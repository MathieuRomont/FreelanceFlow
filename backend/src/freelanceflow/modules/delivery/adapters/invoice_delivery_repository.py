"""PostgreSQL persistence for durable invoice delivery state."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.models import (
    InvoiceApprovalRow,
    InvoiceArtifactRow,
)
from freelanceflow.modules.delivery.adapters.models import (
    InvoiceDeliveryAttemptRow,
    InvoiceDeliveryRow,
)
from freelanceflow.modules.delivery.adapters.provider_event_repository import (
    reconcile_provider_events,
)
from freelanceflow.modules.delivery.adapters.provider_message_lock import (
    lock_provider_message_id,
)
from freelanceflow.modules.delivery.application.email_provider import (
    FrozenInvoiceAttachment,
)
from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    ApprovedInvoiceTarget,
    InvalidInvoiceDeliveryTransitionError,
    InvoiceDelivery,
    InvoiceDeliveryAttempt,
    InvoiceDeliveryAttemptOutcome,
    InvoiceDeliveryMessage,
    InvoiceDeliveryState,
)


def _approved_target(row: InvoiceApprovalRow) -> ApprovedInvoiceTarget:
    return ApprovedInvoiceTarget(
        approval_id=row.id,
        workspace_id=row.workspace_id,
        invoice_id=row.invoice_draft_id,
        invoice_revision=row.invoice_revision,
        artifact_id=row.artifact_id,
        artifact_sha256=row.artifact_sha256,
        approved_at=row.approved_at,
    )


def _attempt(row: InvoiceDeliveryAttemptRow) -> InvoiceDeliveryAttempt:
    return InvoiceDeliveryAttempt(
        id=row.id,
        delivery_id=row.delivery_id,
        sequence=row.sequence,
        started_at=row.started_at,
        completed_at=row.completed_at,
        outcome=(InvoiceDeliveryAttemptOutcome(row.outcome) if row.outcome is not None else None),
        failure_reason=row.failure_reason,
        provider_message_id=row.provider_message_id,
    )


def _message(row: InvoiceDeliveryRow) -> InvoiceDeliveryMessage | None:
    values = (
        row.sender,
        row.recipient,
        row.subject,
        row.body,
        row.attachment_filename,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("Persisted delivery message snapshot is incomplete")
    assert row.sender is not None
    assert row.recipient is not None
    assert row.subject is not None
    assert row.body is not None
    assert row.attachment_filename is not None
    return InvoiceDeliveryMessage(
        sender=row.sender,
        recipient=row.recipient,
        subject=row.subject,
        body=row.body,
        attachment_filename=row.attachment_filename,
    )


class InvoiceDeliveryRepository:
    def __init__(self, session: Session, *, workspace_id: UUID) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def lock_approval_target(
        self, invoice_id: UUID, revision: int, artifact_id: UUID
    ) -> ApprovedInvoiceTarget | None:
        row = self.session.scalar(
            select(InvoiceApprovalRow)
            .where(
                InvoiceApprovalRow.workspace_id == self.workspace_id,
                InvoiceApprovalRow.invoice_draft_id == invoice_id,
                InvoiceApprovalRow.invoice_revision == revision,
                InvoiceApprovalRow.artifact_id == artifact_id,
            )
            .with_for_update()
        )
        return _approved_target(row) if row is not None else None

    def get_by_approval(self, approval_id: UUID) -> InvoiceDelivery | None:
        row = self.session.scalar(
            select(InvoiceDeliveryRow).where(
                InvoiceDeliveryRow.workspace_id == self.workspace_id,
                InvoiceDeliveryRow.approval_id == approval_id,
            )
        )
        return self._delivery(row) if row is not None else None

    def add(self, value: InvoiceDelivery) -> None:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        if value.state is not InvoiceDeliveryState.PENDING or value.attempts:
            raise ValueError("A new delivery must be pending without attempts")
        self.session.add(
            InvoiceDeliveryRow(
                id=value.id,
                workspace_id=value.workspace_id,
                approval_id=value.approval_id,
                invoice_draft_id=value.invoice_id,
                invoice_revision=value.invoice_revision,
                artifact_id=value.artifact_id,
                artifact_sha256=value.artifact_sha256,
                state=value.state.value,
                requested_at=value.requested_at,
                active_attempt_id=None,
                sent_at=None,
                attempt_count=0,
                sender=None,
                recipient=None,
                subject=None,
                body=None,
                attachment_filename=None,
            )
        )
        self.session.flush()

    def get(self, delivery_id: UUID) -> InvoiceDelivery | None:
        row = self.session.scalar(
            select(InvoiceDeliveryRow).where(
                InvoiceDeliveryRow.id == delivery_id,
                InvoiceDeliveryRow.workspace_id == self.workspace_id,
            )
        )
        return self._delivery(row) if row is not None else None

    def lock_next_pending(self) -> InvoiceDelivery | None:
        row = self.session.scalar(
            select(InvoiceDeliveryRow)
            .where(
                InvoiceDeliveryRow.workspace_id == self.workspace_id,
                InvoiceDeliveryRow.state == InvoiceDeliveryState.PENDING.value,
            )
            .order_by(InvoiceDeliveryRow.requested_at, InvoiceDeliveryRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return self._delivery(row) if row is not None else None

    def lock(self, delivery_id: UUID) -> InvoiceDelivery | None:
        row = self.session.scalar(
            select(InvoiceDeliveryRow)
            .where(
                InvoiceDeliveryRow.id == delivery_id,
                InvoiceDeliveryRow.workspace_id == self.workspace_id,
            )
            .with_for_update()
        )
        return self._delivery(row) if row is not None else None

    def get_frozen_artifact(
        self, artifact_id: UUID
    ) -> FrozenInvoiceAttachment | None:
        row = self.session.scalar(
            select(InvoiceArtifactRow).where(
                InvoiceArtifactRow.id == artifact_id,
                InvoiceArtifactRow.workspace_id == self.workspace_id,
            )
        )
        if row is None:
            return None
        return FrozenInvoiceAttachment(
            id=row.id,
            workspace_id=row.workspace_id,
            invoice_id=row.invoice_draft_id,
            invoice_revision=row.invoice_revision,
            sha256=row.sha256,
            media_type=row.media_type,
            content=row.content,
        )

    def lock_provider_message_id(self, provider_message_id: str) -> None:
        lock_provider_message_id(self.session, provider_message_id)

    def reconcile_provider_events(
        self,
        *,
        delivery_id: UUID,
        provider_message_id: str,
        correlated_at: datetime,
    ) -> None:
        reconcile_provider_events(
            self.session,
            delivery_id=delivery_id,
            workspace_id=self.workspace_id,
            provider_message_id=provider_message_id,
            correlated_at=correlated_at,
        )

    def save_message(self, value: InvoiceDelivery) -> None:
        row = self._owned_row(value.id)
        if (
            row.state != InvoiceDeliveryState.IN_PROGRESS.value
            or row.active_attempt_id != value.active_attempt_id
            or value.message is None
        ):
            raise InvalidInvoiceDeliveryTransitionError(
                "Persisted delivery message cannot be prepared"
            )
        existing = _message(row)
        if existing is not None and existing != value.message:
            raise InvalidInvoiceDeliveryTransitionError(
                "Delivery message cannot change between attempts"
            )
        row.sender = value.message.sender
        row.recipient = value.message.recipient
        row.subject = value.message.subject
        row.body = value.message.body
        row.attachment_filename = value.message.attachment_filename
        self.session.flush()

    def save_claim(self, value: InvoiceDelivery) -> None:
        row = self._owned_row(value.id)
        if (
            row.state != InvoiceDeliveryState.PENDING.value
            or value.state is not InvoiceDeliveryState.IN_PROGRESS
            or len(value.attempts) != row.attempt_count + 1
            or value.active_attempt_id is None
        ):
            raise InvalidInvoiceDeliveryTransitionError("Persisted delivery is not claimable")
        attempt = value.attempts[-1]
        if attempt.id != value.active_attempt_id or attempt.outcome is not None:
            raise InvalidInvoiceDeliveryTransitionError("Delivery claim is inconsistent")
        self.session.add(
            InvoiceDeliveryAttemptRow(
                id=attempt.id,
                delivery_id=value.id,
                workspace_id=value.workspace_id,
                sequence=attempt.sequence,
                started_at=attempt.started_at,
                completed_at=None,
                outcome=None,
                failure_reason=None,
                provider_message_id=None,
            )
        )
        row.state = value.state.value
        row.active_attempt_id = attempt.id
        row.attempt_count = len(value.attempts)
        self.session.flush()

    def save_failure(self, value: InvoiceDelivery) -> None:
        row, attempt_row = self._active_rows(value)
        attempt = value.attempts[-1]
        if (
            value.state is not InvoiceDeliveryState.PENDING
            or attempt.outcome is not InvoiceDeliveryAttemptOutcome.FAILED
        ):
            raise InvalidInvoiceDeliveryTransitionError(
                "Delivery failure transition is inconsistent"
            )
        attempt_row.completed_at = attempt.completed_at
        attempt_row.outcome = attempt.outcome.value
        attempt_row.failure_reason = attempt.failure_reason
        row.state = value.state.value
        row.active_attempt_id = None
        self.session.flush()

    def save_rejection(self, value: InvoiceDelivery) -> None:
        row, attempt_row = self._active_rows(value)
        attempt = value.attempts[-1]
        if (
            value.state is not InvoiceDeliveryState.FAILED
            or attempt.outcome is not InvoiceDeliveryAttemptOutcome.REJECTED
        ):
            raise InvalidInvoiceDeliveryTransitionError(
                "Delivery rejection transition is inconsistent"
            )
        attempt_row.completed_at = attempt.completed_at
        attempt_row.outcome = attempt.outcome.value
        attempt_row.failure_reason = attempt.failure_reason
        row.state = value.state.value
        row.active_attempt_id = None
        self.session.flush()

    def save_ambiguous(self, value: InvoiceDelivery) -> None:
        row, attempt_row = self._active_rows(value)
        attempt = value.attempts[-1]
        if (
            value.state is not InvoiceDeliveryState.IN_PROGRESS
            or attempt.outcome is not InvoiceDeliveryAttemptOutcome.AMBIGUOUS
            or value.active_attempt_id != attempt.id
        ):
            raise InvalidInvoiceDeliveryTransitionError(
                "Ambiguous delivery transition is inconsistent"
            )
        attempt_row.completed_at = attempt.completed_at
        attempt_row.outcome = attempt.outcome.value
        attempt_row.failure_reason = attempt.failure_reason
        self.session.flush()

    def save_sent(self, value: InvoiceDelivery) -> None:
        row, attempt_row = self._active_rows(value)
        attempt = value.attempts[-1]
        if (
            value.state is not InvoiceDeliveryState.SENT
            or attempt.outcome is not InvoiceDeliveryAttemptOutcome.SENT
            or value.sent_at != attempt.completed_at
        ):
            raise InvalidInvoiceDeliveryTransitionError(
                "Delivery success transition is inconsistent"
            )
        attempt_row.completed_at = attempt.completed_at
        attempt_row.outcome = attempt.outcome.value
        attempt_row.provider_message_id = attempt.provider_message_id
        row.state = value.state.value
        row.active_attempt_id = None
        row.sent_at = value.sent_at
        self.session.flush()

    def _owned_row(self, delivery_id: UUID) -> InvoiceDeliveryRow:
        row = self.session.get(InvoiceDeliveryRow, delivery_id)
        if row is None or row.workspace_id != self.workspace_id:
            raise InvalidInvoiceDeliveryTransitionError("Persisted delivery claim is unavailable")
        return row

    def _active_rows(
        self, value: InvoiceDelivery
    ) -> tuple[InvoiceDeliveryRow, InvoiceDeliveryAttemptRow]:
        row = self._owned_row(value.id)
        previous_attempt_id = row.active_attempt_id
        if (
            row.state != InvoiceDeliveryState.IN_PROGRESS.value
            or previous_attempt_id is None
            or not value.attempts
            or value.attempts[-1].id != previous_attempt_id
            or len(value.attempts) != row.attempt_count
        ):
            raise InvalidInvoiceDeliveryTransitionError(
                "Persisted delivery claim is stale or invalid"
            )
        attempt_row = self.session.get(InvoiceDeliveryAttemptRow, previous_attempt_id)
        if (
            attempt_row is None
            or attempt_row.delivery_id != value.id
            or attempt_row.outcome is not None
        ):
            raise InvalidInvoiceDeliveryTransitionError(
                "Persisted delivery attempt is stale or invalid"
            )
        return row, attempt_row

    def _delivery(self, row: InvoiceDeliveryRow) -> InvoiceDelivery:
        attempts = tuple(
            _attempt(attempt)
            for attempt in self.session.scalars(
                select(InvoiceDeliveryAttemptRow)
                .where(InvoiceDeliveryAttemptRow.delivery_id == row.id)
                .order_by(InvoiceDeliveryAttemptRow.sequence)
            )
        )
        if len(attempts) != row.attempt_count:
            raise ValueError("Persisted delivery attempt count is inconsistent")
        return InvoiceDelivery(
            id=row.id,
            workspace_id=row.workspace_id,
            approval_id=row.approval_id,
            invoice_id=row.invoice_draft_id,
            invoice_revision=row.invoice_revision,
            artifact_id=row.artifact_id,
            artifact_sha256=row.artifact_sha256,
            state=InvoiceDeliveryState(row.state),
            requested_at=row.requested_at,
            active_attempt_id=row.active_attempt_id,
            sent_at=row.sent_at,
            attempts=attempts,
            message=_message(row),
        )
