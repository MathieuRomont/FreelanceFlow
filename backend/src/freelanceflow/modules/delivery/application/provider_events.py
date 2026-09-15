"""Verified email-provider event ingestion and durable correlation."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from re import fullmatch
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.delivery.domain.provider_events import (
    InvoiceDeliveryProviderEvent,
    InvoiceDeliveryProviderEventKind,
    InvoiceDeliveryProviderEventMatch,
    InvoiceDeliveryProviderEventRecord,
)


class InvalidWebhookSignature(ValueError):
    """Required signature material is absent, stale, or invalid."""


class InvalidWebhookPayload(ValueError):
    """A verified webhook payload is not structurally usable."""


class ProviderEventIdentityConflict(RuntimeError):
    """One provider event identity was reused for different immutable facts."""


class InvoiceDeliveryProviderEventResourceNotFound(LookupError):
    """A workspace-scoped delivery event resource is unavailable."""


@dataclass(frozen=True)
class VerifiedEmailProviderEvent:
    """Minimal trusted event returned only after raw-body verification."""

    provider_event_id: str
    provider_message_id: str | None
    raw_event_type: str
    kind: InvoiceDeliveryProviderEventKind
    occurred_at: datetime
    payload_sha256: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider_event_id, "Provider event identity"),
            (self.raw_event_type, "Provider event type"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise InvalidWebhookPayload(f"{label} must be nonblank")
        if self.provider_message_id is not None and (
            not isinstance(self.provider_message_id, str)
            or not self.provider_message_id.strip()
        ):
            raise InvalidWebhookPayload(
                "Provider message identity must be nonblank when present"
            )
        if not isinstance(self.kind, InvoiceDeliveryProviderEventKind):
            raise InvalidWebhookPayload("Provider event kind is invalid")
        if (
            self.kind is not InvoiceDeliveryProviderEventKind.UNSUPPORTED
            and self.provider_message_id is None
        ):
            raise InvalidWebhookPayload(
                "Supported delivery events require a provider message identity"
            )
        if not isinstance(self.occurred_at, datetime) or (
            self.occurred_at.utcoffset() != timedelta(0)
        ):
            raise InvalidWebhookPayload("Provider event occurrence time must be UTC")
        if (
            not isinstance(self.payload_sha256, str)
            or fullmatch(r"[0-9a-f]{64}", self.payload_sha256) is None
        ):
            raise InvalidWebhookPayload(
                "Provider event payload SHA-256 must be lowercase hexadecimal"
            )


class EmailProviderWebhookVerifier(Protocol):
    def verify(
        self,
        raw_body: bytes,
        *,
        event_id: str,
        timestamp: str,
        signature: str,
    ) -> VerifiedEmailProviderEvent: ...


@dataclass(frozen=True)
class ProviderMessageDeliveryTarget:
    delivery_id: UUID
    workspace_id: UUID


class InvoiceDeliveryProviderEventStore(Protocol):
    def lock_provider_message_id(self, provider_message_id: str) -> None: ...
    def add_or_get(
        self, value: InvoiceDeliveryProviderEvent
    ) -> InvoiceDeliveryProviderEvent: ...
    def get_match(
        self, event_id: UUID
    ) -> InvoiceDeliveryProviderEventMatch | None: ...
    def find_delivery_target(
        self, provider_message_id: str
    ) -> ProviderMessageDeliveryTarget | None: ...
    def add_match(self, value: InvoiceDeliveryProviderEventMatch) -> None: ...
    def delivery_exists(self, workspace_id: UUID, delivery_id: UUID) -> bool: ...
    def list_for_delivery(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> tuple[InvoiceDeliveryProviderEventRecord, ...]: ...


class InvoiceDeliveryProviderEventTransaction(Protocol):
    def __call__(
        self,
    ) -> AbstractContextManager[InvoiceDeliveryProviderEventStore]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvoiceDeliveryProviderEventService:
    def __init__(
        self,
        transaction: InvoiceDeliveryProviderEventTransaction,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.transaction = transaction
        self.clock = clock

    def ingest(
        self, verified: VerifiedEmailProviderEvent
    ) -> InvoiceDeliveryProviderEventRecord:
        if not isinstance(verified, VerifiedEmailProviderEvent):
            raise TypeError("Webhook ingestion requires a verified provider event")
        received_at = self.clock()
        event = InvoiceDeliveryProviderEvent(
            id=uuid4(),
            provider_event_id=verified.provider_event_id,
            provider_message_id=verified.provider_message_id,
            raw_event_type=verified.raw_event_type,
            kind=verified.kind,
            occurred_at=verified.occurred_at,
            received_at=received_at,
            payload_sha256=verified.payload_sha256,
        )
        with self.transaction() as store:
            if event.provider_message_id is not None:
                store.lock_provider_message_id(event.provider_message_id)
            persisted = store.add_or_get(event)
            match = store.get_match(persisted.id)
            if match is None and persisted.provider_message_id is not None:
                target = store.find_delivery_target(persisted.provider_message_id)
                if target is not None:
                    match = InvoiceDeliveryProviderEventMatch(
                        event_id=persisted.id,
                        delivery_id=target.delivery_id,
                        workspace_id=target.workspace_id,
                        provider_message_id=persisted.provider_message_id,
                        correlated_at=received_at,
                    )
                    store.add_match(match)
        return InvoiceDeliveryProviderEventRecord(event=persisted, match=match)

    def list_for_delivery(
        self, *, workspace_id: UUID, delivery_id: UUID
    ) -> tuple[InvoiceDeliveryProviderEventRecord, ...]:
        with self.transaction() as store:
            if not store.delivery_exists(workspace_id, delivery_id):
                raise InvoiceDeliveryProviderEventResourceNotFound(
                    "Invoice delivery resource not found"
                )
            return store.list_for_delivery(workspace_id, delivery_id)
