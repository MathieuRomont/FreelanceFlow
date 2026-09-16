from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class RateAgreementRow(Base):
    __tablename__ = "rate_agreements"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "client_id"], ["clients.workspace_id", "clients.id"]),
        ForeignKeyConstraint(
            ["workspace_id", "client_id", "project_id"],
            ["projects.workspace_id", "projects.client_id", "projects.id"],
        ),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="validity"),
        CheckConstraint(
            "hourly_amount NOT IN ('NaN', 'Infinity', '-Infinity')", name="finite_rate"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    client_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    hourly_amount: Mapped[Decimal] = mapped_column(Numeric())
    currency: Mapped[str]
    valid_from: Mapped[date]
    valid_until: Mapped[date | None]


class InvoiceDraftRow(Base):
    __tablename__ = "invoice_drafts"
    __table_args__ = (
        PrimaryKeyConstraint("id", "revision"),
        ForeignKeyConstraint(
            [
                "id",
                "workspace_id",
                "client_id",
                "currency",
                "currency_decimal_places",
            ],
            [
                "invoice_draft_heads.id",
                "invoice_draft_heads.workspace_id",
                "invoice_draft_heads.client_id",
                "invoice_draft_heads.currency",
                "invoice_draft_heads.currency_decimal_places",
            ],
        ),
        UniqueConstraint(
            "id",
            "revision",
            "workspace_id",
            "client_id",
            "currency",
            "currency_decimal_places",
        ),
        UniqueConstraint(
            "id",
            "revision",
            "workspace_id",
            name="uq_invoice_drafts_exact_revision_workspace",
        ),
        CheckConstraint("revision > 0", name="positive_revision"),
        CheckConstraint(
            "currency = 'EUR' AND currency_decimal_places = 2",
            name="supported_currency_precision",
        ),
        CheckConstraint(
            "exact_subtotal_numerator = trunc(exact_subtotal_numerator) "
            "AND exact_subtotal_numerator >= 0",
            name="integral_exact_subtotal_numerator",
        ),
        CheckConstraint(
            "exact_subtotal_denominator = trunc(exact_subtotal_denominator) "
            "AND exact_subtotal_denominator > 0",
            name="valid_exact_subtotal_denominator",
        ),
        CheckConstraint(
            "subtotal_minor_units = trunc(subtotal_minor_units) "
            "AND total_minor_units = trunc(total_minor_units) "
            "AND subtotal_minor_units >= 0 AND total_minor_units >= 0 "
            "AND subtotal_minor_units = total_minor_units",
            name="reconciled_integral_totals",
        ),
    )

    id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    workspace_id: Mapped[UUID]
    client_id: Mapped[UUID]
    currency: Mapped[str]
    currency_decimal_places: Mapped[int] = mapped_column(Integer)
    exact_subtotal_numerator: Mapped[Decimal] = mapped_column(Numeric())
    exact_subtotal_denominator: Mapped[Decimal] = mapped_column(Numeric())
    subtotal_minor_units: Mapped[Decimal] = mapped_column(Numeric())
    total_minor_units: Mapped[Decimal] = mapped_column(Numeric())


class InvoiceDraftHeadRow(Base):
    __tablename__ = "invoice_draft_heads"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "workspace_id",
            "client_id",
            "currency",
            "currency_decimal_places",
        ),
        CheckConstraint("current_revision > 0", name="positive_current_revision"),
        CheckConstraint(
            "currency = 'EUR' AND currency_decimal_places = 2",
            name="supported_currency_precision",
        ),
        CheckConstraint(
            "(issued_invoice_id IS NULL AND issued_revision IS NULL) OR "
            "(issued_invoice_id IS NOT NULL AND issued_revision = current_revision)",
            name="consistent_issuance_freeze",
        ),
        ForeignKeyConstraint(
            ["issued_invoice_id", "id", "issued_revision", "workspace_id"],
            [
                "issued_invoices.id",
                "issued_invoices.source_invoice_id",
                "issued_invoices.source_revision",
                "issued_invoices.workspace_id",
            ],
            name="fk_invoice_draft_heads_issued_invoice_id_issued_invoices",
            use_alter=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    client_id: Mapped[UUID]
    currency: Mapped[str]
    currency_decimal_places: Mapped[int] = mapped_column(Integer)
    current_revision: Mapped[int] = mapped_column(Integer)
    issued_invoice_id: Mapped[UUID | None]
    issued_revision: Mapped[int | None] = mapped_column(Integer)


class InvoiceLineRow(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        PrimaryKeyConstraint("invoice_draft_id", "invoice_revision", "id"),
        ForeignKeyConstraint(
            [
                "invoice_draft_id",
                "invoice_revision",
                "workspace_id",
                "client_id",
                "currency",
                "currency_decimal_places",
            ],
            [
                "invoice_drafts.id",
                "invoice_drafts.revision",
                "invoice_drafts.workspace_id",
                "invoice_drafts.client_id",
                "invoice_drafts.currency",
                "invoice_drafts.currency_decimal_places",
            ],
        ),
        UniqueConstraint("invoice_draft_id", "invoice_revision", "position"),
        CheckConstraint("position >= 0", name="nonnegative_position"),
        CheckConstraint("duration_microseconds > 0", name="positive_duration"),
        CheckConstraint(
            "(task_id IS NULL) = (task_name IS NULL)", name="complete_task_snapshot"
        ),
        CheckConstraint(
            "rate_scope_project_id IS NULL OR rate_scope_project_id = project_id",
            name="compatible_rate_scope",
        ),
        CheckConstraint(
            "rate_valid_until IS NULL OR rate_valid_until > rate_valid_from",
            name="rate_validity",
        ),
        CheckConstraint(
            "exact_amount_numerator = trunc(exact_amount_numerator) "
            "AND exact_amount_numerator >= 0",
            name="integral_exact_amount_numerator",
        ),
        CheckConstraint(
            "exact_amount_denominator = trunc(exact_amount_denominator) "
            "AND exact_amount_denominator > 0",
            name="valid_exact_amount_denominator",
        ),
        CheckConstraint(
            "rounded_minor_units = trunc(rounded_minor_units) "
            "AND rounded_minor_units >= 0",
            name="integral_rounded_amount",
        ),
    )

    invoice_draft_id: Mapped[UUID]
    invoice_revision: Mapped[int] = mapped_column(Integer)
    id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    workspace_id: Mapped[UUID]
    client_id: Mapped[UUID]
    client_name: Mapped[str]
    project_id: Mapped[UUID]
    project_name: Mapped[str]
    task_id: Mapped[UUID | None]
    task_name: Mapped[str | None]
    rate_agreement_id: Mapped[UUID]
    rate_scope_project_id: Mapped[UUID | None]
    rate_valid_from: Mapped[date]
    rate_valid_until: Mapped[date | None]
    hourly_amount: Mapped[Decimal] = mapped_column(Numeric())
    currency: Mapped[str]
    currency_decimal_places: Mapped[int] = mapped_column(Integer)
    duration_microseconds: Mapped[int] = mapped_column(BigInteger)
    exact_amount_numerator: Mapped[Decimal] = mapped_column(Numeric())
    exact_amount_denominator: Mapped[Decimal] = mapped_column(Numeric())
    rounded_minor_units: Mapped[Decimal] = mapped_column(Numeric())


class InvoiceAllocationRow(Base):
    __tablename__ = "invoice_allocations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "invoice_draft_id", "invoice_revision", "invoice_line_id", "position"
        ),
        ForeignKeyConstraint(
            ["invoice_draft_id", "invoice_revision", "invoice_line_id"],
            [
                "invoice_lines.invoice_draft_id",
                "invoice_lines.invoice_revision",
                "invoice_lines.id",
            ],
        ),
        CheckConstraint("position >= 0", name="nonnegative_position"),
        CheckConstraint("source_end > source_start", name="positive_source_interval"),
        CheckConstraint("segment_end > segment_start", name="positive_segment_interval"),
        CheckConstraint(
            "segment_start >= source_start AND segment_end <= source_end",
            name="contained_segment",
        ),
        CheckConstraint("duration_microseconds > 0", name="positive_duration"),
        CheckConstraint("source_billable", name="billable_source"),
        CheckConstraint(
            "exact_amount_numerator = trunc(exact_amount_numerator) "
            "AND exact_amount_numerator >= 0",
            name="integral_exact_amount_numerator",
        ),
        CheckConstraint(
            "exact_amount_denominator = trunc(exact_amount_denominator) "
            "AND exact_amount_denominator > 0",
            name="valid_exact_amount_denominator",
        ),
    )

    invoice_draft_id: Mapped[UUID]
    invoice_revision: Mapped[int] = mapped_column(Integer)
    invoice_line_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    source_time_entry_id: Mapped[UUID]
    source_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_start_zone: Mapped[str | None]
    source_end_zone: Mapped[str | None]
    source_start_offset_microseconds: Mapped[int] = mapped_column(BigInteger)
    source_end_offset_microseconds: Mapped[int] = mapped_column(BigInteger)
    source_billable: Mapped[bool]
    segment_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    segment_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    segment_start_zone: Mapped[str | None]
    segment_end_zone: Mapped[str | None]
    segment_start_offset_microseconds: Mapped[int] = mapped_column(BigInteger)
    segment_end_offset_microseconds: Mapped[int] = mapped_column(BigInteger)
    business_date: Mapped[date]
    duration_microseconds: Mapped[int] = mapped_column(BigInteger)
    exact_amount_numerator: Mapped[Decimal] = mapped_column(Numeric())
    exact_amount_denominator: Mapped[Decimal] = mapped_column(Numeric())


class InvoiceArtifactRow(Base):
    __tablename__ = "invoice_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "workspace_id",
            "invoice_draft_id",
            "invoice_revision",
            "sha256",
            name="uq_invoice_artifacts_approval_target",
        ),
        ForeignKeyConstraint(
            ["invoice_draft_id", "invoice_revision", "workspace_id"],
            [
                "invoice_drafts.id",
                "invoice_drafts.revision",
                "invoice_drafts.workspace_id",
            ],
        ),
        CheckConstraint("invoice_revision > 0", name="positive_invoice_revision"),
        CheckConstraint(
            "length(btrim(media_type, U&'"
            r"\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020"
            r"\0085\00A0\1680\2000\2001\2002\2003\2004\2005"
            r"\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000"
            "')) > 0",
            name="nonblank_media_type",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="canonical_sha256"),
        CheckConstraint(
            "byte_size > 0 AND octet_length(content) = byte_size",
            name="consistent_nonempty_content_size",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    invoice_draft_id: Mapped[UUID]
    invoice_revision: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str]
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvoiceApprovalRow(Base):
    __tablename__ = "invoice_approvals"
    __table_args__ = (
        UniqueConstraint(
            "invoice_draft_id",
            "invoice_revision",
            name="uq_invoice_approvals_exact_revision",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            "invoice_draft_id",
            "invoice_revision",
            "artifact_id",
            "artifact_sha256",
            name="uq_invoice_approvals_delivery_target",
        ),
        ForeignKeyConstraint(
            ["invoice_draft_id", "invoice_revision", "workspace_id"],
            [
                "invoice_drafts.id",
                "invoice_drafts.revision",
                "invoice_drafts.workspace_id",
            ],
        ),
        ForeignKeyConstraint(
            [
                "artifact_id",
                "workspace_id",
                "invoice_draft_id",
                "invoice_revision",
                "artifact_sha256",
            ],
            [
                "invoice_artifacts.id",
                "invoice_artifacts.workspace_id",
                "invoice_artifacts.invoice_draft_id",
                "invoice_artifacts.invoice_revision",
                "invoice_artifacts.sha256",
            ],
        ),
        CheckConstraint("invoice_revision > 0", name="positive_invoice_revision"),
        CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="canonical_artifact_sha256",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    invoice_draft_id: Mapped[UUID]
    invoice_revision: Mapped[int] = mapped_column(Integer)
    artifact_id: Mapped[UUID]
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
