"""PostgreSQL persistence for immutable issued-invoice artifacts."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from freelanceflow.modules.billing.adapters.issued_invoice_artifact_models import (
    IssuedInvoiceArtifactRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_models import IssuedInvoiceRow
from freelanceflow.modules.billing.adapters.issued_invoice_repository import (
    IssuedInvoiceRepository,
)
from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    IssuedInvoiceArtifact,
    IssuedInvoiceArtifactMetadata,
    IssuedInvoiceRepresentation,
)
from freelanceflow.modules.billing.domain.issued_invoices import IssuedInvoice


def _metadata(row: IssuedInvoiceArtifactRow) -> IssuedInvoiceArtifactMetadata:
    return IssuedInvoiceArtifactMetadata(
        id=row.id,
        workspace_id=row.workspace_id,
        issued_invoice_id=row.issued_invoice_id,
        representation=IssuedInvoiceRepresentation(row.representation),
        renderer_version=row.renderer_version,
        media_type=row.media_type,
        sha256=row.sha256,
        byte_size=row.byte_size,
        created_at=row.created_at,
    )


class IssuedInvoiceArtifactRepository:
    def __init__(self, session: Session, *, workspace_id: UUID) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.issued_invoices = IssuedInvoiceRepository(
            session, workspace_id=workspace_id
        )

    def lock_issued_invoice(self, issued_invoice_id: UUID) -> IssuedInvoice | None:
        row = self.session.scalar(
            select(IssuedInvoiceRow)
            .where(
                IssuedInvoiceRow.id == issued_invoice_id,
                IssuedInvoiceRow.workspace_id == self.workspace_id,
            )
            .with_for_update()
        )
        return self.issued_invoices.get(issued_invoice_id) if row is not None else None

    def issued_invoice_exists(self, issued_invoice_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(IssuedInvoiceRow.id).where(
                    IssuedInvoiceRow.id == issued_invoice_id,
                    IssuedInvoiceRow.workspace_id == self.workspace_id,
                )
            )
            is not None
        )

    def get_by_generation(
        self,
        issued_invoice_id: UUID,
        representation: IssuedInvoiceRepresentation,
        renderer_version: str,
    ) -> IssuedInvoiceArtifactMetadata | None:
        row = self.session.scalar(
            select(IssuedInvoiceArtifactRow).where(
                IssuedInvoiceArtifactRow.issued_invoice_id == issued_invoice_id,
                IssuedInvoiceArtifactRow.workspace_id == self.workspace_id,
                IssuedInvoiceArtifactRow.representation == representation.value,
                IssuedInvoiceArtifactRow.renderer_version == renderer_version,
            )
        )
        return _metadata(row) if row is not None else None

    def add(self, value: IssuedInvoiceArtifact) -> None:
        metadata = value.metadata
        if metadata.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(
            IssuedInvoiceArtifactRow(
                id=metadata.id,
                workspace_id=metadata.workspace_id,
                issued_invoice_id=metadata.issued_invoice_id,
                representation=metadata.representation.value,
                renderer_version=metadata.renderer_version,
                media_type=metadata.media_type,
                sha256=metadata.sha256,
                byte_size=metadata.byte_size,
                content=value.content,
                created_at=metadata.created_at,
            )
        )
        self.session.flush()

    def list_metadata(
        self, issued_invoice_id: UUID
    ) -> list[IssuedInvoiceArtifactMetadata]:
        rows = self.session.scalars(
            select(IssuedInvoiceArtifactRow)
            .where(
                IssuedInvoiceArtifactRow.issued_invoice_id == issued_invoice_id,
                IssuedInvoiceArtifactRow.workspace_id == self.workspace_id,
            )
            .order_by(
                IssuedInvoiceArtifactRow.representation,
                IssuedInvoiceArtifactRow.renderer_version,
                IssuedInvoiceArtifactRow.id,
            )
        )
        return [_metadata(row) for row in rows]

    def get_metadata(
        self, artifact_id: UUID
    ) -> IssuedInvoiceArtifactMetadata | None:
        row = self.session.scalar(
            select(IssuedInvoiceArtifactRow).where(
                IssuedInvoiceArtifactRow.id == artifact_id,
                IssuedInvoiceArtifactRow.workspace_id == self.workspace_id,
            )
        )
        return _metadata(row) if row is not None else None

    def get(self, artifact_id: UUID) -> IssuedInvoiceArtifact | None:
        row = self.session.scalar(
            select(IssuedInvoiceArtifactRow)
            .options(undefer(IssuedInvoiceArtifactRow.content))
            .where(
                IssuedInvoiceArtifactRow.id == artifact_id,
                IssuedInvoiceArtifactRow.workspace_id == self.workspace_id,
            )
        )
        return (
            IssuedInvoiceArtifact(metadata=_metadata(row), content=row.content)
            if row is not None
            else None
        )
