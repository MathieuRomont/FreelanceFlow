import json
from base64 import b64encode
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from svix.webhooks import Webhook

from freelanceflow.modules.delivery.adapters.resend_webhooks import (
    InvalidResendWebhookConfiguration,
    ResendWebhookVerifier,
    load_resend_webhook_secret,
)
from freelanceflow.modules.delivery.application.provider_events import (
    InvalidWebhookPayload,
    InvalidWebhookSignature,
)
from freelanceflow.modules.delivery.domain.provider_events import (
    InvoiceDeliveryProviderEventKind,
)

WEBHOOK_SECRET = "whsec_" + b64encode(b"freelanceflow-test-webhook-secret").decode()


def _raw_payload(
    event_type: str = "email.delivered",
    *,
    provider_message_id: str | None = "resend-message-1",
) -> bytes:
    data: dict[str, object] = {"to": ["client@example.net"]}
    if provider_message_id is not None:
        data["email_id"] = provider_message_id
    return json.dumps(
        {
            "type": event_type,
            "created_at": "2026-09-15T10:11:12.123456Z",
            "data": data,
        },
        separators=(",", ":"),
    ).encode()


def _signature(raw_body: bytes, event_id: str = "msg_webhook_1") -> tuple[str, str]:
    timestamp = datetime.now(UTC)
    signature = Webhook(WEBHOOK_SECRET).sign(
        event_id, timestamp, raw_body.decode("utf-8")
    )
    return str(int(timestamp.timestamp())), signature


@pytest.mark.parametrize(
    "event_type,kind",
    [
        ("email.sent", InvoiceDeliveryProviderEventKind.PROVIDER_ACCEPTED),
        ("email.delivered", InvoiceDeliveryProviderEventKind.RECIPIENT_DELIVERED),
        ("email.delivery_delayed", InvoiceDeliveryProviderEventKind.DELIVERY_DELAYED),
        ("email.bounced", InvoiceDeliveryProviderEventKind.BOUNCED),
        ("email.failed", InvoiceDeliveryProviderEventKind.PROVIDER_FAILED),
        ("email.complained", InvoiceDeliveryProviderEventKind.COMPLAINED),
    ],
)
def test_resend_verifies_and_maps_supported_events(
    event_type: str, kind: InvoiceDeliveryProviderEventKind
) -> None:
    raw_body = _raw_payload(event_type)
    timestamp, signature = _signature(raw_body)

    verified = ResendWebhookVerifier(WEBHOOK_SECRET).verify(
        raw_body,
        event_id="msg_webhook_1",
        timestamp=timestamp,
        signature=signature,
    )

    assert verified.provider_event_id == "msg_webhook_1"
    assert verified.provider_message_id == "resend-message-1"
    assert verified.raw_event_type == event_type
    assert verified.kind is kind
    assert verified.occurred_at == datetime(
        2026, 9, 15, 10, 11, 12, 123456, tzinfo=UTC
    )
    assert verified.payload_sha256 == sha256(raw_body).hexdigest()


def test_resend_signature_is_over_exact_raw_body() -> None:
    raw_body = _raw_payload()
    timestamp, signature = _signature(raw_body)
    reformatted = json.dumps(json.loads(raw_body), indent=2).encode()

    with pytest.raises(InvalidWebhookSignature, match="Invalid Resend"):
        ResendWebhookVerifier(WEBHOOK_SECRET).verify(
            reformatted,
            event_id="msg_webhook_1",
            timestamp=timestamp,
            signature=signature,
        )


@pytest.mark.parametrize(
    "event_id,timestamp,signature",
    [
        ("", "1", "v1,invalid"),
        ("msg_webhook_1", "not-a-timestamp", "v1,invalid"),
        ("msg_webhook_1", "1", "malformed"),
    ],
)
def test_resend_rejects_malformed_signature_headers(
    event_id: str, timestamp: str, signature: str
) -> None:
    with pytest.raises(InvalidWebhookSignature):
        ResendWebhookVerifier(WEBHOOK_SECRET).verify(
            _raw_payload(),
            event_id=event_id,
            timestamp=timestamp,
            signature=signature,
        )


def test_invalid_signature_is_rejected_before_malformed_json_is_parsed() -> None:
    with pytest.raises(InvalidWebhookSignature):
        ResendWebhookVerifier(WEBHOOK_SECRET).verify(
            b"not json",
            event_id="msg_webhook_1",
            timestamp=str(int(datetime.now(UTC).timestamp())),
            signature="v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        )


def test_validly_signed_malformed_json_is_rejected_as_payload() -> None:
    raw_body = b"not json"
    timestamp, signature = _signature(raw_body)

    with pytest.raises(InvalidWebhookPayload, match="must be JSON"):
        ResendWebhookVerifier(WEBHOOK_SECRET).verify(
            raw_body,
            event_id="msg_webhook_1",
            timestamp=timestamp,
            signature=signature,
        )


def test_unsupported_verified_event_is_preserved_without_email_identity() -> None:
    raw_body = _raw_payload("email.opened", provider_message_id=None)
    timestamp, signature = _signature(raw_body, "msg_webhook_unsupported")

    verified = ResendWebhookVerifier(WEBHOOK_SECRET).verify(
        raw_body,
        event_id="msg_webhook_unsupported",
        timestamp=timestamp,
        signature=signature,
    )

    assert verified.kind is InvoiceDeliveryProviderEventKind.UNSUPPORTED
    assert verified.provider_message_id is None


def test_supported_event_requires_email_identity_after_verification() -> None:
    raw_body = _raw_payload(provider_message_id=None)
    timestamp, signature = _signature(raw_body, "msg_webhook_missing_email")

    with pytest.raises(InvalidWebhookPayload, match="data.email_id"):
        ResendWebhookVerifier(WEBHOOK_SECRET).verify(
            raw_body,
            event_id="msg_webhook_missing_email",
            timestamp=timestamp,
            signature=signature,
        )


def test_webhook_configuration_is_explicit_and_secret_is_not_exposed() -> None:
    assert (
        load_resend_webhook_secret({"RESEND_WEBHOOK_SECRET": WEBHOOK_SECRET})
        == WEBHOOK_SECRET
    )
    with pytest.raises(
        InvalidResendWebhookConfiguration, match="RESEND_WEBHOOK_SECRET"
    ) as captured:
        load_resend_webhook_secret({})
    assert WEBHOOK_SECRET not in str(captured.value)
