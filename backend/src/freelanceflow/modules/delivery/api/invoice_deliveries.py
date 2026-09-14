"""Workspace-scoped public HTTP boundary for durable invoice deliveries."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from freelanceflow.modules.delivery.application.invoice_deliveries import (
    InvoiceDeliveryResourceNotFound,
    InvoiceDeliveryService,
)
from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    InvoiceDelivery,
    InvoiceDeliveryAttempt,
    InvoiceDeliveryAttemptOutcome,
    InvoiceDeliveryState,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["invoice-deliveries"])


class InvoiceDeliveryAttemptResponse(BaseModel):
    id: UUID
    sequence: int
    started_at: datetime
    completed_at: datetime | None
    outcome: InvoiceDeliveryAttemptOutcome | None
    failure_reason: str | None

    @classmethod
    def from_attempt(cls, value: InvoiceDeliveryAttempt) -> "InvoiceDeliveryAttemptResponse":
        return cls(
            id=value.id,
            sequence=value.sequence,
            started_at=value.started_at,
            completed_at=value.completed_at,
            outcome=value.outcome,
            failure_reason=value.failure_reason,
        )


class InvoiceDeliveryResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    approval_id: UUID
    invoice_id: UUID
    invoice_revision: int
    artifact_id: UUID
    artifact_sha256: str
    state: InvoiceDeliveryState
    requested_at: datetime
    active_attempt_id: UUID | None
    sent_at: datetime | None
    attempts: list[InvoiceDeliveryAttemptResponse]

    @classmethod
    def from_delivery(cls, value: InvoiceDelivery) -> "InvoiceDeliveryResponse":
        return cls(
            id=value.id,
            workspace_id=value.workspace_id,
            approval_id=value.approval_id,
            invoice_id=value.invoice_id,
            invoice_revision=value.invoice_revision,
            artifact_id=value.artifact_id,
            artifact_sha256=value.artifact_sha256,
            state=value.state,
            requested_at=value.requested_at,
            active_attempt_id=value.active_attempt_id,
            sent_at=value.sent_at,
            attempts=[
                InvoiceDeliveryAttemptResponse.from_attempt(attempt) for attempt in value.attempts
            ],
        )


def get_invoice_delivery_service() -> InvoiceDeliveryService:
    raise RuntimeError("InvoiceDelivery service must be supplied by bootstrap")


Service = Annotated[InvoiceDeliveryService, Depends(get_invoice_delivery_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post(
    "/invoice-drafts/{invoice_id}/revisions/{revision}/artifacts/{artifact_id}/delivery",
    response_model=InvoiceDeliveryResponse,
)
async def request_invoice_delivery(
    workspace_id: UUID,
    invoice_id: UUID,
    revision: int,
    artifact_id: UUID,
    request: Request,
    service: Service,
) -> InvoiceDeliveryResponse:
    if await request.body():
        raise HTTPException(
            status_code=422,
            detail="Invoice delivery does not accept caller-supplied metadata",
        )
    try:
        delivery = service.request(
            workspace_id=workspace_id,
            invoice_id=invoice_id,
            revision=revision,
            artifact_id=artifact_id,
        )
    except InvoiceDeliveryResourceNotFound as error:
        raise _not_found() from error
    return InvoiceDeliveryResponse.from_delivery(delivery)


@router.get("/invoice-deliveries/{delivery_id}", response_model=InvoiceDeliveryResponse)
def get_invoice_delivery(
    workspace_id: UUID, delivery_id: UUID, service: Service
) -> InvoiceDeliveryResponse:
    try:
        delivery = service.get(workspace_id, delivery_id)
    except InvoiceDeliveryResourceNotFound as error:
        raise _not_found() from error
    return InvoiceDeliveryResponse.from_delivery(delivery)
