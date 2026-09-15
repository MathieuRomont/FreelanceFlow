"""Immutable provider delivery facts and their append-only correlation."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from re import fullmatch
from uuid import UUID


class InvalidInvoiceDeliveryProviderEvent(ValueError):
    """A verified provider event or correlation is structurally invalid."""


class InvoiceDeliveryProviderEventKind(StrEnum):
    PROVIDER_ACCEPTED = "provider_accepted"
    RECIPIENT_DELIVERED = "recipient_delivered"
    DELIVERY_DELAYED = "delivery_delayed"
    BOUNCED = "bounced"
    PROVIDER_FAILED = "provider_failed"
    COMPLAINED = "complained"
    UNSUPPORTED = "unsupported"


def _require_utc(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise InvalidInvoiceDeliveryProviderEvent(f"{label} must be UTC")


@dataclass(frozen=True)
class InvoiceDeliveryProviderEvent:
    """One verified provider fact; receipt retries share provider_event_id."""

    id: UUID
    provider_event_id: str
    provider_message_id: str | None
    raw_event_type: str
    kind: InvoiceDeliveryProviderEventKind
    occurred_at: datetime
    received_at: datetime
    payload_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise InvalidInvoiceDeliveryProviderEvent("Provider event ID must be a UUID")
        for value, label in (
            (self.provider_event_id, "Provider event identity"),
            (self.raw_event_type, "Provider event type"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise InvalidInvoiceDeliveryProviderEvent(f"{label} must be nonblank")
        if self.provider_message_id is not None and (
            not isinstance(self.provider_message_id, str)
            or not self.provider_message_id.strip()
        ):
            raise InvalidInvoiceDeliveryProviderEvent(
                "Provider message identity must be nonblank when present"
            )
        if (
            self.kind is not InvoiceDeliveryProviderEventKind.UNSUPPORTED
            and self.provider_message_id is None
        ):
            raise InvalidInvoiceDeliveryProviderEvent(
                "Supported delivery events require a provider message identity"
            )
        if not isinstance(self.kind, InvoiceDeliveryProviderEventKind):
            raise InvalidInvoiceDeliveryProviderEvent("Provider event kind is invalid")
        _require_utc(self.occurred_at, "Provider event occurrence time")
        _require_utc(self.received_at, "Provider event receipt time")
        if (
            not isinstance(self.payload_sha256, str)
            or fullmatch(r"[0-9a-f]{64}", self.payload_sha256) is None
        ):
            raise InvalidInvoiceDeliveryProviderEvent(
                "Provider event payload SHA-256 must be lowercase hexadecimal"
            )


@dataclass(frozen=True)
class InvoiceDeliveryProviderEventMatch:
    """Append-only correlation from one event to its exact logical delivery."""

    event_id: UUID
    delivery_id: UUID
    workspace_id: UUID
    provider_message_id: str
    correlated_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (self.event_id, self.delivery_id, self.workspace_id)
        ):
            raise InvalidInvoiceDeliveryProviderEvent(
                "Provider event correlation identities must be UUIDs"
            )
        if (
            not isinstance(self.provider_message_id, str)
            or not self.provider_message_id.strip()
        ):
            raise InvalidInvoiceDeliveryProviderEvent(
                "Correlated provider message identity must be nonblank"
            )
        _require_utc(self.correlated_at, "Provider event correlation time")


@dataclass(frozen=True)
class InvoiceDeliveryProviderEventRecord:
    event: InvoiceDeliveryProviderEvent
    match: InvoiceDeliveryProviderEventMatch | None

    def __post_init__(self) -> None:
        if not isinstance(self.event, InvoiceDeliveryProviderEvent):
            raise InvalidInvoiceDeliveryProviderEvent("Provider event is invalid")
        if self.match is not None and (
            not isinstance(self.match, InvoiceDeliveryProviderEventMatch)
            or self.match.event_id != self.event.id
            or self.match.provider_message_id != self.event.provider_message_id
        ):
            raise InvalidInvoiceDeliveryProviderEvent(
                "Provider event correlation does not match its event"
            )
