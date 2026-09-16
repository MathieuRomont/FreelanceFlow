"""Workspace-scoped immutable invoice issuance HTTP boundary."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from freelanceflow.modules.billing.application.issued_invoices import (
    InvoiceIssuanceConfigurationError,
    InvoiceIssuanceConflictError,
    InvoiceIssuanceService,
    IssuedInvoiceResourceNotFound,
    IssueInvoiceCommand,
)
from freelanceflow.modules.billing.domain.billing_profiles import BillingAddress
from freelanceflow.modules.billing.domain.invoice_dates import InvoiceDatePolicyError
from freelanceflow.modules.billing.domain.issued_invoices import (
    InvoiceIssuanceError,
    InvoiceLineDescription,
    IssuedClientSnapshot,
    IssuedFiscalPaymentSnapshot,
    IssuedInvoice,
    IssuedInvoiceAllocation,
    IssuedInvoiceLine,
    IssuedSellerSnapshot,
    IssuedVatBreakdown,
)
from freelanceflow.modules.billing.domain.vat import InvoiceTaxError

router = APIRouter(tags=["issued-invoices"])


class InvoiceLineDescriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_line_id: UUID
    description: str


class IssueInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_revision: int = Field(ge=1)
    service_completion_date: date
    purchase_order_number: str | None = None
    line_descriptions: list[InvoiceLineDescriptionRequest]

    def to_command(self) -> IssueInvoiceCommand:
        return IssueInvoiceCommand(
            source_revision=self.source_revision,
            service_completion_date=self.service_completion_date,
            purchase_order_number=self.purchase_order_number,
            line_descriptions=tuple(
                InvoiceLineDescription(value.invoice_line_id, value.description)
                for value in self.line_descriptions
            ),
        )


class AddressResponse(BaseModel):
    line1: str
    line2: str | None
    postal_code: str | None
    city: str
    country_code: str

    @classmethod
    def from_domain(cls, value: BillingAddress) -> "AddressResponse":
        return cls(**value.__dict__)


class SellerSnapshotResponse(BaseModel):
    legal_entity_kind: str
    legal_name: str
    trading_name: str | None
    siren: str
    siret: str
    vat_number: str | None
    legal_address: AddressResponse
    billing_address: AddressResponse | None
    legal_form: str | None
    share_capital: str | None
    share_capital_currency: str | None

    @classmethod
    def from_domain(cls, value: IssuedSellerSnapshot) -> "SellerSnapshotResponse":
        return cls(
            legal_entity_kind=value.legal_entity_kind.value,
            legal_name=value.legal_name,
            trading_name=value.trading_name,
            siren=value.siren,
            siret=value.siret,
            vat_number=value.vat_number,
            legal_address=AddressResponse.from_domain(value.legal_address),
            billing_address=(
                AddressResponse.from_domain(value.billing_address)
                if value.billing_address
                else None
            ),
            legal_form=value.legal_form,
            share_capital=str(value.share_capital) if value.share_capital is not None else None,
            share_capital_currency=value.share_capital_currency,
        )


class ClientSnapshotResponse(BaseModel):
    source_client_id: UUID
    legal_name: str
    trading_name: str | None
    siren: str
    vat_number: str | None
    legal_address: AddressResponse
    billing_address: AddressResponse | None

    @classmethod
    def from_domain(cls, value: IssuedClientSnapshot) -> "ClientSnapshotResponse":
        return cls(
            source_client_id=value.source_client_id,
            legal_name=value.legal_name,
            trading_name=value.trading_name,
            siren=value.siren,
            vat_number=value.vat_number,
            legal_address=AddressResponse.from_domain(value.legal_address),
            billing_address=(
                AddressResponse.from_domain(value.billing_address)
                if value.billing_address
                else None
            ),
        )


class FiscalPaymentSnapshotResponse(BaseModel):
    vat_regime: str
    franchise_legal_basis: str | None
    franchise_invoice_mention: str | None
    default_vat_rate_percent: str | None
    vat_on_debits: bool
    operation_category: str
    payment_due_rule: str
    payment_net_days: int | None
    early_discount_kind: str
    early_discount_rate_percent: str | None
    early_discount_days_after_issue: int | None
    early_discount_mention: str
    late_payment_penalty_annual_rate_percent: str
    late_payment_minimum_annual_rate_percent: str
    late_payment_legal_policy: str
    recovery_indemnity_policy: str
    recovery_indemnity_currency: str
    recovery_indemnity_minor_units: str

    @classmethod
    def from_domain(
        cls, value: IssuedFiscalPaymentSnapshot
    ) -> "FiscalPaymentSnapshotResponse":
        return cls(
            vat_regime=value.vat_regime.value,
            franchise_legal_basis=value.franchise_legal_basis,
            franchise_invoice_mention=value.franchise_invoice_mention,
            default_vat_rate_percent=(
                str(value.default_vat_rate_percent)
                if value.default_vat_rate_percent is not None
                else None
            ),
            vat_on_debits=value.vat_on_debits,
            operation_category=value.operation_category.value,
            payment_due_rule=value.payment_terms.due_rule.value,
            payment_net_days=value.payment_terms.net_days,
            early_discount_kind=value.early_payment_discount.kind.value,
            early_discount_rate_percent=(
                str(value.early_payment_discount.rate_percent)
                if value.early_payment_discount.rate_percent is not None
                else None
            ),
            early_discount_days_after_issue=(
                value.early_payment_discount.days_after_issue
            ),
            early_discount_mention=value.early_payment_discount_mention,
            late_payment_penalty_annual_rate_percent=str(
                value.late_payment_penalty_annual_rate_percent
            ),
            late_payment_minimum_annual_rate_percent=str(
                value.late_payment_minimum_annual_rate_percent
            ),
            late_payment_legal_policy=value.late_payment_legal_policy,
            recovery_indemnity_policy=value.recovery_indemnity_policy.value,
            recovery_indemnity_currency=value.recovery_indemnity_currency,
            recovery_indemnity_minor_units=str(value.recovery_indemnity_minor_units),
        )


class ExactAmountResponse(BaseModel):
    numerator: str
    denominator: str


class IssuedAllocationResponse(BaseModel):
    position: int
    source_time_entry_id: UUID
    source_start: datetime
    source_end: datetime
    source_billable: bool
    segment_start: datetime
    segment_end: datetime
    business_date: date
    duration_microseconds: str
    exact_amount: ExactAmountResponse

    @classmethod
    def from_domain(cls, value: IssuedInvoiceAllocation) -> "IssuedAllocationResponse":
        return cls(
            position=value.position,
            source_time_entry_id=value.source_time_entry_id,
            source_start=value.source_start,
            source_end=value.source_end,
            source_billable=value.source_billable,
            segment_start=value.segment_start,
            segment_end=value.segment_end,
            business_date=value.business_date,
            duration_microseconds=str(value.duration_microseconds),
            exact_amount=ExactAmountResponse(
                numerator=str(value.exact_amount.numerator),
                denominator=str(value.exact_amount.denominator),
            ),
        )


class IssuedLineResponse(BaseModel):
    position: int
    source_invoice_line_id: UUID
    description: str
    project_id: UUID
    project_name: str
    task_id: UUID | None
    task_name: str | None
    rate_agreement_id: UUID
    rate_scope_project_id: UUID | None
    rate_valid_from: date
    rate_valid_until: date | None
    hourly_rate: str
    duration_microseconds: str
    exact_amount: ExactAmountResponse
    rounded_ht_minor_units: str
    allocations: list[IssuedAllocationResponse]

    @classmethod
    def from_domain(cls, value: IssuedInvoiceLine) -> "IssuedLineResponse":
        return cls(
            position=value.position,
            source_invoice_line_id=value.source_invoice_line_id,
            description=value.description,
            project_id=value.project_id,
            project_name=value.project_name,
            task_id=value.task_id,
            task_name=value.task_name,
            rate_agreement_id=value.rate_agreement_id,
            rate_scope_project_id=value.rate_scope_project_id,
            rate_valid_from=value.rate_valid_from,
            rate_valid_until=value.rate_valid_until,
            hourly_rate=str(value.hourly_rate),
            duration_microseconds=str(value.duration_microseconds),
            exact_amount=ExactAmountResponse(
                numerator=str(value.exact_amount.numerator),
                denominator=str(value.exact_amount.denominator),
            ),
            rounded_ht_minor_units=str(value.rounded_ht.minor_units),
            allocations=[IssuedAllocationResponse.from_domain(item) for item in value.allocations],
        )


class VatBreakdownResponse(BaseModel):
    position: int
    invoice_line_positions: list[int]
    exact_source_ht: ExactAmountResponse
    ht_base_minor_units: str
    vat_rate_percent: str | None
    franchise_legal_basis: str | None
    franchise_invoice_mention: str | None
    exact_vat_amount: ExactAmountResponse
    vat_minor_units: str
    rounding_policy: str

    @classmethod
    def from_domain(cls, value: IssuedVatBreakdown) -> "VatBreakdownResponse":
        return cls(
            position=value.position,
            invoice_line_positions=list(value.invoice_line_positions),
            exact_source_ht=ExactAmountResponse(
                numerator=str(value.exact_source_ht.numerator),
                denominator=str(value.exact_source_ht.denominator),
            ),
            ht_base_minor_units=str(value.ht_base.minor_units),
            vat_rate_percent=(str(value.vat_rate.percent) if value.vat_rate else None),
            franchise_legal_basis=value.franchise_legal_basis,
            franchise_invoice_mention=value.franchise_invoice_mention,
            exact_vat_amount=ExactAmountResponse(
                numerator=str(value.exact_vat_amount.numerator),
                denominator=str(value.exact_vat_amount.denominator),
            ),
            vat_minor_units=str(value.vat_amount.minor_units),
            rounding_policy=value.rounding_policy.value,
        )


class IssuedInvoiceResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    source_invoice_id: UUID
    source_revision: int
    invoice_number: str
    number_series: str
    number_sequence: str
    issued_at: datetime
    billing_timezone: str
    issue_date: date
    service_completion_date: date
    due_date: date
    purchase_order_number: str | None
    currency: str
    currency_decimal_places: int
    line_rounding_policy: str
    vat_rounding_policy: str
    seller: SellerSnapshotResponse
    client: ClientSnapshotResponse
    fiscal_payment: FiscalPaymentSnapshotResponse
    lines: list[IssuedLineResponse]
    vat_breakdowns: list[VatBreakdownResponse]
    exact_source_ht_total: ExactAmountResponse
    ht_total_minor_units: str
    vat_total_minor_units: str
    ttc_total_minor_units: str

    @classmethod
    def from_domain(cls, value: IssuedInvoice) -> "IssuedInvoiceResponse":
        return cls(
            id=value.id,
            workspace_id=value.workspace_id,
            source_invoice_id=value.source_invoice_id,
            source_revision=value.source_revision,
            invoice_number=value.number.value,
            number_series=value.number.series,
            number_sequence=str(value.number.sequence),
            issued_at=value.issued_at,
            billing_timezone=value.billing_timezone,
            issue_date=value.issue_date,
            service_completion_date=value.service_completion_date,
            due_date=value.due_date,
            purchase_order_number=value.purchase_order_number,
            currency=value.currency,
            currency_decimal_places=value.currency_decimal_places,
            line_rounding_policy=value.line_rounding_policy.value,
            vat_rounding_policy=value.vat_breakdowns[0].rounding_policy.value,
            seller=SellerSnapshotResponse.from_domain(value.seller),
            client=ClientSnapshotResponse.from_domain(value.client),
            fiscal_payment=FiscalPaymentSnapshotResponse.from_domain(value.fiscal_payment),
            lines=[IssuedLineResponse.from_domain(item) for item in value.lines],
            vat_breakdowns=[
                VatBreakdownResponse.from_domain(item) for item in value.vat_breakdowns
            ],
            exact_source_ht_total=ExactAmountResponse(
                numerator=str(value.exact_source_ht_total.numerator),
                denominator=str(value.exact_source_ht_total.denominator),
            ),
            ht_total_minor_units=str(value.ht_total.minor_units),
            vat_total_minor_units=str(value.vat_total.minor_units),
            ttc_total_minor_units=str(value.ttc_total.minor_units),
        )


def get_invoice_issuance_service() -> InvoiceIssuanceService:
    raise RuntimeError("InvoiceIssuance service must be supplied by bootstrap")


Service = Annotated[InvoiceIssuanceService, Depends(get_invoice_issuance_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post(
    "/workspaces/{workspace_id}/invoice-drafts/{invoice_id}/issue",
    status_code=201,
    response_model=IssuedInvoiceResponse,
)
def issue_invoice(
    workspace_id: UUID,
    invoice_id: UUID,
    body: IssueInvoiceRequest,
    service: Service,
) -> IssuedInvoiceResponse:
    try:
        value = service.issue(
            workspace_id=workspace_id,
            invoice_id=invoice_id,
            command=body.to_command(),
        )
    except IssuedInvoiceResourceNotFound as error:
        raise _not_found() from error
    except InvoiceIssuanceConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (
        InvoiceIssuanceConfigurationError,
        InvoiceIssuanceError,
        InvoiceDatePolicyError,
        InvoiceTaxError,
    ) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return IssuedInvoiceResponse.from_domain(value)


@router.get(
    "/workspaces/{workspace_id}/issued-invoices/{issued_invoice_id}",
    response_model=IssuedInvoiceResponse,
)
def get_issued_invoice(
    workspace_id: UUID, issued_invoice_id: UUID, service: Service
) -> IssuedInvoiceResponse:
    try:
        value = service.get(workspace_id, issued_invoice_id)
    except IssuedInvoiceResourceNotFound as error:
        raise _not_found() from error
    return IssuedInvoiceResponse.from_domain(value)


@router.get(
    "/workspaces/{workspace_id}/issued-invoices",
    response_model=list[IssuedInvoiceResponse],
)
def list_issued_invoices(
    workspace_id: UUID, service: Service
) -> list[IssuedInvoiceResponse]:
    return [
        IssuedInvoiceResponse.from_domain(value) for value in service.list(workspace_id)
    ]
