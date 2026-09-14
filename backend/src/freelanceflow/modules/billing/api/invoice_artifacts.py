"""Workspace-scoped HTTP boundary for frozen invoice artifacts."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from freelanceflow.modules.billing.application.invoice_artifacts import (
    InvoiceArtifactResourceNotFound,
    InvoiceArtifactService,
)
from freelanceflow.modules.billing.domain.invoice_artifacts import (
    InvoiceArtifactError,
    InvoiceArtifactMetadata,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["invoice-artifacts"])


class InvoiceArtifactMetadataResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    invoice_id: UUID
    invoice_revision: int
    media_type: str
    sha256: str
    byte_size: int
    created_at: datetime

    @classmethod
    def from_metadata(cls, value: InvoiceArtifactMetadata) -> "InvoiceArtifactMetadataResponse":
        return cls(
            id=value.id,
            workspace_id=value.workspace_id,
            invoice_id=value.invoice_id,
            invoice_revision=value.invoice_revision,
            media_type=value.media_type,
            sha256=value.sha256,
            byte_size=value.byte_size,
            created_at=value.created_at,
        )


def get_invoice_artifact_service() -> InvoiceArtifactService:
    raise RuntimeError("InvoiceArtifact service must be supplied by bootstrap")


Service = Annotated[InvoiceArtifactService, Depends(get_invoice_artifact_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post(
    "/invoice-drafts/{invoice_id}/revisions/{revision}/artifacts",
    status_code=201,
    response_model=InvoiceArtifactMetadataResponse,
)
async def create_invoice_artifact(
    workspace_id: UUID,
    invoice_id: UUID,
    revision: int,
    request: Request,
    service: Service,
) -> InvoiceArtifactMetadataResponse:
    content = await request.body()
    media_type = request.headers.get("content-type", "")
    try:
        metadata = service.create(
            workspace_id=workspace_id,
            invoice_id=invoice_id,
            revision=revision,
            media_type=media_type,
            content=content,
        )
    except InvoiceArtifactResourceNotFound as error:
        raise _not_found() from error
    except InvoiceArtifactError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return InvoiceArtifactMetadataResponse.from_metadata(metadata)


@router.get(
    "/invoice-drafts/{invoice_id}/revisions/{revision}/artifacts",
    response_model=list[InvoiceArtifactMetadataResponse],
)
def list_invoice_artifacts(
    workspace_id: UUID,
    invoice_id: UUID,
    revision: int,
    service: Service,
) -> list[InvoiceArtifactMetadataResponse]:
    try:
        metadata = service.list_metadata(workspace_id, invoice_id, revision)
    except InvoiceArtifactResourceNotFound as error:
        raise _not_found() from error
    return [InvoiceArtifactMetadataResponse.from_metadata(value) for value in metadata]


@router.get(
    "/invoice-artifacts/{artifact_id}",
    response_model=InvoiceArtifactMetadataResponse,
)
def get_invoice_artifact_metadata(
    workspace_id: UUID, artifact_id: UUID, service: Service
) -> InvoiceArtifactMetadataResponse:
    try:
        metadata = service.get_metadata(workspace_id, artifact_id)
    except InvoiceArtifactResourceNotFound as error:
        raise _not_found() from error
    return InvoiceArtifactMetadataResponse.from_metadata(metadata)


@router.get("/invoice-artifacts/{artifact_id}/content")
def get_invoice_artifact_content(
    workspace_id: UUID, artifact_id: UUID, service: Service
) -> Response:
    try:
        artifact = service.get_content(workspace_id, artifact_id)
    except InvoiceArtifactResourceNotFound as error:
        raise _not_found() from error
    return Response(
        content=artifact.content,
        headers={"Content-Type": artifact.metadata.media_type},
    )
