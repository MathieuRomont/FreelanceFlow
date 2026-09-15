"""Workspace-scoped HTTP boundary for fiscal and payment defaults."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from freelanceflow.modules.billing.application.invoice_settings import (
    EarlyPaymentDiscountData,
    FiscalSettingsData,
    InvoiceSettingsAlreadyExists,
    InvoiceSettingsNotFound,
    InvoiceSettingsService,
    PaymentTermsData,
    WorkspaceInvoiceSettingsData,
)
from freelanceflow.modules.billing.domain.invoice_settings import (
    EarlyPaymentDiscount,
    EarlyPaymentDiscountKind,
    FiscalSettings,
    FranchiseLegalBasis,
    InvalidInvoiceSettings,
    InvoiceOperationCategory,
    PaymentDueRule,
    PaymentTerms,
    RecoveryIndemnityPolicy,
    VatRegime,
    WorkspaceInvoiceSettings,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/invoice-settings",
    tags=["invoice-settings"],
)


class FiscalSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vat_regime: VatRegime
    franchise_legal_basis: FranchiseLegalBasis | None = None
    default_vat_rate_percent: str | None = None
    vat_on_debits: bool

    def to_application(self) -> FiscalSettingsData:
        return FiscalSettingsData(
            vat_regime=self.vat_regime,
            franchise_legal_basis=self.franchise_legal_basis,
            default_vat_rate_percent=self.default_vat_rate_percent,
            vat_on_debits=self.vat_on_debits,
        )


class PaymentTermsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    due_rule: PaymentDueRule
    net_days: int | None = None

    def to_application(self) -> PaymentTermsData:
        return PaymentTermsData(due_rule=self.due_rule, net_days=self.net_days)


class EarlyPaymentDiscountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EarlyPaymentDiscountKind
    rate_percent: str | None = None
    days_after_issue: int | None = None

    def to_application(self) -> EarlyPaymentDiscountData:
        return EarlyPaymentDiscountData(
            kind=self.kind,
            rate_percent=self.rate_percent,
            days_after_issue=self.days_after_issue,
        )


class WorkspaceInvoiceSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fiscal: FiscalSettingsRequest
    payment_terms: PaymentTermsRequest
    early_payment_discount: EarlyPaymentDiscountRequest
    late_payment_penalty_annual_rate_percent: str
    recovery_indemnity_policy: RecoveryIndemnityPolicy
    operation_category: InvoiceOperationCategory

    def to_application(self) -> WorkspaceInvoiceSettingsData:
        return WorkspaceInvoiceSettingsData(
            fiscal=self.fiscal.to_application(),
            payment_terms=self.payment_terms.to_application(),
            early_payment_discount=self.early_payment_discount.to_application(),
            late_payment_penalty_annual_rate_percent=(
                self.late_payment_penalty_annual_rate_percent
            ),
            recovery_indemnity_policy=self.recovery_indemnity_policy,
            operation_category=self.operation_category,
        )


class FiscalSettingsResponse(BaseModel):
    vat_regime: VatRegime
    franchise_legal_basis: FranchiseLegalBasis | None
    franchise_invoice_mention: str | None
    default_vat_rate_percent: str | None
    vat_on_debits: bool

    @classmethod
    def from_domain(cls, value: FiscalSettings) -> "FiscalSettingsResponse":
        return cls(
            vat_regime=value.vat_regime,
            franchise_legal_basis=value.franchise_legal_basis,
            franchise_invoice_mention=value.franchise_invoice_mention,
            default_vat_rate_percent=(
                str(value.default_vat_rate_percent)
                if value.default_vat_rate_percent is not None
                else None
            ),
            vat_on_debits=value.vat_on_debits,
        )


class PaymentTermsResponse(BaseModel):
    due_rule: PaymentDueRule
    net_days: int | None

    @classmethod
    def from_domain(cls, value: PaymentTerms) -> "PaymentTermsResponse":
        return cls(due_rule=value.due_rule, net_days=value.net_days)


class EarlyPaymentDiscountResponse(BaseModel):
    kind: EarlyPaymentDiscountKind
    rate_percent: str | None
    days_after_issue: int | None

    @classmethod
    def from_domain(cls, value: EarlyPaymentDiscount) -> "EarlyPaymentDiscountResponse":
        return cls(
            kind=value.kind,
            rate_percent=(str(value.rate_percent) if value.rate_percent is not None else None),
            days_after_issue=value.days_after_issue,
        )


class WorkspaceInvoiceSettingsResponse(BaseModel):
    workspace_id: UUID
    fiscal: FiscalSettingsResponse
    payment_terms: PaymentTermsResponse
    early_payment_discount: EarlyPaymentDiscountResponse
    late_payment_penalty_annual_rate_percent: str
    recovery_indemnity_policy: RecoveryIndemnityPolicy
    recovery_indemnity_currency: str
    recovery_indemnity_minor_units: int
    operation_category: InvoiceOperationCategory

    @classmethod
    def from_domain(cls, value: WorkspaceInvoiceSettings) -> "WorkspaceInvoiceSettingsResponse":
        return cls(
            workspace_id=value.workspace_id,
            fiscal=FiscalSettingsResponse.from_domain(value.fiscal),
            payment_terms=PaymentTermsResponse.from_domain(value.payment_terms),
            early_payment_discount=EarlyPaymentDiscountResponse.from_domain(
                value.early_payment_discount
            ),
            late_payment_penalty_annual_rate_percent=str(
                value.late_payment_penalty_annual_rate_percent
            ),
            recovery_indemnity_policy=value.recovery_indemnity_policy,
            recovery_indemnity_currency=value.recovery_indemnity_currency,
            recovery_indemnity_minor_units=value.recovery_indemnity_minor_units,
            operation_category=value.operation_category,
        )


def get_invoice_settings_service() -> InvoiceSettingsService:
    raise RuntimeError("InvoiceSettings service must be supplied by bootstrap")


Service = Annotated[InvoiceSettingsService, Depends(get_invoice_settings_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


def _settings_error(error: Exception) -> HTTPException:
    if isinstance(error, InvoiceSettingsAlreadyExists):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, InvoiceSettingsNotFound):
        return _not_found()
    return HTTPException(status_code=422, detail=str(error))


@router.post("", status_code=201, response_model=WorkspaceInvoiceSettingsResponse)
def create_invoice_settings(
    workspace_id: UUID,
    body: WorkspaceInvoiceSettingsRequest,
    service: Service,
) -> WorkspaceInvoiceSettingsResponse:
    try:
        settings = service.create(workspace_id, body.to_application())
    except (
        InvoiceSettingsAlreadyExists,
        InvoiceSettingsNotFound,
        InvalidInvoiceSettings,
    ) as error:
        raise _settings_error(error) from error
    return WorkspaceInvoiceSettingsResponse.from_domain(settings)


@router.get("", response_model=WorkspaceInvoiceSettingsResponse)
def get_invoice_settings(workspace_id: UUID, service: Service) -> WorkspaceInvoiceSettingsResponse:
    try:
        settings = service.get(workspace_id)
    except InvoiceSettingsNotFound as error:
        raise _not_found() from error
    return WorkspaceInvoiceSettingsResponse.from_domain(settings)


@router.put("", response_model=WorkspaceInvoiceSettingsResponse)
def update_invoice_settings(
    workspace_id: UUID,
    body: WorkspaceInvoiceSettingsRequest,
    service: Service,
) -> WorkspaceInvoiceSettingsResponse:
    try:
        settings = service.update(workspace_id, body.to_application())
    except (InvoiceSettingsNotFound, InvalidInvoiceSettings) as error:
        raise _settings_error(error) from error
    return WorkspaceInvoiceSettingsResponse.from_domain(settings)
