import json
from base64 import b64decode
from collections.abc import Mapping

import pytest

from freelanceflow.modules.delivery.adapters.resend import (
    RESEND_EMAILS_URL,
    InvalidResendConfiguration,
    ResendEmailProvider,
    ResendHttpResponse,
    ResendTransportAmbiguousError,
    load_resend_settings,
)
from freelanceflow.modules.delivery.application.email_provider import (
    AmbiguousEmailDeliveryError,
    DefinitiveEmailDeliveryError,
    EmailAttachment,
    EmailDeliveryMessage,
    RetryableEmailDeliveryError,
)


class FakeResendTransport:
    def __init__(
        self,
        response: ResendHttpResponse | None = None,
        error: ResendTransportAmbiguousError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, str], bytes]] = []

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> ResendHttpResponse:
        self.calls.append((url, dict(headers), body))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _message(content: bytes = b"\x00\xffexact\x80bytes") -> EmailDeliveryMessage:
    return EmailDeliveryMessage(
        sender="Freelancer <invoices@example.com>",
        recipient="client@example.net",
        subject="Invoice 2026-09",
        body="Please find the invoice attached.",
        attachment=EmailAttachment(
            filename="invoice.pdf",
            media_type="application/pdf",
            content=content,
        ),
    )


def test_resend_sends_exact_payload_attachment_and_idempotency_key() -> None:
    transport = FakeResendTransport(
        ResendHttpResponse(200, b'{"id":"resend-message-123"}')
    )
    provider = ResendEmailProvider(api_key="re_secret", transport=transport)

    accepted = provider.send(
        _message(), idempotency_key="invoice-delivery/00000000-0000-0000-0000-000000000001"
    )

    assert accepted.provider_message_id == "resend-message-123"
    assert len(transport.calls) == 1
    url, headers, raw_body = transport.calls[0]
    assert url == RESEND_EMAILS_URL
    assert headers["Idempotency-Key"] == (
        "invoice-delivery/00000000-0000-0000-0000-000000000001"
    )
    assert headers["Authorization"] == "Bearer re_secret"
    payload = json.loads(raw_body)
    assert payload["from"] == "Freelancer <invoices@example.com>"
    assert payload["to"] == ["client@example.net"]
    assert payload["subject"] == "Invoice 2026-09"
    assert payload["text"] == "Please find the invoice attached."
    attachment = payload["attachments"][0]
    assert attachment["filename"] == "invoice.pdf"
    assert attachment["content_type"] == "application/pdf"
    assert b64decode(attachment["content"]) == b"\x00\xffexact\x80bytes"


@pytest.mark.parametrize(
    "response,error_type,reason",
    [
        (
            ResendHttpResponse(
                422, b'{"name":"invalid_from_address","message":"detail"}'
            ),
            DefinitiveEmailDeliveryError,
            "invalid_from_address",
        ),
        (
            ResendHttpResponse(409, b'{"name":"invalid_idempotent_request"}'),
            DefinitiveEmailDeliveryError,
            "invalid_idempotent_request",
        ),
        (
            ResendHttpResponse(409, b'{"name":"concurrent_idempotent_requests"}'),
            RetryableEmailDeliveryError,
            "concurrent_idempotent_requests",
        ),
        (
            ResendHttpResponse(429, b'{"name":"rate_limit_exceeded"}'),
            RetryableEmailDeliveryError,
            "rate_limit_exceeded",
        ),
        (
            ResendHttpResponse(500, b'{"name":"internal_server_error"}'),
            AmbiguousEmailDeliveryError,
            "internal_server_error",
        ),
        (
            ResendHttpResponse(408, b'{"name":"request_timeout"}'),
            AmbiguousEmailDeliveryError,
            "request_timeout",
        ),
        (
            ResendHttpResponse(200, b'{"unexpected":"response"}'),
            AmbiguousEmailDeliveryError,
            "accepted_response_missing_email_id",
        ),
    ],
)
def test_resend_maps_provider_responses_without_leaking_http_types(
    response: ResendHttpResponse,
    error_type: type[Exception],
    reason: str,
) -> None:
    provider = ResendEmailProvider(
        api_key="re_never_leak_this", transport=FakeResendTransport(response)
    )

    with pytest.raises(error_type, match=reason) as captured:
        provider.send(_message(), idempotency_key="invoice-delivery/test")

    assert "re_never_leak_this" not in str(captured.value)
    assert not isinstance(captured.value, ResendTransportAmbiguousError)


def test_resend_maps_transport_timeout_to_ambiguous_without_secret_leak() -> None:
    provider = ResendEmailProvider(
        api_key="re_never_leak_this",
        transport=FakeResendTransport(
            error=ResendTransportAmbiguousError("socket timed out")
        ),
    )

    with pytest.raises(AmbiguousEmailDeliveryError, match="transport_outcome_unknown") as captured:
        provider.send(_message(), idempotency_key="invoice-delivery/test")

    assert "re_never_leak_this" not in str(captured.value)


def test_resend_settings_require_explicit_environment_values() -> None:
    settings = load_resend_settings(
        {
            "RESEND_API_KEY": "re_configured",
            "RESEND_SENDER": "Freelancer <invoices@example.com>",
        }
    )
    assert settings.api_key == "re_configured"
    assert settings.sender_identity == "Freelancer <invoices@example.com>"

    with pytest.raises(InvalidResendConfiguration, match="RESEND_API_KEY"):
        load_resend_settings({})
    with pytest.raises(InvalidResendConfiguration, match="RESEND_SENDER"):
        load_resend_settings({"RESEND_API_KEY": "re_configured"})
