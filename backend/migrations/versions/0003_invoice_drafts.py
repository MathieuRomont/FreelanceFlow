"""Persist immutable, auditable InvoiceDraft revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("currency_decimal_places", sa.Integer(), nullable=False),
        sa.Column("exact_subtotal_numerator", sa.Numeric(), nullable=False),
        sa.Column("exact_subtotal_denominator", sa.Numeric(), nullable=False),
        sa.Column("subtotal_minor_units", sa.Numeric(), nullable=False),
        sa.Column("total_minor_units", sa.Numeric(), nullable=False),
        sa.CheckConstraint(
            "exact_subtotal_denominator = trunc(exact_subtotal_denominator) "
            "AND exact_subtotal_denominator > 0",
            name=op.f("ck_invoice_drafts_valid_exact_subtotal_denominator"),
        ),
        sa.CheckConstraint(
            "exact_subtotal_numerator = trunc(exact_subtotal_numerator) "
            "AND exact_subtotal_numerator >= 0",
            name=op.f("ck_invoice_drafts_integral_exact_subtotal_numerator"),
        ),
        sa.CheckConstraint(
            "revision > 0", name=op.f("ck_invoice_drafts_positive_revision")
        ),
        sa.CheckConstraint(
            "subtotal_minor_units = trunc(subtotal_minor_units) "
            "AND total_minor_units = trunc(total_minor_units) "
            "AND subtotal_minor_units >= 0 AND total_minor_units >= 0 "
            "AND subtotal_minor_units = total_minor_units",
            name=op.f("ck_invoice_drafts_reconciled_integral_totals"),
        ),
        sa.CheckConstraint(
            "currency = 'EUR' AND currency_decimal_places = 2",
            name=op.f("ck_invoice_drafts_supported_currency_precision"),
        ),
        sa.PrimaryKeyConstraint("id", "revision", name=op.f("pk_invoice_drafts")),
        sa.UniqueConstraint(
            "id",
            "revision",
            "workspace_id",
            "client_id",
            "currency",
            "currency_decimal_places",
            name=op.f("uq_invoice_drafts_id"),
        ),
    )
    op.create_table(
        "invoice_lines",
        sa.Column("invoice_draft_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_revision", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("project_name", sa.String(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("task_name", sa.String(), nullable=True),
        sa.Column("rate_agreement_id", sa.Uuid(), nullable=False),
        sa.Column("rate_scope_project_id", sa.Uuid(), nullable=True),
        sa.Column("rate_valid_from", sa.Date(), nullable=False),
        sa.Column("rate_valid_until", sa.Date(), nullable=True),
        sa.Column("hourly_amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("currency_decimal_places", sa.Integer(), nullable=False),
        sa.Column("duration_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("exact_amount_numerator", sa.Numeric(), nullable=False),
        sa.Column("exact_amount_denominator", sa.Numeric(), nullable=False),
        sa.Column("rounded_minor_units", sa.Numeric(), nullable=False),
        sa.CheckConstraint(
            "rate_scope_project_id IS NULL OR rate_scope_project_id = project_id",
            name=op.f("ck_invoice_lines_compatible_rate_scope"),
        ),
        sa.CheckConstraint(
            "exact_amount_numerator = trunc(exact_amount_numerator) "
            "AND exact_amount_numerator >= 0",
            name=op.f("ck_invoice_lines_integral_exact_amount_numerator"),
        ),
        sa.CheckConstraint(
            "rounded_minor_units = trunc(rounded_minor_units) "
            "AND rounded_minor_units >= 0",
            name=op.f("ck_invoice_lines_integral_rounded_amount"),
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_invoice_lines_nonnegative_position")
        ),
        sa.CheckConstraint(
            "duration_microseconds > 0",
            name=op.f("ck_invoice_lines_positive_duration"),
        ),
        sa.CheckConstraint(
            "rate_valid_until IS NULL OR rate_valid_until > rate_valid_from",
            name=op.f("ck_invoice_lines_rate_validity"),
        ),
        sa.CheckConstraint(
            "(task_id IS NULL) = (task_name IS NULL)",
            name=op.f("ck_invoice_lines_complete_task_snapshot"),
        ),
        sa.CheckConstraint(
            "exact_amount_denominator = trunc(exact_amount_denominator) "
            "AND exact_amount_denominator > 0",
            name=op.f("ck_invoice_lines_valid_exact_amount_denominator"),
        ),
        sa.ForeignKeyConstraint(
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
            name=op.f("fk_invoice_lines_invoice_draft_id_invoice_drafts"),
        ),
        sa.PrimaryKeyConstraint(
            "invoice_draft_id",
            "invoice_revision",
            "id",
            name=op.f("pk_invoice_lines"),
        ),
        sa.UniqueConstraint(
            "invoice_draft_id",
            "invoice_revision",
            "position",
            name=op.f("uq_invoice_lines_invoice_draft_id"),
        ),
    )
    op.create_table(
        "invoice_allocations",
        sa.Column("invoice_draft_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_revision", sa.Integer(), nullable=False),
        sa.Column("invoice_line_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_time_entry_id", sa.Uuid(), nullable=False),
        sa.Column("source_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_start_zone", sa.String(), nullable=True),
        sa.Column("source_end_zone", sa.String(), nullable=True),
        sa.Column("source_start_offset_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("source_end_offset_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("source_billable", sa.Boolean(), nullable=False),
        sa.Column("segment_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("segment_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("segment_start_zone", sa.String(), nullable=True),
        sa.Column("segment_end_zone", sa.String(), nullable=True),
        sa.Column("segment_start_offset_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("segment_end_offset_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("duration_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("exact_amount_numerator", sa.Numeric(), nullable=False),
        sa.Column("exact_amount_denominator", sa.Numeric(), nullable=False),
        sa.CheckConstraint(
            "source_billable", name=op.f("ck_invoice_allocations_billable_source")
        ),
        sa.CheckConstraint(
            "segment_start >= source_start AND segment_end <= source_end",
            name=op.f("ck_invoice_allocations_contained_segment"),
        ),
        sa.CheckConstraint(
            "exact_amount_numerator = trunc(exact_amount_numerator) "
            "AND exact_amount_numerator >= 0",
            name=op.f("ck_invoice_allocations_integral_exact_amount_numerator"),
        ),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_invoice_allocations_nonnegative_position"),
        ),
        sa.CheckConstraint(
            "duration_microseconds > 0",
            name=op.f("ck_invoice_allocations_positive_duration"),
        ),
        sa.CheckConstraint(
            "segment_end > segment_start",
            name=op.f("ck_invoice_allocations_positive_segment_interval"),
        ),
        sa.CheckConstraint(
            "source_end > source_start",
            name=op.f("ck_invoice_allocations_positive_source_interval"),
        ),
        sa.CheckConstraint(
            "exact_amount_denominator = trunc(exact_amount_denominator) "
            "AND exact_amount_denominator > 0",
            name=op.f("ck_invoice_allocations_valid_exact_amount_denominator"),
        ),
        sa.ForeignKeyConstraint(
            ["invoice_draft_id", "invoice_revision", "invoice_line_id"],
            [
                "invoice_lines.invoice_draft_id",
                "invoice_lines.invoice_revision",
                "invoice_lines.id",
            ],
            name=op.f("fk_invoice_allocations_invoice_draft_id_invoice_lines"),
        ),
        sa.PrimaryKeyConstraint(
            "invoice_draft_id",
            "invoice_revision",
            "invoice_line_id",
            "position",
            name=op.f("pk_invoice_allocations"),
        ),
    )


def downgrade() -> None:
    op.drop_table("invoice_allocations")
    op.drop_table("invoice_lines")
    op.drop_table("invoice_drafts")
