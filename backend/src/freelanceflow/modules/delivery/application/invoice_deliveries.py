"""Durable InvoiceDelivery use cases and internal worker transitions."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.delivery.application.email_provider import (
    AmbiguousEmailDeliveryError,
    DefinitiveEmailDeliveryError,
    EmailAttachment,
    EmailDeliveryMessage,
    EmailDeliveryProvider,
    FrozenInvoiceAttachment,
    RetryableEmailDeliveryError,
)
from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    ApprovedInvoiceTarget,
    InvalidInvoiceDeliveryTransitionError,
    InvoiceDelivery,
    InvoiceDeliveryMessage,
    InvoiceDeliveryState,
    claim_invoice_delivery,
    fail_invoice_delivery,
    mark_invoice_delivery_ambiguous,
    mark_invoice_delivery_sent,
    prepare_invoice_delivery_message,
    reject_invoice_delivery,
    request_invoice_delivery,
)


class InvoiceDeliveryResourceNotFound(LookupError):
    """A workspace-scoped approval target or delivery is unavailable."""


class InvoiceDeliveryIntegrityError(RuntimeError):
    """Persisted delivery and frozen artifact identity disagree."""


@dataclass(frozen=True)
class InvoiceEmailContent:
    """Caller-prepared presentation content, frozen before its first send."""

    recipient: str
    subject: str
    body: str
    attachment_filename: str


class InvoiceDeliveryStore(Protocol):
    def lock_approval_target(
        self, invoice_id: UUID, revision: int, artifact_id: UUID
    ) -> ApprovedInvoiceTarget | None: ...
    def get_by_approval(self, approval_id: UUID) -> InvoiceDelivery | None: ...
    def add(self, value: InvoiceDelivery) -> None: ...
    def get(self, delivery_id: UUID) -> InvoiceDelivery | None: ...
    def lock_next_pending(self) -> InvoiceDelivery | None: ...
    def lock(self, delivery_id: UUID) -> InvoiceDelivery | None: ...
    def get_frozen_artifact(self, artifact_id: UUID) -> FrozenInvoiceAttachment | None: ...
    def save_message(self, value: InvoiceDelivery) -> None: ...
    def save_claim(self, value: InvoiceDelivery) -> None: ...
    def save_failure(self, value: InvoiceDelivery) -> None: ...
    def save_rejection(self, value: InvoiceDelivery) -> None: ...
    def save_ambiguous(self, value: InvoiceDelivery) -> None: ...
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
        provider_message_id: str,
    ) -> InvoiceDelivery:
        with self.transaction(workspace_id) as store:
            delivery = store.lock(delivery_id)
            if delivery is None:
                raise InvoiceDeliveryResourceNotFound("Invoice delivery resource not found")
            sent = mark_invoice_delivery_sent(
                delivery,
                attempt_id=attempt_id,
                sent_at=self.clock(),
                provider_message_id=provider_message_id,
            )
            store.save_sent(sent)
        return sent

    def record_rejection(
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
            rejected = reject_invoice_delivery(
                delivery,
                attempt_id=attempt_id,
                rejected_at=self.clock(),
                failure_reason=failure_reason,
            )
            store.save_rejection(rejected)
        return rejected

    def record_ambiguous(
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
            ambiguous = mark_invoice_delivery_ambiguous(
                delivery,
                attempt_id=attempt_id,
                observed_at=self.clock(),
                failure_reason=failure_reason,
            )
            store.save_ambiguous(ambiguous)
        return ambiguous


class InvoiceDeliverySender:
    """Send one already-claimed delivery through a provider-neutral boundary."""

    def __init__(
        self,
        transaction: InvoiceDeliveryTransaction,
        provider: EmailDeliveryProvider,
        *,
        sender_identity: str,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.transaction = transaction
        self.provider = provider
        self.sender_identity = sender_identity
        self.delivery_service = InvoiceDeliveryService(transaction, clock=clock)

    def send_claimed(
        self,
        *,
        workspace_id: UUID,
        delivery_id: UUID,
        attempt_id: UUID,
        content: InvoiceEmailContent,
    ) -> InvoiceDelivery:
        message_snapshot = InvoiceDeliveryMessage(
            sender=self.sender_identity,
            recipient=content.recipient,
            subject=content.subject,
            body=content.body,
            attachment_filename=content.attachment_filename,
        )
        with self.transaction(workspace_id) as store:
            delivery = store.lock(delivery_id)
            if delivery is None:
                raise InvoiceDeliveryResourceNotFound("Invoice delivery resource not found")
            if (
                delivery.state is not InvoiceDeliveryState.IN_PROGRESS
                or delivery.active_attempt_id != attempt_id
                or not delivery.attempts
                or delivery.attempts[-1].outcome is not None
            ):
                raise InvalidInvoiceDeliveryTransitionError(
                    "Delivery claim token is stale or invalid"
                )
            prepared = prepare_invoice_delivery_message(
                delivery, message=message_snapshot
            )
            artifact = store.get_frozen_artifact(prepared.artifact_id)
            if artifact is None or (
                artifact.workspace_id != prepared.workspace_id
                or artifact.invoice_id != prepared.invoice_id
                or artifact.invoice_revision != prepared.invoice_revision
                or artifact.sha256 != prepared.artifact_sha256
            ):
                raise InvoiceDeliveryIntegrityError(
                    "Frozen artifact does not match the claimed delivery"
                )
            store.save_message(prepared)

        provider_message = EmailDeliveryMessage(
            sender=message_snapshot.sender,
            recipient=message_snapshot.recipient,
            subject=message_snapshot.subject,
            body=message_snapshot.body,
            attachment=EmailAttachment(
                filename=message_snapshot.attachment_filename,
                media_type=artifact.media_type,
                content=artifact.content,
            ),
        )
        try:
            accepted = self.provider.send(
                provider_message,
                idempotency_key=prepared.provider_operation_key,
            )
        except DefinitiveEmailDeliveryError as error:
            return self.delivery_service.record_rejection(
                workspace_id=workspace_id,
                delivery_id=delivery_id,
                attempt_id=attempt_id,
                failure_reason=error.reason_code,
            )
        except RetryableEmailDeliveryError as error:
            return self.delivery_service.record_failure(
                workspace_id=workspace_id,
                delivery_id=delivery_id,
                attempt_id=attempt_id,
                failure_reason=error.reason_code,
            )
        except AmbiguousEmailDeliveryError as error:
            return self.delivery_service.record_ambiguous(
                workspace_id=workspace_id,
                delivery_id=delivery_id,
                attempt_id=attempt_id,
                failure_reason=error.reason_code,
            )
        return self.delivery_service.record_sent(
            workspace_id=workspace_id,
            delivery_id=delivery_id,
            attempt_id=attempt_id,
            provider_message_id=accepted.provider_message_id,
        )
