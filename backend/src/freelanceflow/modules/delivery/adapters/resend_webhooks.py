"""Authenticated Resend webhook parsing over the official Svix verifier."""

import binascii
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from json import JSONDecodeError

from svix.webhooks import Webhook, WebhookVerificationError

from freelanceflow.modules.delivery.application.provider_events import (
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    VerifiedEmailProviderEvent,
)
from freelanceflow.modules.delivery.domain.provider_events import (
    InvoiceDeliveryProviderEventKind,
)


class InvalidResendWebhookConfiguration(ValueError):
    """The Resend webhook signing secret is absent or unusable."""


_EVENT_KINDS = {
    "email.sent": InvoiceDeliveryProviderEventKind.PROVIDER_ACCEPTED,
    "email.delivered": InvoiceDeliveryProviderEventKind.RECIPIENT_DELIVERED,
    "email.delivery_delayed": InvoiceDeliveryProviderEventKind.DELIVERY_DELAYED,
    "email.bounced": InvoiceDeliveryProviderEventKind.BOUNCED,
    "email.failed": InvoiceDeliveryProviderEventKind.PROVIDER_FAILED,
    "email.complained": InvoiceDeliveryProviderEventKind.COMPLAINED,
}


def load_resend_webhook_secret(
    environ: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if environ is None else environ
    secret = values.get("RESEND_WEBHOOK_SECRET", "")
    if not secret.strip():
        raise InvalidResendWebhookConfiguration(
            "RESEND_WEBHOOK_SECRET must be configured"
        )
    return secret


class ResendWebhookVerifier:
    """Verify exact request bytes before translating trusted event fields."""

    def __init__(self, signing_secret: str) -> None:
        if not isinstance(signing_secret, str) or not signing_secret.strip():
            raise InvalidResendWebhookConfiguration(
                "RESEND_WEBHOOK_SECRET must be configured"
            )
        try:
            self._webhook = Webhook(signing_secret)
        except (ValueError, TypeError, binascii.Error) as error:
            raise InvalidResendWebhookConfiguration(
                "RESEND_WEBHOOK_SECRET is invalid"
            ) from error

    def verify(
        self,
        raw_body: bytes,
        *,
        event_id: str,
        timestamp: str,
        signature: str,
    ) -> VerifiedEmailProviderEvent:
        if not isinstance(raw_body, bytes):
            raise TypeError("Resend webhook body must be raw bytes")
        try:
            payload = self._webhook.verify(
                raw_body,
                {
                    "svix-id": event_id,
                    "svix-timestamp": timestamp,
                    "svix-signature": signature,
                },
            )
        except JSONDecodeError as error:
            raise InvalidWebhookPayload("Verified webhook body must be JSON") from error
        except UnicodeDecodeError as error:
            raise InvalidWebhookPayload("Verified webhook body must be UTF-8 JSON") from error
        except (WebhookVerificationError, ValueError, TypeError, binascii.Error) as error:
            raise InvalidWebhookSignature("Invalid Resend webhook signature") from error

        if not isinstance(payload, dict):
            raise InvalidWebhookPayload("Verified webhook payload must be an object")
        raw_event_type = payload.get("type")
        occurred_at_raw = payload.get("created_at")
        data = payload.get("data")
        if not isinstance(raw_event_type, str) or not raw_event_type.strip():
            raise InvalidWebhookPayload("Verified webhook type must be nonblank")
        if not isinstance(occurred_at_raw, str):
            raise InvalidWebhookPayload("Verified webhook created_at must be a string")
        occurred_at = _parse_utc_timestamp(occurred_at_raw)
        kind = _EVENT_KINDS.get(
            raw_event_type, InvoiceDeliveryProviderEventKind.UNSUPPORTED
        )

        provider_message_id: str | None = None
        if isinstance(data, dict):
            candidate = data.get("email_id")
            if isinstance(candidate, str) and candidate.strip():
                provider_message_id = candidate
        if (
            kind is not InvoiceDeliveryProviderEventKind.UNSUPPORTED
            and provider_message_id is None
        ):
            raise InvalidWebhookPayload(
                "Verified delivery event requires data.email_id"
            )

        return VerifiedEmailProviderEvent(
            provider_event_id=event_id,
            provider_message_id=provider_message_id,
            raw_event_type=raw_event_type,
            kind=kind,
            occurred_at=occurred_at,
            payload_sha256=sha256(raw_body).hexdigest(),
        )


def _parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise InvalidWebhookPayload(
            "Verified webhook created_at must be ISO 8601"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidWebhookPayload(
            "Verified webhook created_at must include a timezone"
        )
    return parsed.astimezone(UTC)
