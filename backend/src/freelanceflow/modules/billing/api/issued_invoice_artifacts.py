"""Workspace-scoped HTTP boundary for immutable issued-invoice artifacts."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from freelanceflow.modules.billing.application.issued_invoice_artifacts import (
    IssuedInvoiceArtifactResourceNotFound,
    IssuedInvoiceArtifactService,
)
from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    IssuedInvoiceArtifactError,
    IssuedInvoiceArtifactMetadata,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["issued-invoice-artifacts"])


class IssuedInvoiceArtifactMetadataResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    issued_invoice_id: UUID
    representation: str
    renderer_version: str
    media_type: str
    sha256: str
    byte_size: int
    created_at: datetime

    @classmethod
    def from_metadata(
        cls, value: IssuedInvoiceArtifactMetadata
    ) -> "IssuedInvoiceArtifactMetadataResponse":
        return cls(
            id=value.id,
            workspace_id=value.workspace_id,
            issued_invoice_id=value.issued_invoice_id,
            representation=value.representation.value,
            renderer_version=value.renderer_version,
            media_type=value.media_type,
            sha256=value.sha256,
            byte_size=value.byte_size,
            created_at=value.created_at,
        )


def get_issued_invoice_artifact_service() -> IssuedInvoiceArtifactService:
    raise RuntimeError("IssuedInvoiceArtifact service must be supplied by bootstrap")


Service = Annotated[
    IssuedInvoiceArtifactService, Depends(get_issued_invoice_artifact_service)
]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post(
    "/issued-invoices/{issued_invoice_id}/artifacts",
    status_code=201,
    response_model=IssuedInvoiceArtifactMetadataResponse,
)
def generate_issued_invoice_artifact(
    workspace_id: UUID,
    issued_invoice_id: UUID,
    service: Service,
) -> IssuedInvoiceArtifactMetadataResponse:
    try:
        metadata = service.generate_pdf(
            workspace_id=workspace_id, issued_invoice_id=issued_invoice_id
        )
    except IssuedInvoiceArtifactResourceNotFound as error:
        raise _not_found() from error
    except IssuedInvoiceArtifactError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return IssuedInvoiceArtifactMetadataResponse.from_metadata(metadata)


@router.get(
    "/issued-invoices/{issued_invoice_id}/artifacts",
    response_model=list[IssuedInvoiceArtifactMetadataResponse],
)
def list_issued_invoice_artifacts(
    workspace_id: UUID,
    issued_invoice_id: UUID,
    service: Service,
) -> list[IssuedInvoiceArtifactMetadataResponse]:
    try:
        metadata = service.list_metadata(workspace_id, issued_invoice_id)
    except IssuedInvoiceArtifactResourceNotFound as error:
        raise _not_found() from error
    return [
        IssuedInvoiceArtifactMetadataResponse.from_metadata(value)
        for value in metadata
    ]


@router.get(
    "/issued-invoice-artifacts/{artifact_id}",
    response_model=IssuedInvoiceArtifactMetadataResponse,
)
def get_issued_invoice_artifact_metadata(
    workspace_id: UUID,
    artifact_id: UUID,
    service: Service,
) -> IssuedInvoiceArtifactMetadataResponse:
    try:
        metadata = service.get_metadata(workspace_id, artifact_id)
    except IssuedInvoiceArtifactResourceNotFound as error:
        raise _not_found() from error
    return IssuedInvoiceArtifactMetadataResponse.from_metadata(metadata)


@router.get("/issued-invoice-artifacts/{artifact_id}/content")
def get_issued_invoice_artifact_content(
    workspace_id: UUID,
    artifact_id: UUID,
    service: Service,
) -> Response:
    try:
        artifact = service.get_content(workspace_id, artifact_id)
    except IssuedInvoiceArtifactResourceNotFound as error:
        raise _not_found() from error
    return Response(
        content=artifact.content,
        headers={"Content-Type": artifact.metadata.media_type},
    )
