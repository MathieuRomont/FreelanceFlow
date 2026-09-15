"""PostgreSQL persistence for immutable provider events and correlations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from freelanceflow.modules.delivery.adapters.models import (
    InvoiceDeliveryAttemptRow,
    InvoiceDeliveryProviderEventMatchRow,
    InvoiceDeliveryProviderEventRow,
    InvoiceDeliveryRow,
)
from freelanceflow.modules.delivery.adapters.provider_message_lock import (
    lock_provider_message_id,
)
from freelanceflow.modules.delivery.application.provider_events import (
    ProviderEventIdentityConflict,
    ProviderMessageDeliveryTarget,
)
from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    InvoiceDeliveryAttemptOutcome,
)
from freelanceflow.modules.delivery.domain.provider_events import (
    InvoiceDeliveryProviderEvent,
    InvoiceDeliveryProviderEventKind,
    InvoiceDeliveryProviderEventMatch,
    InvoiceDeliveryProviderEventRecord,
)


def _event(row: InvoiceDeliveryProviderEventRow) -> InvoiceDeliveryProviderEvent:
    return InvoiceDeliveryProviderEvent(
        id=row.id,
        provider_event_id=row.provider_event_id,
        provider_message_id=row.provider_message_id,
        raw_event_type=row.raw_event_type,
        kind=InvoiceDeliveryProviderEventKind(row.event_kind),
        occurred_at=row.occurred_at,
        received_at=row.received_at,
        payload_sha256=row.payload_sha256,
    )


def _match(
    row: InvoiceDeliveryProviderEventMatchRow,
) -> InvoiceDeliveryProviderEventMatch:
    return InvoiceDeliveryProviderEventMatch(
        event_id=row.event_id,
        delivery_id=row.delivery_id,
        workspace_id=row.workspace_id,
        provider_message_id=row.provider_message_id,
        correlated_at=row.correlated_at,
    )


def _same_immutable_event(
    left: InvoiceDeliveryProviderEvent, right: InvoiceDeliveryProviderEvent
) -> bool:
    return (
        left.provider_event_id == right.provider_event_id
        and left.provider_message_id == right.provider_message_id
        and left.raw_event_type == right.raw_event_type
        and left.kind is right.kind
        and left.occurred_at == right.occurred_at
        and left.payload_sha256 == right.payload_sha256
    )


class InvoiceDeliveryProviderEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_provider_message_id(self, provider_message_id: str) -> None:
        lock_provider_message_id(self.session, provider_message_id)

    def add_or_get(
        self, value: InvoiceDeliveryProviderEvent
    ) -> InvoiceDeliveryProviderEvent:
        inserted_id = self.session.scalar(
            insert(InvoiceDeliveryProviderEventRow)
            .values(
                id=value.id,
                provider_event_id=value.provider_event_id,
                provider_message_id=value.provider_message_id,
                raw_event_type=value.raw_event_type,
                event_kind=value.kind.value,
                occurred_at=value.occurred_at,
                received_at=value.received_at,
                payload_sha256=value.payload_sha256,
            )
            .on_conflict_do_nothing(
                index_elements=[InvoiceDeliveryProviderEventRow.provider_event_id]
            )
            .returning(InvoiceDeliveryProviderEventRow.id)
        )
        if inserted_id is not None:
            return value
        row = self.session.scalar(
            select(InvoiceDeliveryProviderEventRow).where(
                InvoiceDeliveryProviderEventRow.provider_event_id
                == value.provider_event_id
            )
        )
        if row is None:
            raise RuntimeError("Provider event conflict did not return its record")
        existing = _event(row)
        if not _same_immutable_event(existing, value):
            raise ProviderEventIdentityConflict(
                "Provider event identity was reused for different content"
            )
        return existing

    def get_match(
        self, event_id: UUID
    ) -> InvoiceDeliveryProviderEventMatch | None:
        row = self.session.get(InvoiceDeliveryProviderEventMatchRow, event_id)
        return _match(row) if row is not None else None

    def find_delivery_target(
        self, provider_message_id: str
    ) -> ProviderMessageDeliveryTarget | None:
        row = self.session.execute(
            select(
                InvoiceDeliveryAttemptRow.delivery_id,
                InvoiceDeliveryAttemptRow.workspace_id,
            ).where(
                InvoiceDeliveryAttemptRow.provider_message_id
                == provider_message_id,
                InvoiceDeliveryAttemptRow.outcome
                == InvoiceDeliveryAttemptOutcome.SENT.value,
            )
        ).one_or_none()
        if row is None:
            return None
        return ProviderMessageDeliveryTarget(
            delivery_id=row.delivery_id,
            workspace_id=row.workspace_id,
        )

    def add_match(self, value: InvoiceDeliveryProviderEventMatch) -> None:
        self.session.add(
            InvoiceDeliveryProviderEventMatchRow(
                event_id=value.event_id,
                delivery_id=value.delivery_id,
                workspace_id=value.workspace_id,
                provider_message_id=value.provider_message_id,
                correlated_at=value.correlated_at,
            )
        )
        self.session.flush()

    def delivery_exists(self, workspace_id: UUID, delivery_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(InvoiceDeliveryRow.id).where(
                    InvoiceDeliveryRow.id == delivery_id,
                    InvoiceDeliveryRow.workspace_id == workspace_id,
                )
            )
            is not None
        )

    def list_for_delivery(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> tuple[InvoiceDeliveryProviderEventRecord, ...]:
        rows = self.session.execute(
            select(
                InvoiceDeliveryProviderEventRow,
                InvoiceDeliveryProviderEventMatchRow,
            )
            .join(
                InvoiceDeliveryProviderEventMatchRow,
                InvoiceDeliveryProviderEventMatchRow.event_id
                == InvoiceDeliveryProviderEventRow.id,
            )
            .where(
                InvoiceDeliveryProviderEventMatchRow.delivery_id == delivery_id,
                InvoiceDeliveryProviderEventMatchRow.workspace_id == workspace_id,
            )
            .order_by(
                InvoiceDeliveryProviderEventRow.occurred_at,
                InvoiceDeliveryProviderEventRow.provider_event_id,
                InvoiceDeliveryProviderEventRow.id,
            )
        )
        return tuple(
            InvoiceDeliveryProviderEventRecord(
                event=_event(event_row), match=_match(match_row)
            )
            for event_row, match_row in rows
        )


def reconcile_provider_events(
    session: Session,
    *,
    delivery_id: UUID,
    workspace_id: UUID,
    provider_message_id: str,
    correlated_at: datetime,
) -> None:
    unmatched_events = tuple(
        session.scalars(
            select(InvoiceDeliveryProviderEventRow)
            .outerjoin(
                InvoiceDeliveryProviderEventMatchRow,
                InvoiceDeliveryProviderEventMatchRow.event_id
                == InvoiceDeliveryProviderEventRow.id,
            )
            .where(
                InvoiceDeliveryProviderEventRow.provider_message_id
                == provider_message_id,
                InvoiceDeliveryProviderEventMatchRow.event_id.is_(None),
            )
            .order_by(
                InvoiceDeliveryProviderEventRow.occurred_at,
                InvoiceDeliveryProviderEventRow.provider_event_id,
            )
        )
    )
    session.add_all(
        InvoiceDeliveryProviderEventMatchRow(
            event_id=event.id,
            delivery_id=delivery_id,
            workspace_id=workspace_id,
            provider_message_id=provider_message_id,
            correlated_at=correlated_at,
        )
        for event in unmatched_events
    )
    session.flush()
