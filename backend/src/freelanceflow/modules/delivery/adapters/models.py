"""SQLAlchemy models for durable invoice deliveries."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class InvoiceDeliveryRow(Base):
    __tablename__ = "invoice_deliveries"
    __table_args__ = (
        UniqueConstraint("approval_id", name="uq_invoice_deliveries_approval_id"),
        UniqueConstraint("id", "workspace_id", name="uq_invoice_deliveries_workspace"),
        ForeignKeyConstraint(
            [
                "approval_id",
                "workspace_id",
                "invoice_draft_id",
                "invoice_revision",
                "artifact_id",
                "artifact_sha256",
            ],
            [
                "invoice_approvals.id",
                "invoice_approvals.workspace_id",
                "invoice_approvals.invoice_draft_id",
                "invoice_approvals.invoice_revision",
                "invoice_approvals.artifact_id",
                "invoice_approvals.artifact_sha256",
            ],
        ),
        ForeignKeyConstraint(
            ["id", "active_attempt_id"],
            ["invoice_delivery_attempts.delivery_id", "invoice_delivery_attempts.id"],
            name="fk_invoice_deliveries_active_attempt",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("invoice_revision > 0", name="positive_invoice_revision"),
        CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="canonical_artifact_sha256",
        ),
        CheckConstraint(
            "state IN ('pending', 'in_progress', 'sent', 'failed')",
            name="valid_state",
        ),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        CheckConstraint(
            "(state = 'pending' AND active_attempt_id IS NULL AND sent_at IS NULL) OR "
            "(state = 'in_progress' AND active_attempt_id IS NOT NULL "
            "AND sent_at IS NULL AND attempt_count > 0) OR "
            "(state = 'sent' AND active_attempt_id IS NULL "
            "AND sent_at IS NOT NULL AND attempt_count > 0) OR "
            "(state = 'failed' AND active_attempt_id IS NULL "
            "AND sent_at IS NULL AND attempt_count > 0)",
            name="consistent_state_metadata",
        ),
        CheckConstraint(
            "(sender IS NULL AND recipient IS NULL AND subject IS NULL "
            "AND body IS NULL AND attachment_filename IS NULL) OR "
            "(sender IS NOT NULL AND length(btrim(sender)) > 0 "
            "AND recipient IS NOT NULL AND length(btrim(recipient)) > 0 "
            "AND subject IS NOT NULL AND body IS NOT NULL "
            "AND attachment_filename IS NOT NULL "
            "AND length(btrim(attachment_filename)) > 0)",
            name="complete_message_snapshot",
        ),
        CheckConstraint(
            "sent_at IS NULL OR sent_at >= requested_at",
            name="sent_after_request",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    approval_id: Mapped[UUID]
    invoice_draft_id: Mapped[UUID]
    invoice_revision: Mapped[int] = mapped_column(Integer)
    artifact_id: Mapped[UUID]
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str]
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active_attempt_id: Mapped[UUID | None]
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer)
    sender: Mapped[str | None]
    recipient: Mapped[str | None]
    subject: Mapped[str | None]
    body: Mapped[str | None]
    attachment_filename: Mapped[str | None]


class InvoiceDeliveryAttemptRow(Base):
    __tablename__ = "invoice_delivery_attempts"
    __table_args__ = (
        UniqueConstraint(
            "delivery_id", "id", name="uq_invoice_delivery_attempts_delivery_id_id"
        ),
        UniqueConstraint(
            "delivery_id",
            "sequence",
            name="uq_invoice_delivery_attempts_delivery_sequence",
        ),
        UniqueConstraint(
            "provider_message_id",
            name="uq_invoice_delivery_attempts_provider_message_id",
        ),
        UniqueConstraint(
            "delivery_id",
            "provider_message_id",
            name="uq_invoice_delivery_attempts_delivery_provider_message",
        ),
        ForeignKeyConstraint(
            ["delivery_id", "workspace_id"],
            ["invoice_deliveries.id", "invoice_deliveries.workspace_id"],
        ),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('failed', 'rejected', 'ambiguous', 'sent')",
            name="valid_outcome",
        ),
        CheckConstraint(
            "(outcome IS NULL AND completed_at IS NULL AND failure_reason IS NULL "
            "AND provider_message_id IS NULL) OR "
            "(outcome = 'sent' AND completed_at IS NOT NULL "
            "AND failure_reason IS NULL AND (provider_message_id IS NULL "
            "OR length(btrim(provider_message_id)) > 0)) OR "
            "(outcome IN ('failed', 'rejected', 'ambiguous') "
            "AND completed_at IS NOT NULL AND failure_reason IS NOT NULL "
            "AND length(btrim(failure_reason)) > 0 "
            "AND provider_message_id IS NULL)",
            name="consistent_outcome_metadata",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="completion_after_start",
        ),
        Index(
            "uq_invoice_delivery_attempts_open_delivery",
            "delivery_id",
            unique=True,
            postgresql_where=text("outcome IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    delivery_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None]
    failure_reason: Mapped[str | None]
    provider_message_id: Mapped[str | None]


class InvoiceDeliveryProviderEventRow(Base):
    __tablename__ = "invoice_delivery_provider_events"
    __table_args__ = (
        UniqueConstraint(
            "provider_event_id",
            name="uq_invoice_delivery_provider_events_provider_event_id",
        ),
        UniqueConstraint(
            "id",
            "provider_message_id",
            name="uq_invoice_delivery_provider_events_id_provider_message",
        ),
        CheckConstraint(
            "length(btrim(provider_event_id)) > 0",
            name="nonblank_provider_event_id",
        ),
        CheckConstraint(
            "provider_message_id IS NULL OR "
            "length(btrim(provider_message_id)) > 0",
            name="nonblank_provider_message_id",
        ),
        CheckConstraint(
            "length(btrim(raw_event_type)) > 0",
            name="nonblank_raw_event_type",
        ),
        CheckConstraint(
            "event_kind IN ('provider_accepted', 'recipient_delivered', "
            "'delivery_delayed', 'bounced', 'provider_failed', "
            "'complained', 'unsupported')",
            name="valid_event_kind",
        ),
        CheckConstraint(
            "event_kind = 'unsupported' OR provider_message_id IS NOT NULL",
            name="supported_event_has_provider_message",
        ),
        CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="canonical_payload_sha256",
        ),
        Index(
            "ix_invoice_delivery_provider_events_provider_message_id",
            "provider_message_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    provider_event_id: Mapped[str]
    provider_message_id: Mapped[str | None]
    raw_event_type: Mapped[str]
    event_kind: Mapped[str]
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_sha256: Mapped[str] = mapped_column(String(64))


class InvoiceDeliveryProviderEventMatchRow(Base):
    __tablename__ = "invoice_delivery_provider_event_matches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "provider_message_id"],
            [
                "invoice_delivery_provider_events.id",
                "invoice_delivery_provider_events.provider_message_id",
            ],
        ),
        ForeignKeyConstraint(
            ["delivery_id", "provider_message_id"],
            [
                "invoice_delivery_attempts.delivery_id",
                "invoice_delivery_attempts.provider_message_id",
            ],
        ),
        ForeignKeyConstraint(
            ["delivery_id", "workspace_id"],
            ["invoice_deliveries.id", "invoice_deliveries.workspace_id"],
        ),
        CheckConstraint(
            "length(btrim(provider_message_id)) > 0",
            name="nonblank_provider_message_id",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    delivery_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    provider_message_id: Mapped[str]
    correlated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
