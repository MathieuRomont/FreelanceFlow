"""Workspace-scoped InvoiceDraft HTTP boundary."""

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from freelanceflow.modules.billing.application.invoice_drafts import (
    InvoiceAllocationInput,
    InvoiceDraftAlreadyIssuedError,
    InvoiceDraftIdentityChangeError,
    InvoiceDraftResourceNotFound,
    InvoiceDraftService,
    InvoiceLineConstructionInput,
)
from freelanceflow.modules.billing.domain import RateError
from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceAllocation,
    InvoiceDraft,
    InvoiceDraftError,
    InvoiceLine,
)
from freelanceflow.modules.billing.domain.pricing import BillingCalculationError

router = APIRouter(
    prefix="/workspaces/{workspace_id}/invoice-drafts", tags=["invoice-drafts"]
)


class CreateInvoiceAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_entry_id: UUID
    start: AwareDatetime
    end: AwareDatetime
    business_date: date

    @field_validator("start", "end", mode="before")
    @classmethod
    def require_iso_string(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("Timestamp must be an offset-aware ISO-8601 string")
        return value


class CreateInvoiceLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocations: list[CreateInvoiceAllocationRequest]


class CreateInvoiceDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    lines: list[CreateInvoiceLineRequest]


class CreateInvoiceRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[CreateInvoiceLineRequest]


class ExactMoneyResponse(BaseModel):
    numerator: str
    denominator: str


class InvoiceAllocationResponse(BaseModel):
    source_time_entry_id: UUID
    source_start: datetime
    source_end: datetime
    source_billable: bool
    start: datetime
    end: datetime
    business_date: date
    duration_microseconds: str
    exact_amount: ExactMoneyResponse

    @classmethod
    def from_allocation(cls, value: InvoiceAllocation) -> "InvoiceAllocationResponse":
        priced = value.priced_segment
        source = priced.segment.source_time_entry
        return cls(
            source_time_entry_id=source.id,
            source_start=source.start,
            source_end=source.end,
            source_billable=source.billable,
            start=priced.segment.start,
            end=priced.segment.end,
            business_date=priced.segment.business_date,
            duration_microseconds=str(priced.duration_microseconds),
            exact_amount=ExactMoneyResponse(
                numerator=str(priced.exact_amount.numerator),
                denominator=str(priced.exact_amount.denominator),
            ),
        )


class InvoiceLineResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    client_id: UUID
    project_id: UUID
    task_id: UUID | None
    rate_agreement_id: UUID
    hourly_amount: str
    currency: str
    currency_decimal_places: int
    duration_microseconds: str
    exact_amount: ExactMoneyResponse
    rounded_minor_units: str
    allocations: list[InvoiceAllocationResponse]

    @classmethod
    def from_line(cls, value: InvoiceLine) -> "InvoiceLineResponse":
        return cls(
            id=value.id,
            workspace_id=value.workspace_id,
            client_id=value.client_id,
            project_id=value.project_id,
            task_id=value.task_id,
            rate_agreement_id=value.applied_rate_agreement_id,
            hourly_amount=str(value.hourly_rate),
            currency=value.currency.code,
            currency_decimal_places=value.currency.decimal_places,
            duration_microseconds=str(value.duration_microseconds),
            exact_amount=ExactMoneyResponse(
                numerator=str(value.exact_amount.numerator),
                denominator=str(value.exact_amount.denominator),
            ),
            rounded_minor_units=str(value.rounded_amount.minor_units),
            allocations=[
                InvoiceAllocationResponse.from_allocation(allocation)
                for allocation in value.allocations
            ],
        )


class InvoiceDraftResponse(BaseModel):
    id: UUID
    revision: int
    workspace_id: UUID
    client_id: UUID
    currency: str
    currency_decimal_places: int
    exact_subtotal: ExactMoneyResponse
    subtotal_minor_units: str
    total_minor_units: str
    lines: list[InvoiceLineResponse]

    @classmethod
    def from_draft(cls, value: InvoiceDraft) -> "InvoiceDraftResponse":
        return cls(
            id=value.id,
            revision=value.revision,
            workspace_id=value.workspace_id,
            client_id=value.client_id,
            currency=value.currency.code,
            currency_decimal_places=value.currency.decimal_places,
            exact_subtotal=ExactMoneyResponse(
                numerator=str(value.exact_subtotal.numerator),
                denominator=str(value.exact_subtotal.denominator),
            ),
            subtotal_minor_units=str(value.subtotal.minor_units),
            total_minor_units=str(value.total.minor_units),
            lines=[InvoiceLineResponse.from_line(line) for line in value.lines],
        )


def get_invoice_draft_service() -> InvoiceDraftService:
    raise RuntimeError("InvoiceDraft service must be supplied by bootstrap")


Service = Annotated[InvoiceDraftService, Depends(get_invoice_draft_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


def _line_inputs(
    lines: list[CreateInvoiceLineRequest],
) -> tuple[InvoiceLineConstructionInput, ...]:
    return tuple(
        InvoiceLineConstructionInput(
            allocations=tuple(
                InvoiceAllocationInput(
                    time_entry_id=allocation.time_entry_id,
                    start=allocation.start,
                    end=allocation.end,
                    business_date=allocation.business_date,
                )
                for allocation in line.allocations
            )
        )
        for line in lines
    )


@router.post("", status_code=201, response_model=InvoiceDraftResponse)
def create_invoice_draft(
    workspace_id: UUID, body: CreateInvoiceDraftRequest, service: Service
) -> InvoiceDraftResponse:
    try:
        draft = service.create(
            workspace_id=workspace_id,
            client_id=body.client_id,
            lines=_line_inputs(body.lines),
        )
    except InvoiceDraftResourceNotFound as error:
        raise _not_found() from error
    except (InvoiceDraftError, BillingCalculationError, RateError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return InvoiceDraftResponse.from_draft(draft)


@router.post(
    "/{invoice_draft_id}/revisions",
    status_code=201,
    response_model=InvoiceDraftResponse,
)
def create_invoice_draft_revision(
    workspace_id: UUID,
    invoice_draft_id: UUID,
    body: CreateInvoiceRevisionRequest,
    service: Service,
) -> InvoiceDraftResponse:
    try:
        draft = service.create_revision(
            workspace_id=workspace_id,
            draft_id=invoice_draft_id,
            lines=_line_inputs(body.lines),
        )
    except InvoiceDraftResourceNotFound as error:
        raise _not_found() from error
    except (
        InvoiceDraftAlreadyIssuedError,
        InvoiceDraftIdentityChangeError,
        InvoiceDraftError,
        BillingCalculationError,
        RateError,
    ) as error:
        status_code = 409 if isinstance(error, InvoiceDraftAlreadyIssuedError) else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return InvoiceDraftResponse.from_draft(draft)


@router.get("", response_model=list[InvoiceDraftResponse])
def list_invoice_drafts(
    workspace_id: UUID, service: Service
) -> list[InvoiceDraftResponse]:
    return [InvoiceDraftResponse.from_draft(value) for value in service.list(workspace_id)]


@router.get(
    "/{invoice_draft_id}/revisions", response_model=list[InvoiceDraftResponse]
)
def list_invoice_draft_revisions(
    workspace_id: UUID, invoice_draft_id: UUID, service: Service
) -> list[InvoiceDraftResponse]:
    try:
        revisions = service.list_revisions(workspace_id, invoice_draft_id)
    except InvoiceDraftResourceNotFound as error:
        raise _not_found() from error
    return [InvoiceDraftResponse.from_draft(value) for value in revisions]


@router.get(
    "/{invoice_draft_id}/revisions/{revision}", response_model=InvoiceDraftResponse
)
def get_invoice_draft_revision(
    workspace_id: UUID,
    invoice_draft_id: UUID,
    revision: int,
    service: Service,
) -> InvoiceDraftResponse:
    try:
        draft = service.get_revision(workspace_id, invoice_draft_id, revision)
    except InvoiceDraftResourceNotFound as error:
        raise _not_found() from error
    return InvoiceDraftResponse.from_draft(draft)


@router.get("/{invoice_draft_id}", response_model=InvoiceDraftResponse)
def get_invoice_draft(
    workspace_id: UUID, invoice_draft_id: UUID, service: Service
) -> InvoiceDraftResponse:
    try:
        draft = service.get(workspace_id, invoice_draft_id)
    except InvoiceDraftResourceNotFound as error:
        raise _not_found() from error
    return InvoiceDraftResponse.from_draft(draft)
