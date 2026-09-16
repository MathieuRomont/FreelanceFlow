"""Add immutable issued invoices and rollback-safe legal numbering."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_number_counters",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("series", sa.String(), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_issue_date", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "(last_sequence = 0 AND last_issue_date IS NULL) OR "
            "(last_sequence > 0 AND last_issue_date IS NOT NULL)",
            name=op.f("ck_invoice_number_counters_consistent_last_issue"),
        ),
        sa.CheckConstraint(
            "last_sequence >= 0",
            name=op.f("ck_invoice_number_counters_nonnegative_last_sequence"),
        ),
        sa.CheckConstraint(
            "series = 'main'", name=op.f("ck_invoice_number_counters_supported_series")
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "series", name=op.f("pk_invoice_number_counters")
        ),
    )
    op.create_table(
        "issued_invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("number_series", sa.String(), nullable=False),
        sa.Column("number_sequence", sa.BigInteger(), nullable=False),
        sa.Column("invoice_number", sa.String(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("billing_timezone", sa.String(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("service_completion_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("purchase_order_number", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("currency_decimal_places", sa.Integer(), nullable=False),
        sa.Column("line_rounding_policy", sa.String(), nullable=False),
        sa.Column("vat_rounding_policy", sa.String(), nullable=False),
        sa.Column("exact_source_ht_numerator", sa.Numeric(), nullable=False),
        sa.Column("exact_source_ht_denominator", sa.Numeric(), nullable=False),
        sa.Column("ht_minor_units", sa.Numeric(), nullable=False),
        sa.Column("vat_minor_units", sa.Numeric(), nullable=False),
        sa.Column("ttc_minor_units", sa.Numeric(), nullable=False),
        sa.Column("vat_regime", sa.String(), nullable=False),
        sa.Column("franchise_legal_basis", sa.String(), nullable=True),
        sa.Column("franchise_invoice_mention", sa.String(), nullable=True),
        sa.Column("default_vat_rate_percent", sa.Numeric(), nullable=True),
        sa.Column("vat_on_debits", sa.Boolean(), nullable=False),
        sa.Column("operation_category", sa.String(), nullable=False),
        sa.Column("payment_due_rule", sa.String(), nullable=False),
        sa.Column("payment_net_days", sa.Integer(), nullable=True),
        sa.Column("early_discount_kind", sa.String(), nullable=False),
        sa.Column("early_discount_rate_percent", sa.Numeric(), nullable=True),
        sa.Column("early_discount_days_after_issue", sa.Integer(), nullable=True),
        sa.Column("early_discount_mention", sa.String(), nullable=False),
        sa.Column("late_payment_penalty_annual_rate_percent", sa.Numeric(), nullable=False),
        sa.Column("late_payment_minimum_annual_rate_percent", sa.Numeric(), nullable=False),
        sa.Column("late_payment_legal_policy", sa.String(), nullable=False),
        sa.Column("recovery_indemnity_policy", sa.String(), nullable=False),
        sa.Column("recovery_indemnity_currency", sa.String(), nullable=False),
        sa.Column("recovery_indemnity_minor_units", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "invoice_number = number_sequence::text",
            name=op.f("ck_issued_invoices_canonical_number"),
        ),
        sa.CheckConstraint(
            "service_completion_date <= issue_date",
            name=op.f("ck_issued_invoices_completed_service"),
        ),
        sa.CheckConstraint(
            "exact_source_ht_numerator = trunc(exact_source_ht_numerator) "
            "AND exact_source_ht_numerator >= 0",
            name=op.f("ck_issued_invoices_integral_exact_source_ht_numerator"),
        ),
        sa.CheckConstraint(
            "purchase_order_number IS NULL OR length(btrim(purchase_order_number)) > 0",
            name=op.f("ck_issued_invoices_nonblank_purchase_order"),
        ),
        sa.CheckConstraint(
            "source_revision > 0", name=op.f("ck_issued_invoices_positive_source_revision")
        ),
        sa.CheckConstraint(
            "number_sequence > 0", name=op.f("ck_issued_invoices_positive_number_sequence")
        ),
        sa.CheckConstraint(
            "exact_source_ht_denominator = trunc(exact_source_ht_denominator) "
            "AND exact_source_ht_denominator > 0",
            name=op.f("ck_issued_invoices_valid_exact_source_ht_denominator"),
        ),
        sa.CheckConstraint(
            "ht_minor_units = trunc(ht_minor_units) AND ht_minor_units >= 0 "
            "AND vat_minor_units = trunc(vat_minor_units) AND vat_minor_units >= 0 "
            "AND ttc_minor_units = trunc(ttc_minor_units) "
            "AND ttc_minor_units = ht_minor_units + vat_minor_units",
            name=op.f("ck_issued_invoices_reconciled_integral_totals"),
        ),
        sa.CheckConstraint(
            "recovery_indemnity_policy = 'french_b2b_40_eur' "
            "AND recovery_indemnity_currency = 'EUR' "
            "AND recovery_indemnity_minor_units = 4000",
            name=op.f("ck_issued_invoices_french_recovery_indemnity"),
        ),
        sa.CheckConstraint(
            "operation_category = 'services'",
            name=op.f("ck_issued_invoices_services_only"),
        ),
        sa.CheckConstraint(
            "currency = 'EUR' AND currency_decimal_places = 2",
            name=op.f("ck_issued_invoices_supported_currency_precision"),
        ),
        sa.CheckConstraint(
            "line_rounding_policy = 'per_line_half_up' AND "
            "vat_rounding_policy = 'per_rate_subtotal_half_up'",
            name=op.f("ck_issued_invoices_supported_rounding_policies"),
        ),
        sa.CheckConstraint(
            "number_series = 'main'",
            name=op.f("ck_issued_invoices_supported_number_series"),
        ),
        sa.CheckConstraint(
            "payment_due_rule IN ('due_on_issue', 'net_days_after_issue', "
            "'invoice_month_end_plus_45_days', 'end_of_month_after_45_days')",
            name=op.f("ck_issued_invoices_valid_payment_due_rule"),
        ),
        sa.CheckConstraint(
            "length(btrim(early_discount_mention)) > 0",
            name=op.f("ck_issued_invoices_nonblank_early_discount_mention"),
        ),
        sa.CheckConstraint(
            "vat_regime IN ('franchise_en_base', 'taxable')",
            name=op.f("ck_issued_invoices_valid_vat_regime"),
        ),
        sa.ForeignKeyConstraint(
            ["source_invoice_id", "source_revision", "workspace_id"],
            ["invoice_drafts.id", "invoice_drafts.revision", "invoice_drafts.workspace_id"],
            name=op.f("fk_issued_invoices_source_invoice_id_invoice_drafts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issued_invoices")),
        sa.UniqueConstraint(
            "workspace_id", "invoice_number", name=op.f("uq_issued_invoices_legal_invoice_number")
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "number_series",
            "number_sequence",
            name=op.f("uq_issued_invoices_legal_sequence"),
        ),
        sa.UniqueConstraint(
            "source_invoice_id",
            name=op.f("uq_issued_invoices_one_issuance_per_logical_invoice"),
        ),
        sa.UniqueConstraint(
            "id", "workspace_id", name=op.f("uq_issued_invoices_identity_workspace")
        ),
        sa.UniqueConstraint(
            "id",
            "source_invoice_id",
            "source_revision",
            "workspace_id",
            name=op.f("uq_issued_invoices_head_binding"),
        ),
    )
    op.create_table(
        "issued_invoice_clients",
        sa.Column("issued_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_client_id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(), nullable=False),
        sa.Column("trading_name", sa.String(), nullable=True),
        sa.Column("siren", sa.String(), nullable=False),
        sa.Column("vat_number", sa.String(), nullable=True),
        sa.Column("legal_line1", sa.String(), nullable=False),
        sa.Column("legal_line2", sa.String(), nullable=True),
        sa.Column("legal_postal_code", sa.String(), nullable=True),
        sa.Column("legal_city", sa.String(), nullable=False),
        sa.Column("legal_country_code", sa.String(), nullable=False),
        sa.Column("billing_line1", sa.String(), nullable=True),
        sa.Column("billing_line2", sa.String(), nullable=True),
        sa.Column("billing_postal_code", sa.String(), nullable=True),
        sa.Column("billing_city", sa.String(), nullable=True),
        sa.Column("billing_country_code", sa.String(), nullable=True),
        sa.CheckConstraint(
            "legal_country_code = 'FR'",
            name=op.f("ck_issued_invoice_clients_french_legal_address"),
        ),
        sa.CheckConstraint(
            "siren ~ '^[0-9]{9}$'", name=op.f("ck_issued_invoice_clients_siren_shape")
        ),
        sa.ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
            name=op.f("fk_issued_invoice_clients_issued_invoice_id_issued_invoices"),
        ),
        sa.PrimaryKeyConstraint(
            "issued_invoice_id", name=op.f("pk_issued_invoice_clients")
        ),
    )
    op.create_table(
        "issued_invoice_sellers",
        sa.Column("issued_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("legal_entity_kind", sa.String(), nullable=False),
        sa.Column("legal_name", sa.String(), nullable=False),
        sa.Column("trading_name", sa.String(), nullable=True),
        sa.Column("siren", sa.String(), nullable=False),
        sa.Column("siret", sa.String(), nullable=False),
        sa.Column("vat_number", sa.String(), nullable=True),
        sa.Column("legal_form", sa.String(), nullable=True),
        sa.Column("share_capital", sa.Numeric(), nullable=True),
        sa.Column("share_capital_currency", sa.String(), nullable=True),
        sa.Column("legal_line1", sa.String(), nullable=False),
        sa.Column("legal_line2", sa.String(), nullable=True),
        sa.Column("legal_postal_code", sa.String(), nullable=True),
        sa.Column("legal_city", sa.String(), nullable=False),
        sa.Column("legal_country_code", sa.String(), nullable=False),
        sa.Column("billing_line1", sa.String(), nullable=True),
        sa.Column("billing_line2", sa.String(), nullable=True),
        sa.Column("billing_postal_code", sa.String(), nullable=True),
        sa.Column("billing_city", sa.String(), nullable=True),
        sa.Column("billing_country_code", sa.String(), nullable=True),
        sa.CheckConstraint(
            "legal_entity_kind IN ('individual', 'company')",
            name=op.f("ck_issued_invoice_sellers_entity_kind"),
        ),
        sa.CheckConstraint(
            "legal_country_code = 'FR'",
            name=op.f("ck_issued_invoice_sellers_french_legal_address"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
            name=op.f("fk_issued_invoice_sellers_issued_invoice_id_issued_invoices"),
        ),
        sa.PrimaryKeyConstraint(
            "issued_invoice_id", name=op.f("pk_issued_invoice_sellers")
        ),
    )
    op.create_table(
        "issued_invoice_vat_breakdowns",
        sa.Column("issued_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("exact_source_ht_numerator", sa.Numeric(), nullable=False),
        sa.Column("exact_source_ht_denominator", sa.Numeric(), nullable=False),
        sa.Column("ht_base_minor_units", sa.Numeric(), nullable=False),
        sa.Column("vat_rate_percent", sa.Numeric(), nullable=True),
        sa.Column("franchise_legal_basis", sa.String(), nullable=True),
        sa.Column("franchise_invoice_mention", sa.String(), nullable=True),
        sa.Column("exact_vat_numerator", sa.Numeric(), nullable=False),
        sa.Column("exact_vat_denominator", sa.Numeric(), nullable=False),
        sa.Column("vat_minor_units", sa.Numeric(), nullable=False),
        sa.Column("rounding_policy", sa.String(), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_issued_invoice_vat_breakdowns_nonnegative_position"),
        ),
        sa.CheckConstraint(
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
            name=op.f(
                "ck_issued_invoice_vat_breakdowns_exact_nonnegative_amounts"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
            name=op.f("fk_issued_invoice_vat_breakdowns_issued_invoice_id_issued_invoices"),
        ),
        sa.PrimaryKeyConstraint(
            "issued_invoice_id",
            "position",
            name=op.f("pk_issued_invoice_vat_breakdowns"),
        ),
        sa.UniqueConstraint(
            "issued_invoice_id",
            "position",
            "workspace_id",
            name=op.f("uq_issued_invoice_vat_breakdowns_issued_invoice_id"),
        ),
    )
    op.create_table(
        "issued_invoice_lines",
        sa.Column("issued_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("vat_breakdown_position", sa.Integer(), nullable=False),
        sa.Column("source_invoice_line_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("project_name", sa.String(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("task_name", sa.String(), nullable=True),
        sa.Column("rate_agreement_id", sa.Uuid(), nullable=False),
        sa.Column("rate_scope_project_id", sa.Uuid(), nullable=True),
        sa.Column("rate_valid_from", sa.Date(), nullable=False),
        sa.Column("rate_valid_until", sa.Date(), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(), nullable=False),
        sa.Column("duration_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("exact_amount_numerator", sa.Numeric(), nullable=False),
        sa.Column("exact_amount_denominator", sa.Numeric(), nullable=False),
        sa.Column("rounded_ht_minor_units", sa.Numeric(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(description)) > 0",
            name=op.f("ck_issued_invoice_lines_nonblank_description"),
        ),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_issued_invoice_lines_nonnegative_position"),
        ),
        sa.CheckConstraint(
            "vat_breakdown_position >= 0",
            name=op.f("ck_issued_invoice_lines_nonnegative_vat_position"),
        ),
        sa.CheckConstraint(
            "rounded_ht_minor_units = trunc(rounded_ht_minor_units) "
            "AND rounded_ht_minor_units >= 0",
            name=op.f("ck_issued_invoice_lines_integral_nonnegative_ht"),
        ),
        sa.CheckConstraint(
            "exact_amount_numerator = trunc(exact_amount_numerator) "
            "AND exact_amount_numerator >= 0 "
            "AND exact_amount_denominator = trunc(exact_amount_denominator) "
            "AND exact_amount_denominator > 0",
            name=op.f("ck_issued_invoice_lines_exact_nonnegative_amount"),
        ),
        sa.CheckConstraint(
            "hourly_rate NOT IN ('NaN', 'Infinity', '-Infinity') "
            "AND hourly_rate >= 0",
            name=op.f("ck_issued_invoice_lines_finite_nonnegative_hourly_rate"),
        ),
        sa.CheckConstraint(
            "duration_microseconds > 0",
            name=op.f("ck_issued_invoice_lines_positive_duration"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
            name=op.f("fk_issued_invoice_lines_issued_invoice_id_issued_invoices"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_invoice_id", "vat_breakdown_position", "workspace_id"],
            [
                "issued_invoice_vat_breakdowns.issued_invoice_id",
                "issued_invoice_vat_breakdowns.position",
                "issued_invoice_vat_breakdowns.workspace_id",
            ],
            name=op.f(
                "fk_issued_invoice_lines_issued_invoice_id_issued_invoice_vat_breakdowns"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "issued_invoice_id", "position", name=op.f("pk_issued_invoice_lines")
        ),
        sa.UniqueConstraint(
            "issued_invoice_id",
            "position",
            "workspace_id",
            name=op.f("uq_issued_invoice_lines_issued_invoice_id"),
        ),
        sa.UniqueConstraint(
            "issued_invoice_id",
            "source_invoice_line_id",
            name=op.f("uq_issued_invoice_lines_source_line"),
        ),
    )
    op.create_table(
        "issued_invoice_allocations",
        sa.Column("issued_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("line_position", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_time_entry_id", sa.Uuid(), nullable=False),
        sa.Column("source_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_billable", sa.Boolean(), nullable=False),
        sa.Column("segment_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("segment_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("duration_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("exact_amount_numerator", sa.Numeric(), nullable=False),
        sa.Column("exact_amount_denominator", sa.Numeric(), nullable=False),
        sa.CheckConstraint(
            "source_billable",
            name=op.f("ck_issued_invoice_allocations_billable_source"),
        ),
        sa.CheckConstraint(
            "segment_start >= source_start AND segment_end <= source_end",
            name=op.f("ck_issued_invoice_allocations_contained_segment"),
        ),
        sa.CheckConstraint(
            "line_position >= 0 AND position >= 0",
            name=op.f("ck_issued_invoice_allocations_nonnegative_positions"),
        ),
        sa.CheckConstraint(
            "exact_amount_numerator = trunc(exact_amount_numerator) "
            "AND exact_amount_numerator >= 0 "
            "AND exact_amount_denominator = trunc(exact_amount_denominator) "
            "AND exact_amount_denominator > 0",
            name=op.f("ck_issued_invoice_allocations_exact_nonnegative_amount"),
        ),
        sa.CheckConstraint(
            "duration_microseconds > 0",
            name=op.f("ck_issued_invoice_allocations_positive_duration"),
        ),
        sa.CheckConstraint(
            "segment_end > segment_start",
            name=op.f("ck_issued_invoice_allocations_positive_segment_interval"),
        ),
        sa.CheckConstraint(
            "source_end > source_start",
            name=op.f("ck_issued_invoice_allocations_positive_source_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_invoice_id", "line_position", "workspace_id"],
            [
                "issued_invoice_lines.issued_invoice_id",
                "issued_invoice_lines.position",
                "issued_invoice_lines.workspace_id",
            ],
            name=op.f(
                "fk_issued_invoice_allocations_issued_invoice_id_issued_invoice_lines"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "issued_invoice_id",
            "line_position",
            "position",
            name=op.f("pk_issued_invoice_allocations"),
        ),
    )
    op.add_column(
        "invoice_draft_heads", sa.Column("issued_invoice_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "invoice_draft_heads", sa.Column("issued_revision", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_invoice_draft_heads_consistent_issuance_freeze"),
        "invoice_draft_heads",
        "(issued_invoice_id IS NULL AND issued_revision IS NULL) OR "
        "(issued_invoice_id IS NOT NULL AND issued_revision = current_revision)",
    )
    op.create_foreign_key(
        op.f("fk_invoice_draft_heads_issued_invoice_id_issued_invoices"),
        "invoice_draft_heads",
        "issued_invoices",
        ["issued_invoice_id", "id", "issued_revision", "workspace_id"],
        ["id", "source_invoice_id", "source_revision", "workspace_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_invoice_draft_heads_issued_invoice_id_issued_invoices"),
        "invoice_draft_heads",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_invoice_draft_heads_consistent_issuance_freeze"),
        "invoice_draft_heads",
        type_="check",
    )
    op.drop_column("invoice_draft_heads", "issued_revision")
    op.drop_column("invoice_draft_heads", "issued_invoice_id")
    op.drop_table("issued_invoice_allocations")
    op.drop_table("issued_invoice_lines")
    op.drop_table("issued_invoice_vat_breakdowns")
    op.drop_table("issued_invoice_sellers")
    op.drop_table("issued_invoice_clients")
    op.drop_table("issued_invoices")
    op.drop_table("invoice_number_counters")
