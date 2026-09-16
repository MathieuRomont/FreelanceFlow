"""Workspace-scoped HTTP boundary for immutable final invoice approval."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from freelanceflow.modules.billing.application.issued_invoice_approvals import (
    IssuedInvoiceApprovalConflictError,
    IssuedInvoiceApprovalResourceNotFound,
    IssuedInvoiceApprovalService,
)
from freelanceflow.modules.billing.domain.issued_invoice_approvals import (
    IssuedInvoiceApproval,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["issued-invoice-approvals"])


class IssuedInvoiceApprovalResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    issued_invoice_id: UUID
    issued_invoice_artifact_id: UUID
    artifact_sha256: str
    representation: str
    renderer_version: str
    approved_at: datetime

    @classmethod
    def from_approval(cls, value: IssuedInvoiceApproval) -> "IssuedInvoiceApprovalResponse":
        return cls(
            id=value.id,
            workspace_id=value.workspace_id,
            issued_invoice_id=value.issued_invoice_id,
            issued_invoice_artifact_id=value.issued_invoice_artifact_id,
            artifact_sha256=value.artifact_sha256,
            representation=value.representation.value,
            renderer_version=value.renderer_version,
            approved_at=value.approved_at,
        )


def get_issued_invoice_approval_service() -> IssuedInvoiceApprovalService:
    raise RuntimeError("IssuedInvoiceApproval service must be supplied by bootstrap")


Service = Annotated[IssuedInvoiceApprovalService, Depends(get_issued_invoice_approval_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post(
    "/issued-invoices/{issued_invoice_id}/artifacts/{artifact_id}/approval",
    response_model=IssuedInvoiceApprovalResponse,
)
async def approve_issued_invoice_artifact(
    workspace_id: UUID,
    issued_invoice_id: UUID,
    artifact_id: UUID,
    request: Request,
    service: Service,
) -> IssuedInvoiceApprovalResponse:
    if await request.body():
        raise HTTPException(
            status_code=422,
            detail="Issued invoice approval does not accept caller-supplied metadata",
        )
    try:
        approval = service.approve(
            workspace_id=workspace_id,
            issued_invoice_id=issued_invoice_id,
            artifact_id=artifact_id,
        )
    except IssuedInvoiceApprovalResourceNotFound as error:
        raise _not_found() from error
    except IssuedInvoiceApprovalConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return IssuedInvoiceApprovalResponse.from_approval(approval)


@router.get(
    "/issued-invoices/{issued_invoice_id}/approval",
    response_model=IssuedInvoiceApprovalResponse,
)
def get_issued_invoice_approval(
    workspace_id: UUID,
    issued_invoice_id: UUID,
    service: Service,
) -> IssuedInvoiceApprovalResponse:
    try:
        approval = service.get(workspace_id, issued_invoice_id)
    except IssuedInvoiceApprovalResourceNotFound as error:
        raise _not_found() from error
    return IssuedInvoiceApprovalResponse.from_approval(approval)
