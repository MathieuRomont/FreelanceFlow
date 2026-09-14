"""Durable InvoiceDelivery use cases and internal worker transitions."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    ApprovedInvoiceTarget,
    InvoiceDelivery,
    claim_invoice_delivery,
    fail_invoice_delivery,
    mark_invoice_delivery_sent,
    request_invoice_delivery,
)


class InvoiceDeliveryResourceNotFound(LookupError):
    """A workspace-scoped approval target or delivery is unavailable."""


class InvoiceDeliveryStore(Protocol):
    def lock_approval_target(
        self, invoice_id: UUID, revision: int, artifact_id: UUID
    ) -> ApprovedInvoiceTarget | None: ...
    def get_by_approval(self, approval_id: UUID) -> InvoiceDelivery | None: ...
    def add(self, value: InvoiceDelivery) -> None: ...
    def get(self, delivery_id: UUID) -> InvoiceDelivery | None: ...
    def lock_next_pending(self) -> InvoiceDelivery | None: ...
    def lock(self, delivery_id: UUID) -> InvoiceDelivery | None: ...
    def save_claim(self, value: InvoiceDelivery) -> None: ...
    def save_failure(self, value: InvoiceDelivery) -> None: ...
    def save_sent(self, value: InvoiceDelivery) -> None: ...


class InvoiceDeliveryTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[InvoiceDeliveryStore]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvoiceDeliveryService:
    def __init__(
        self,
        transaction: InvoiceDeliveryTransaction,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.transaction = transaction
        self.clock = clock

    def request(
        self,
        *,
        workspace_id: UUID,
        invoice_id: UUID,
        revision: int,
        artifact_id: UUID,
    ) -> InvoiceDelivery:
        with self.transaction(workspace_id) as store:
            target = store.lock_approval_target(invoice_id, revision, artifact_id)
            if target is None:
                raise InvoiceDeliveryResourceNotFound("Invoice delivery resource not found")
            existing = store.get_by_approval(target.approval_id)
            if existing is not None:
                return existing
            delivery = request_invoice_delivery(
                delivery_id=uuid4(), target=target, requested_at=self.clock()
            )
            store.add(delivery)
        return delivery

    def get(self, workspace_id: UUID, delivery_id: UUID) -> InvoiceDelivery:
        with self.transaction(workspace_id) as store:
            delivery = store.get(delivery_id)
            if delivery is None:
                raise InvoiceDeliveryResourceNotFound("Invoice delivery resource not found")
        return delivery

    def claim_next(self, workspace_id: UUID) -> InvoiceDelivery | None:
        with self.transaction(workspace_id) as store:
            delivery = store.lock_next_pending()
            if delivery is None:
                return None
            claimed = claim_invoice_delivery(delivery, attempt_id=uuid4(), started_at=self.clock())
            store.save_claim(claimed)
        return claimed

    def record_failure(
        self,
        *,
        workspace_id: UUID,
        delivery_id: UUID,
        attempt_id: UUID,
        failure_reason: str,
    ) -> InvoiceDelivery:
        with self.transaction(workspace_id) as store:
            delivery = store.lock(delivery_id)
            if delivery is None:
                raise InvoiceDeliveryResourceNotFound("Invoice delivery resource not found")
            failed = fail_invoice_delivery(
                delivery,
                attempt_id=attempt_id,
                failed_at=self.clock(),
                failure_reason=failure_reason,
            )
            store.save_failure(failed)
        return failed

    def record_sent(
        self,
        *,
        workspace_id: UUID,
        delivery_id: UUID,
        attempt_id: UUID,
    ) -> InvoiceDelivery:
        with self.transaction(workspace_id) as store:
            delivery = store.lock(delivery_id)
            if delivery is None:
                raise InvoiceDeliveryResourceNotFound("Invoice delivery resource not found")
            sent = mark_invoice_delivery_sent(delivery, attempt_id=attempt_id, sent_at=self.clock())
            store.save_sent(sent)
        return sent
