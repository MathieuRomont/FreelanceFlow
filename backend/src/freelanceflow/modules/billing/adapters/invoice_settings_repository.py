"""Explicit persistence mapping for mutable workspace invoice defaults."""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.invoice_settings_models import (
    WorkspaceInvoiceSettingsRow,
)
from freelanceflow.modules.billing.domain.invoice_settings import (
    EarlyPaymentDiscount,
    EarlyPaymentDiscountKind,
    FiscalSettings,
    FranchiseLegalBasis,
    InvoiceOperationCategory,
    PaymentDueRule,
    PaymentTerms,
    RecoveryIndemnityPolicy,
    VatRegime,
    WorkspaceInvoiceSettings,
)


def _values(value: WorkspaceInvoiceSettings) -> dict[str, object]:
    return {
        "workspace_id": value.workspace_id,
        "vat_regime": value.fiscal.vat_regime.value,
        "franchise_legal_basis": (
            value.fiscal.franchise_legal_basis.value if value.fiscal.franchise_legal_basis else None
        ),
        "default_vat_rate_percent": value.fiscal.default_vat_rate_percent,
        "vat_on_debits": value.fiscal.vat_on_debits,
        "payment_due_rule": value.payment_terms.due_rule.value,
        "payment_net_days": value.payment_terms.net_days,
        "early_discount_kind": value.early_payment_discount.kind.value,
        "early_discount_rate_percent": value.early_payment_discount.rate_percent,
        "early_discount_days_after_issue": (value.early_payment_discount.days_after_issue),
        "late_payment_penalty_annual_rate_percent": (
            value.late_payment_penalty_annual_rate_percent
        ),
        "recovery_indemnity_policy": value.recovery_indemnity_policy.value,
        "operation_category": value.operation_category.value,
    }


def _to_domain(row: WorkspaceInvoiceSettingsRow) -> WorkspaceInvoiceSettings:
    return WorkspaceInvoiceSettings(
        workspace_id=row.workspace_id,
        fiscal=FiscalSettings(
            vat_regime=VatRegime(row.vat_regime),
            franchise_legal_basis=(
                FranchiseLegalBasis(row.franchise_legal_basis)
                if row.franchise_legal_basis
                else None
            ),
            default_vat_rate_percent=row.default_vat_rate_percent,
            vat_on_debits=row.vat_on_debits,
        ),
        payment_terms=PaymentTerms(
            due_rule=PaymentDueRule(row.payment_due_rule),
            net_days=row.payment_net_days,
        ),
        early_payment_discount=EarlyPaymentDiscount(
            kind=EarlyPaymentDiscountKind(row.early_discount_kind),
            rate_percent=row.early_discount_rate_percent,
            days_after_issue=row.early_discount_days_after_issue,
        ),
        late_payment_penalty_annual_rate_percent=(row.late_payment_penalty_annual_rate_percent),
        recovery_indemnity_policy=RecoveryIndemnityPolicy(row.recovery_indemnity_policy),
        operation_category=InvoiceOperationCategory(row.operation_category),
    )


class InvoiceSettingsRepository:
    def __init__(self, session: Session, *, workspace_id: UUID) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def add(self, value: WorkspaceInvoiceSettings) -> bool:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        created = self.session.scalar(
            insert(WorkspaceInvoiceSettingsRow)
            .values(**_values(value))
            .on_conflict_do_nothing(index_elements=["workspace_id"])
            .returning(WorkspaceInvoiceSettingsRow.workspace_id)
        )
        self.session.flush()
        return created is not None

    def get(self) -> WorkspaceInvoiceSettings | None:
        row = self.session.get(WorkspaceInvoiceSettingsRow, self.workspace_id)
        return _to_domain(row) if row else None

    def update(self, value: WorkspaceInvoiceSettings) -> bool:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        row = self.session.get(WorkspaceInvoiceSettingsRow, self.workspace_id)
        if row is None:
            return False
        for field, field_value in _values(value).items():
            setattr(row, field, field_value)
        self.session.flush()
        return True
