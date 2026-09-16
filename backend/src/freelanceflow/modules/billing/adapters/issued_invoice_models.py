"""Normalized immutable persistence rows for legally issued invoices."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class InvoiceNumberCounterRow(Base):
    __tablename__ = "invoice_number_counters"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "series"),
        CheckConstraint("series = 'main'", name="supported_series"),
        CheckConstraint("last_sequence >= 0", name="nonnegative_last_sequence"),
        CheckConstraint(
            "(last_sequence = 0 AND last_issue_date IS NULL) OR "
            "(last_sequence > 0 AND last_issue_date IS NOT NULL)",
            name="consistent_last_issue",
        ),
    )

    workspace_id: Mapped[UUID]
    series: Mapped[str]
    last_sequence: Mapped[int] = mapped_column(BigInteger)
    last_issue_date: Mapped[date | None] = mapped_column(Date)


class IssuedInvoiceRow(Base):
    __tablename__ = "issued_invoices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_invoice_id", "source_revision", "workspace_id"],
            ["invoice_drafts.id", "invoice_drafts.revision", "invoice_drafts.workspace_id"],
        ),
        UniqueConstraint(
            "source_invoice_id",
            name="uq_issued_invoices_one_issuance_per_logical_invoice",
        ),
        UniqueConstraint(
            "workspace_id",
            "invoice_number",
            name="uq_issued_invoices_legal_invoice_number",
        ),
        UniqueConstraint(
            "workspace_id",
            "number_series",
            "number_sequence",
            name="uq_issued_invoices_legal_sequence",
        ),
        UniqueConstraint(
            "id", "workspace_id", name="uq_issued_invoices_identity_workspace"
        ),
        UniqueConstraint(
            "id",
            "source_invoice_id",
            "source_revision",
            "workspace_id",
            name="uq_issued_invoices_head_binding",
        ),
        CheckConstraint("source_revision > 0", name="positive_source_revision"),
        CheckConstraint("number_series = 'main'", name="supported_number_series"),
        CheckConstraint("number_sequence > 0", name="positive_number_sequence"),
        CheckConstraint("invoice_number = number_sequence::text", name="canonical_number"),
        CheckConstraint("service_completion_date <= issue_date", name="completed_service"),
        CheckConstraint(
            "purchase_order_number IS NULL OR length(btrim(purchase_order_number)) > 0",
            name="nonblank_purchase_order",
        ),
        CheckConstraint(
            "currency = 'EUR' AND currency_decimal_places = 2",
            name="supported_currency_precision",
        ),
        CheckConstraint(
            "line_rounding_policy = 'per_line_half_up' AND "
            "vat_rounding_policy = 'per_rate_subtotal_half_up'",
            name="supported_rounding_policies",
        ),
        CheckConstraint(
            "exact_source_ht_numerator = trunc(exact_source_ht_numerator) "
            "AND exact_source_ht_numerator >= 0",
            name="integral_exact_source_ht_numerator",
        ),
        CheckConstraint(
            "exact_source_ht_denominator = trunc(exact_source_ht_denominator) "
            "AND exact_source_ht_denominator > 0",
            name="valid_exact_source_ht_denominator",
        ),
        CheckConstraint(
            "ht_minor_units = trunc(ht_minor_units) AND ht_minor_units >= 0 "
            "AND vat_minor_units = trunc(vat_minor_units) AND vat_minor_units >= 0 "
            "AND ttc_minor_units = trunc(ttc_minor_units) "
            "AND ttc_minor_units = ht_minor_units + vat_minor_units",
            name="reconciled_integral_totals",
        ),
        CheckConstraint(
            "vat_regime IN ('franchise_en_base', 'taxable')",
            name="valid_vat_regime",
        ),
        CheckConstraint("operation_category = 'services'", name="services_only"),
        CheckConstraint(
            "payment_due_rule IN ('due_on_issue', 'net_days_after_issue', "
            "'invoice_month_end_plus_45_days', 'end_of_month_after_45_days')",
            name="valid_payment_due_rule",
        ),
        CheckConstraint(
            "length(btrim(early_discount_mention)) > 0",
            name="nonblank_early_discount_mention",
        ),
        CheckConstraint(
            "recovery_indemnity_policy = 'french_b2b_40_eur' "
            "AND recovery_indemnity_currency = 'EUR' "
            "AND recovery_indemnity_minor_units = 4000",
            name="french_recovery_indemnity",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    source_invoice_id: Mapped[UUID]
    source_revision: Mapped[int] = mapped_column(Integer)
    number_series: Mapped[str]
    number_sequence: Mapped[int] = mapped_column(BigInteger)
    invoice_number: Mapped[str]
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    billing_timezone: Mapped[str]
    issue_date: Mapped[date] = mapped_column(Date)
    service_completion_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    purchase_order_number: Mapped[str | None]
    currency: Mapped[str]
    currency_decimal_places: Mapped[int] = mapped_column(Integer)
    line_rounding_policy: Mapped[str]
    vat_rounding_policy: Mapped[str]
    exact_source_ht_numerator: Mapped[Decimal] = mapped_column(Numeric())
    exact_source_ht_denominator: Mapped[Decimal] = mapped_column(Numeric())
    ht_minor_units: Mapped[Decimal] = mapped_column(Numeric())
    vat_minor_units: Mapped[Decimal] = mapped_column(Numeric())
    ttc_minor_units: Mapped[Decimal] = mapped_column(Numeric())
    vat_regime: Mapped[str]
    franchise_legal_basis: Mapped[str | None]
    franchise_invoice_mention: Mapped[str | None]
    default_vat_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric())
    vat_on_debits: Mapped[bool]
    operation_category: Mapped[str]
    payment_due_rule: Mapped[str]
    payment_net_days: Mapped[int | None] = mapped_column(Integer)
    early_discount_kind: Mapped[str]
    early_discount_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric())
    early_discount_days_after_issue: Mapped[int | None] = mapped_column(Integer)
    early_discount_mention: Mapped[str]
    late_payment_penalty_annual_rate_percent: Mapped[Decimal] = mapped_column(Numeric())
    late_payment_minimum_annual_rate_percent: Mapped[Decimal] = mapped_column(Numeric())
    late_payment_legal_policy: Mapped[str]
    recovery_indemnity_policy: Mapped[str]
    recovery_indemnity_currency: Mapped[str]
    recovery_indemnity_minor_units: Mapped[int] = mapped_column(BigInteger)


class IssuedInvoiceSellerRow(Base):
    __tablename__ = "issued_invoice_sellers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
        ),
        CheckConstraint("legal_entity_kind IN ('individual', 'company')", name="entity_kind"),
        CheckConstraint("legal_country_code = 'FR'", name="french_legal_address"),
    )

    issued_invoice_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    legal_entity_kind: Mapped[str]
    legal_name: Mapped[str]
    trading_name: Mapped[str | None]
    siren: Mapped[str]
    siret: Mapped[str]
    vat_number: Mapped[str | None]
    legal_form: Mapped[str | None]
    share_capital: Mapped[Decimal | None] = mapped_column(Numeric())
    share_capital_currency: Mapped[str | None]
    legal_line1: Mapped[str]
    legal_line2: Mapped[str | None]
    legal_postal_code: Mapped[str | None]
    legal_city: Mapped[str]
    legal_country_code: Mapped[str]
    billing_line1: Mapped[str | None]
    billing_line2: Mapped[str | None]
    billing_postal_code: Mapped[str | None]
    billing_city: Mapped[str | None]
    billing_country_code: Mapped[str | None]


class IssuedInvoiceClientRow(Base):
    __tablename__ = "issued_invoice_clients"
    __table_args__ = (
        ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
        ),
        CheckConstraint("legal_country_code = 'FR'", name="french_legal_address"),
        CheckConstraint("siren ~ '^[0-9]{9}$'", name="siren_shape"),
    )

    issued_invoice_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    source_client_id: Mapped[UUID]
    legal_name: Mapped[str]
    trading_name: Mapped[str | None]
    siren: Mapped[str]
    vat_number: Mapped[str | None]
    legal_line1: Mapped[str]
    legal_line2: Mapped[str | None]
    legal_postal_code: Mapped[str | None]
    legal_city: Mapped[str]
    legal_country_code: Mapped[str]
    billing_line1: Mapped[str | None]
    billing_line2: Mapped[str | None]
    billing_postal_code: Mapped[str | None]
    billing_city: Mapped[str | None]
    billing_country_code: Mapped[str | None]


class IssuedInvoiceVatBreakdownRow(Base):
    __tablename__ = "issued_invoice_vat_breakdowns"
    __table_args__ = (
        PrimaryKeyConstraint("issued_invoice_id", "position"),
        ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
        ),
        UniqueConstraint("issued_invoice_id", "position", "workspace_id"),
        CheckConstraint("position >= 0", name="nonnegative_position"),
        CheckConstraint(
            "exact_source_ht_numerator = trunc(exact_source_ht_numerator) "
            "AND exact_source_ht_numerator >= 0 "
            "AND exact_source_ht_denominator = trunc(exact_source_ht_denominator) "
            "AND exact_source_ht_denominator > 0 "
            "AND ht_base_minor_units = trunc(ht_base_minor_units) "
            "AND ht_base_minor_units >= 0 "
            "AND exact_vat_numerator = trunc(exact_vat_numerator) "
            "AND exact_vat_numerator >= 0 "
            "AND exact_vat_denominator = trunc(exact_vat_denominator) "
            "AND exact_vat_denominator > 0 "
            "AND vat_minor_units = trunc(vat_minor_units) "
            "AND vat_minor_units >= 0",
            name="exact_nonnegative_amounts",
        ),
    )

    issued_invoice_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    workspace_id: Mapped[UUID]
    exact_source_ht_numerator: Mapped[Decimal] = mapped_column(Numeric())
    exact_source_ht_denominator: Mapped[Decimal] = mapped_column(Numeric())
    ht_base_minor_units: Mapped[Decimal] = mapped_column(Numeric())
    vat_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric())
    franchise_legal_basis: Mapped[str | None]
    franchise_invoice_mention: Mapped[str | None]
    exact_vat_numerator: Mapped[Decimal] = mapped_column(Numeric())
    exact_vat_denominator: Mapped[Decimal] = mapped_column(Numeric())
    vat_minor_units: Mapped[Decimal] = mapped_column(Numeric())
    rounding_policy: Mapped[str]


class IssuedInvoiceLineRow(Base):
    __tablename__ = "issued_invoice_lines"
    __table_args__ = (
        PrimaryKeyConstraint("issued_invoice_id", "position"),
        ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
        ),
        ForeignKeyConstraint(
            ["issued_invoice_id", "vat_breakdown_position", "workspace_id"],
            [
                "issued_invoice_vat_breakdowns.issued_invoice_id",
                "issued_invoice_vat_breakdowns.position",
                "issued_invoice_vat_breakdowns.workspace_id",
            ],
        ),
        UniqueConstraint(
            "issued_invoice_id",
            "source_invoice_line_id",
            name="uq_issued_invoice_lines_source_line",
        ),
        UniqueConstraint(
            "issued_invoice_id",
            "position",
            "workspace_id",
            name="uq_issued_invoice_lines_issued_invoice_id",
        ),
        CheckConstraint("position >= 0", name="nonnegative_position"),
        CheckConstraint("vat_breakdown_position >= 0", name="nonnegative_vat_position"),
        CheckConstraint("length(btrim(description)) > 0", name="nonblank_description"),
        CheckConstraint("duration_microseconds > 0", name="positive_duration"),
        CheckConstraint(
            "exact_amount_numerator = trunc(exact_amount_numerator) "
            "AND exact_amount_numerator >= 0 "
            "AND exact_amount_denominator = trunc(exact_amount_denominator) "
            "AND exact_amount_denominator > 0",
            name="exact_nonnegative_amount",
        ),
        CheckConstraint(
            "rounded_ht_minor_units = trunc(rounded_ht_minor_units) "
            "AND rounded_ht_minor_units >= 0",
            name="integral_nonnegative_ht",
        ),
        CheckConstraint(
            "hourly_rate NOT IN ('NaN', 'Infinity', '-Infinity') AND hourly_rate >= 0",
            name="finite_nonnegative_hourly_rate",
        ),
    )

    issued_invoice_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    workspace_id: Mapped[UUID]
    vat_breakdown_position: Mapped[int] = mapped_column(Integer)
    source_invoice_line_id: Mapped[UUID]
    description: Mapped[str]
    project_id: Mapped[UUID]
    project_name: Mapped[str]
    task_id: Mapped[UUID | None]
    task_name: Mapped[str | None]
    rate_agreement_id: Mapped[UUID]
    rate_scope_project_id: Mapped[UUID | None]
    rate_valid_from: Mapped[date] = mapped_column(Date)
    rate_valid_until: Mapped[date | None] = mapped_column(Date)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric())
    duration_microseconds: Mapped[int] = mapped_column(BigInteger)
    exact_amount_numerator: Mapped[Decimal] = mapped_column(Numeric())
    exact_amount_denominator: Mapped[Decimal] = mapped_column(Numeric())
    rounded_ht_minor_units: Mapped[Decimal] = mapped_column(Numeric())


class IssuedInvoiceAllocationRow(Base):
    __tablename__ = "issued_invoice_allocations"
    __table_args__ = (
        PrimaryKeyConstraint("issued_invoice_id", "line_position", "position"),
        ForeignKeyConstraint(
            ["issued_invoice_id", "line_position", "workspace_id"],
            [
                "issued_invoice_lines.issued_invoice_id",
                "issued_invoice_lines.position",
                "issued_invoice_lines.workspace_id",
            ],
        ),
        CheckConstraint("line_position >= 0 AND position >= 0", name="nonnegative_positions"),
        CheckConstraint("source_end > source_start", name="positive_source_interval"),
        CheckConstraint("segment_end > segment_start", name="positive_segment_interval"),
        CheckConstraint(
            "segment_start >= source_start AND segment_end <= source_end",
            name="contained_segment",
        ),
        CheckConstraint("source_billable", name="billable_source"),
        CheckConstraint("duration_microseconds > 0", name="positive_duration"),
        CheckConstraint(
            "exact_amount_numerator = trunc(exact_amount_numerator) "
            "AND exact_amount_numerator >= 0 "
            "AND exact_amount_denominator = trunc(exact_amount_denominator) "
            "AND exact_amount_denominator > 0",
            name="exact_nonnegative_amount",
        ),
    )

    issued_invoice_id: Mapped[UUID]
    line_position: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    workspace_id: Mapped[UUID]
    source_time_entry_id: Mapped[UUID]
    source_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_billable: Mapped[bool]
    segment_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    segment_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business_date: Mapped[date] = mapped_column(Date)
    duration_microseconds: Mapped[int] = mapped_column(BigInteger)
    exact_amount_numerator: Mapped[Decimal] = mapped_column(Numeric())
    exact_amount_denominator: Mapped[Decimal] = mapped_column(Numeric())
