"""Relational row for mutable workspace invoice defaults."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class WorkspaceInvoiceSettingsRow(Base):
    __tablename__ = "workspace_invoice_settings"
    __table_args__ = (
        CheckConstraint(
            "vat_regime IN ('franchise_en_base', 'taxable')",
            name="valid_vat_regime",
        ),
        CheckConstraint(
            "(vat_regime = 'franchise_en_base' "
            "AND franchise_legal_basis IN "
            "('cgi_293_b', 'cgi_293_b_bis', 'eu_directive_2006_112_article_284') "
            "AND default_vat_rate_percent IS NULL AND NOT vat_on_debits) OR "
            "(vat_regime = 'taxable' AND franchise_legal_basis IS NULL "
            "AND default_vat_rate_percent IS NOT NULL)",
            name="consistent_vat_configuration",
        ),
        CheckConstraint(
            "default_vat_rate_percent IS NULL OR "
            "(default_vat_rate_percent NOT IN ('NaN', 'Infinity', '-Infinity') "
            "AND default_vat_rate_percent >= 0 "
            "AND default_vat_rate_percent <= 100)",
            name="valid_default_vat_rate",
        ),
        CheckConstraint(
            "(payment_due_rule = 'due_on_issue' AND payment_net_days IS NULL) OR "
            "(payment_due_rule = 'net_days_after_issue' "
            "AND payment_net_days BETWEEN 1 AND 60) OR "
            "(payment_due_rule IN ('invoice_month_end_plus_45_days', "
            "'end_of_month_after_45_days') AND payment_net_days IS NULL)",
            name="valid_payment_terms",
        ),
        CheckConstraint(
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
            name="valid_early_discount",
        ),
        CheckConstraint(
            "late_payment_penalty_annual_rate_percent NOT IN "
            "('NaN', 'Infinity', '-Infinity') "
            "AND late_payment_penalty_annual_rate_percent > 0",
            name="valid_late_payment_penalty_rate",
        ),
        CheckConstraint(
            "recovery_indemnity_policy = 'french_b2b_40_eur'",
            name="supported_recovery_indemnity",
        ),
        CheckConstraint(
            "operation_category = 'services'",
            name="supported_operation_category",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(primary_key=True)
    vat_regime: Mapped[str]
    franchise_legal_basis: Mapped[str | None]
    default_vat_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric())
    vat_on_debits: Mapped[bool]
    payment_due_rule: Mapped[str]
    payment_net_days: Mapped[int | None] = mapped_column(Integer)
    early_discount_kind: Mapped[str]
    early_discount_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric())
    early_discount_days_after_issue: Mapped[int | None] = mapped_column(Integer)
    late_payment_penalty_annual_rate_percent: Mapped[Decimal] = mapped_column(Numeric())
    recovery_indemnity_policy: Mapped[str]
    operation_category: Mapped[str]
