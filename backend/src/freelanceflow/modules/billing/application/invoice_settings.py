"""HTTP-independent use cases for mutable workspace invoice defaults."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from freelanceflow.modules.billing.domain.invoice_settings import (
    BillingTimezone,
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
    parse_exact_percentage,
)


class InvoiceSettingsNotFound(LookupError):
    """The requested workspace has no current invoice settings."""


class InvoiceSettingsAlreadyExists(ValueError):
    """The workspace already has current invoice settings."""


@dataclass(frozen=True)
class FiscalSettingsData:
    vat_regime: VatRegime
    franchise_legal_basis: FranchiseLegalBasis | None
    default_vat_rate_percent: str | None
    vat_on_debits: bool


@dataclass(frozen=True)
class PaymentTermsData:
    due_rule: PaymentDueRule
    net_days: int | None


@dataclass(frozen=True)
class EarlyPaymentDiscountData:
    kind: EarlyPaymentDiscountKind
    rate_percent: str | None
    days_after_issue: int | None


@dataclass(frozen=True)
class WorkspaceInvoiceSettingsData:
    fiscal: FiscalSettingsData
    payment_terms: PaymentTermsData
    early_payment_discount: EarlyPaymentDiscountData
    late_payment_penalty_annual_rate_percent: str
    recovery_indemnity_policy: RecoveryIndemnityPolicy
    operation_category: InvoiceOperationCategory
    billing_timezone: str | None = None


class InvoiceSettingsStore(Protocol):
    def add(self, value: WorkspaceInvoiceSettings) -> bool: ...
    def get(self) -> WorkspaceInvoiceSettings | None: ...
    def update(self, value: WorkspaceInvoiceSettings) -> bool: ...


class InvoiceSettingsTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[InvoiceSettingsStore]: ...


def _build_settings(
    workspace_id: UUID, data: WorkspaceInvoiceSettingsData
) -> WorkspaceInvoiceSettings:
    fiscal = FiscalSettings(
        vat_regime=data.fiscal.vat_regime,
        franchise_legal_basis=data.fiscal.franchise_legal_basis,
        default_vat_rate_percent=parse_exact_percentage(
            data.fiscal.default_vat_rate_percent,
            field="Default VAT rate",
        ),
        vat_on_debits=data.fiscal.vat_on_debits,
    )
    payment_terms = PaymentTerms(
        due_rule=data.payment_terms.due_rule,
        net_days=data.payment_terms.net_days,
    )
    early_payment_discount = EarlyPaymentDiscount(
        kind=data.early_payment_discount.kind,
        rate_percent=parse_exact_percentage(
            data.early_payment_discount.rate_percent,
            field="Early-payment discount rate",
        ),
        days_after_issue=data.early_payment_discount.days_after_issue,
    )
    late_rate = parse_exact_percentage(
        data.late_payment_penalty_annual_rate_percent,
        field="Late-payment penalty annual rate",
    )
    assert late_rate is not None
    return WorkspaceInvoiceSettings(
        workspace_id=workspace_id,
        fiscal=fiscal,
        payment_terms=payment_terms,
        early_payment_discount=early_payment_discount,
        late_payment_penalty_annual_rate_percent=late_rate,
        recovery_indemnity_policy=data.recovery_indemnity_policy,
        operation_category=data.operation_category,
        billing_timezone=(
            BillingTimezone(data.billing_timezone) if data.billing_timezone is not None else None
        ),
    )


class InvoiceSettingsService:
    def __init__(self, transaction: InvoiceSettingsTransaction) -> None:
        self.transaction = transaction

    def create(
        self, workspace_id: UUID, data: WorkspaceInvoiceSettingsData
    ) -> WorkspaceInvoiceSettings:
        settings = _build_settings(workspace_id, data)
        with self.transaction(workspace_id) as store:
            if not store.add(settings):
                raise InvoiceSettingsAlreadyExists("Invoice settings already exist")
        return settings

    def get(self, workspace_id: UUID) -> WorkspaceInvoiceSettings:
        with self.transaction(workspace_id) as store:
            settings = store.get()
            if settings is None:
                raise InvoiceSettingsNotFound("Invoice settings not found")
        return settings

    def update(
        self, workspace_id: UUID, data: WorkspaceInvoiceSettingsData
    ) -> WorkspaceInvoiceSettings:
        settings = _build_settings(workspace_id, data)
        with self.transaction(workspace_id) as store:
            if not store.update(settings):
                raise InvoiceSettingsNotFound("Invoice settings not found")
        return settings
