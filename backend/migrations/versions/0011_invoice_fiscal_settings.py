"""Add mutable workspace fiscal and payment invoice defaults."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_invoice_settings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("vat_regime", sa.String(), nullable=False),
        sa.Column("franchise_legal_basis", sa.String(), nullable=True),
        sa.Column("default_vat_rate_percent", sa.Numeric(), nullable=True),
        sa.Column("vat_on_debits", sa.Boolean(), nullable=False),
        sa.Column("payment_due_rule", sa.String(), nullable=False),
        sa.Column("payment_net_days", sa.Integer(), nullable=True),
        sa.Column("early_discount_kind", sa.String(), nullable=False),
        sa.Column("early_discount_rate_percent", sa.Numeric(), nullable=True),
        sa.Column("early_discount_days_after_issue", sa.Integer(), nullable=True),
        sa.Column(
            "late_payment_penalty_annual_rate_percent",
            sa.Numeric(),
            nullable=False,
        ),
        sa.Column("recovery_indemnity_policy", sa.String(), nullable=False),
        sa.Column("operation_category", sa.String(), nullable=False),
        sa.CheckConstraint(
            "vat_regime IN ('franchise_en_base', 'taxable')",
            name=op.f("ck_workspace_invoice_settings_valid_vat_regime"),
        ),
        sa.CheckConstraint(
            "(vat_regime = 'franchise_en_base' "
            "AND franchise_legal_basis IN "
            "('cgi_293_b', 'cgi_293_b_bis', 'eu_directive_2006_112_article_284') "
            "AND default_vat_rate_percent IS NULL AND NOT vat_on_debits) OR "
            "(vat_regime = 'taxable' AND franchise_legal_basis IS NULL "
            "AND default_vat_rate_percent IS NOT NULL)",
            name=op.f("ck_workspace_invoice_settings_consistent_vat_configuration"),
        ),
        sa.CheckConstraint(
            "default_vat_rate_percent IS NULL OR "
            "(default_vat_rate_percent NOT IN ('NaN', 'Infinity', '-Infinity') "
            "AND default_vat_rate_percent >= 0 "
            "AND default_vat_rate_percent <= 100)",
            name=op.f("ck_workspace_invoice_settings_valid_default_vat_rate"),
        ),
        sa.CheckConstraint(
            "(payment_due_rule = 'due_on_issue' AND payment_net_days IS NULL) OR "
            "(payment_due_rule = 'net_days_after_issue' "
            "AND payment_net_days BETWEEN 1 AND 60) OR "
            "(payment_due_rule IN ('invoice_month_end_plus_45_days', "
            "'end_of_month_after_45_days') AND payment_net_days IS NULL)",
            name=op.f("ck_workspace_invoice_settings_valid_payment_terms"),
        ),
        sa.CheckConstraint(
            "(early_discount_kind = 'none' "
            "AND early_discount_rate_percent IS NULL "
            "AND early_discount_days_after_issue IS NULL) OR "
            "(early_discount_kind = 'percentage_within_days' "
            "AND early_discount_rate_percent IS NOT NULL "
            "AND early_discount_rate_percent NOT IN "
            "('NaN', 'Infinity', '-Infinity') "
            "AND early_discount_rate_percent > 0 "
            "AND early_discount_rate_percent <= 100 "
            "AND early_discount_days_after_issue >= 1)",
            name=op.f("ck_workspace_invoice_settings_valid_early_discount"),
        ),
        sa.CheckConstraint(
            "late_payment_penalty_annual_rate_percent NOT IN "
            "('NaN', 'Infinity', '-Infinity') "
            "AND late_payment_penalty_annual_rate_percent > 0",
            name=op.f("ck_workspace_invoice_settings_valid_late_payment_penalty_rate"),
        ),
        sa.CheckConstraint(
            "recovery_indemnity_policy = 'french_b2b_40_eur'",
            name=op.f("ck_workspace_invoice_settings_supported_recovery_indemnity"),
        ),
        sa.CheckConstraint(
            "operation_category = 'services'",
            name=op.f("ck_workspace_invoice_settings_supported_operation_category"),
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_workspace_invoice_settings")),
    )


def downgrade() -> None:
    op.drop_table("workspace_invoice_settings")
