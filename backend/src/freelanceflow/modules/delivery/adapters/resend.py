"""Resend Email API adapter with provider-neutral failure semantics."""

import json
import os
from base64 import b64encode
from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from freelanceflow.modules.delivery.application.email_provider import (
    AmbiguousEmailDeliveryError,
    DefinitiveEmailDeliveryError,
    EmailAccepted,
    EmailDeliveryMessage,
    RetryableEmailDeliveryError,
)

RESEND_EMAILS_URL = "https://api.resend.com/emails"


class InvalidResendConfiguration(ValueError):
    """Required Resend configuration is absent or blank."""


@dataclass(frozen=True)
class ResendSettings:
    api_key: str
    sender_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise InvalidResendConfiguration("RESEND_API_KEY must be configured")
        if not isinstance(self.sender_identity, str) or not self.sender_identity.strip():
            raise InvalidResendConfiguration("RESEND_SENDER must be configured")


def load_resend_settings(
    environ: Mapping[str, str] | None = None,
) -> ResendSettings:
    values = os.environ if environ is None else environ
    return ResendSettings(
        api_key=values.get("RESEND_API_KEY", ""),
        sender_identity=values.get("RESEND_SENDER", ""),
    )


@dataclass(frozen=True)
class ResendHttpResponse:
    status_code: int
    body: bytes


class ResendTransportAmbiguousError(RuntimeError):
    """No authoritative HTTP response was received."""


class ResendHttpTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> ResendHttpResponse: ...


class UrllibResendHttpTransport:
    """Small standard-library transport; provider behavior stays in the adapter."""

    def __init__(self, *, timeout_seconds: int = 30) -> None:
        if type(timeout_seconds) is not int or timeout_seconds < 1:
            raise ValueError("Resend timeout must be a positive integer")
        self.timeout_seconds = timeout_seconds

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> ResendHttpResponse:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                return ResendHttpResponse(
                    status_code=response.status,
                    body=response.read(),
                )
        except HTTPError as error:
            return ResendHttpResponse(status_code=error.code, body=error.read())
        except (TimeoutError, URLError) as error:
            raise ResendTransportAmbiguousError(
                "Resend request completed without an authoritative response"
            ) from error


class ResendEmailProvider:
    def __init__(
        self,
        *,
        api_key: str,
        transport: ResendHttpTransport,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise InvalidResendConfiguration("RESEND_API_KEY must be configured")
        self._api_key = api_key
        self._transport = transport

    def send(
        self, message: EmailDeliveryMessage, *, idempotency_key: str
    ) -> EmailAccepted:
        if not isinstance(message, EmailDeliveryMessage):
            raise TypeError("Resend requires a provider-neutral email message")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("Resend idempotency key must be nonblank")
        if len(idempotency_key) > 256:
            raise DefinitiveEmailDeliveryError("invalid_idempotency_key")

        payload = {
            "from": message.sender,
            "to": [message.recipient],
            "subject": message.subject,
            "text": message.body,
            "attachments": [
                {
                    "filename": message.attachment.filename,
                    "content_type": message.attachment.media_type,
                    "content": b64encode(message.attachment.content).decode("ascii"),
                }
            ],
        }
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            response = self._transport.post(
                url=RESEND_EMAILS_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idempotency_key,
                    "User-Agent": "FreelanceFlow/0.1",
                },
                body=body,
            )
        except ResendTransportAmbiguousError as error:
            raise AmbiguousEmailDeliveryError("transport_outcome_unknown") from error

        if 200 <= response.status_code < 300:
            provider_message_id = _response_email_id(response.body)
            if provider_message_id is None:
                raise AmbiguousEmailDeliveryError("accepted_response_missing_email_id")
            return EmailAccepted(provider_message_id=provider_message_id)

        error_name = _response_error_name(response.body)
        reason = error_name or f"resend_http_{response.status_code}"
        if response.status_code == 408:
            raise AmbiguousEmailDeliveryError(reason)
        if response.status_code == 429:
            raise RetryableEmailDeliveryError(reason)
        if (
            response.status_code == 409
            and error_name == "concurrent_idempotent_requests"
        ):
            raise RetryableEmailDeliveryError(reason)
        if 400 <= response.status_code < 500:
            raise DefinitiveEmailDeliveryError(reason)
        if response.status_code >= 500:
            # Resend recommends retrying server errors, but a response does not prove
            # that email acceptance did not occur. Its idempotency window is finite,
            # so the durable workflow must reconcile rather than allow an unbounded
            # retry that could later duplicate the external action.
            raise AmbiguousEmailDeliveryError(reason)
        raise AmbiguousEmailDeliveryError(reason)


def _response_email_id(body: bytes) -> str | None:
    value = _json_object(body).get("id")
    return value if isinstance(value, str) and value.strip() else None


def _response_error_name(body: bytes) -> str | None:
    value = _json_object(body).get("name")
    if not isinstance(value, str) or not value:
        return None
    if len(value) > 100 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value
    ):
        return None
    return value


def _json_object(body: bytes) -> dict[str, object]:
    try:
        value = json.loads(body)
    except (JSONDecodeError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
