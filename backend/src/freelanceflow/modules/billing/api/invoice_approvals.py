"""Workspace-scoped HTTP boundary for immutable invoice approval."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from freelanceflow.modules.billing.application.invoice_approvals import (
    InvoiceApprovalConflictError,
    InvoiceApprovalResourceNotFound,
    InvoiceApprovalService,
)
from freelanceflow.modules.billing.domain.invoice_approvals import InvoiceApproval

router = APIRouter(
    prefix="/workspaces/{workspace_id}/invoice-drafts",
    tags=["invoice-approvals"],
)


class InvoiceApprovalResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    invoice_id: UUID
    invoice_revision: int
    artifact_id: UUID
    artifact_sha256: str
    approved_at: datetime

    @classmethod
    def from_approval(cls, value: InvoiceApproval) -> "InvoiceApprovalResponse":
        return cls(
            id=value.id,
            workspace_id=value.workspace_id,
            invoice_id=value.invoice_id,
            invoice_revision=value.invoice_revision,
            artifact_id=value.artifact_id,
            artifact_sha256=value.artifact_sha256,
            approved_at=value.approved_at,
        )


def get_invoice_approval_service() -> InvoiceApprovalService:
    raise RuntimeError("InvoiceApproval service must be supplied by bootstrap")


Service = Annotated[InvoiceApprovalService, Depends(get_invoice_approval_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post(
    "/{invoice_id}/revisions/{revision}/artifacts/{artifact_id}/approval",
    response_model=InvoiceApprovalResponse,
)
async def approve_invoice_artifact(
    workspace_id: UUID,
    invoice_id: UUID,
    revision: int,
    artifact_id: UUID,
    request: Request,
    service: Service,
) -> InvoiceApprovalResponse:
    if await request.body():
        raise HTTPException(
            status_code=422,
            detail="Invoice approval does not accept caller-supplied metadata",
        )
    try:
        approval = service.approve(
            workspace_id=workspace_id,
            invoice_id=invoice_id,
            revision=revision,
            artifact_id=artifact_id,
        )
    except InvoiceApprovalResourceNotFound as error:
        raise _not_found() from error
    except InvoiceApprovalConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return InvoiceApprovalResponse.from_approval(approval)


@router.get(
    "/{invoice_id}/revisions/{revision}/approval",
    response_model=InvoiceApprovalResponse,
)
def get_invoice_approval(
    workspace_id: UUID,
    invoice_id: UUID,
    revision: int,
    service: Service,
) -> InvoiceApprovalResponse:
    try:
        approval = service.get(workspace_id, invoice_id, revision)
    except InvoiceApprovalResourceNotFound as error:
        raise _not_found() from error
    return InvoiceApprovalResponse.from_approval(approval)
