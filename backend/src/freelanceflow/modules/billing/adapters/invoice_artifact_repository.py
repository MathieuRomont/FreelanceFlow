"""PostgreSQL persistence for immutable frozen invoice artifacts."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.models import (
    InvoiceArtifactRow,
    InvoiceDraftRow,
)
from freelanceflow.modules.billing.domain.invoice_artifacts import (
    InvoiceArtifact,
    InvoiceArtifactMetadata,
)


def _metadata(row: InvoiceArtifactRow) -> InvoiceArtifactMetadata:
    return InvoiceArtifactMetadata(
        id=row.id,
        workspace_id=row.workspace_id,
        invoice_id=row.invoice_draft_id,
        invoice_revision=row.invoice_revision,
        media_type=row.media_type,
        sha256=row.sha256,
        byte_size=row.byte_size,
        created_at=row.created_at,
    )


class InvoiceArtifactRepository:
    def __init__(self, session: Session, *, workspace_id: UUID) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def revision_exists(self, invoice_id: UUID, revision: int) -> bool:
        return (
            self.session.scalar(
                select(InvoiceDraftRow.id).where(
                    InvoiceDraftRow.id == invoice_id,
                    InvoiceDraftRow.revision == revision,
                    InvoiceDraftRow.workspace_id == self.workspace_id,
                )
            )
            is not None
        )

    def add(self, value: InvoiceArtifact) -> None:
        metadata = value.metadata
        if metadata.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(
            InvoiceArtifactRow(
                id=metadata.id,
                workspace_id=metadata.workspace_id,
                invoice_draft_id=metadata.invoice_id,
                invoice_revision=metadata.invoice_revision,
                media_type=metadata.media_type,
                sha256=metadata.sha256,
                byte_size=metadata.byte_size,
                content=value.content,
                created_at=metadata.created_at,
            )
        )
        self.session.flush()

    def list_metadata(self, invoice_id: UUID, revision: int) -> list[InvoiceArtifactMetadata]:
        rows = self.session.scalars(
            select(InvoiceArtifactRow)
            .where(
                InvoiceArtifactRow.workspace_id == self.workspace_id,
                InvoiceArtifactRow.invoice_draft_id == invoice_id,
                InvoiceArtifactRow.invoice_revision == revision,
            )
            .order_by(InvoiceArtifactRow.created_at, InvoiceArtifactRow.id)
        )
        return [_metadata(row) for row in rows]

    def get_metadata(self, artifact_id: UUID) -> InvoiceArtifactMetadata | None:
        row = self.session.scalar(
            select(InvoiceArtifactRow).where(
                InvoiceArtifactRow.id == artifact_id,
                InvoiceArtifactRow.workspace_id == self.workspace_id,
            )
        )
        return _metadata(row) if row is not None else None

    def get(self, artifact_id: UUID) -> InvoiceArtifact | None:
        row = self.session.scalar(
            select(InvoiceArtifactRow).where(
                InvoiceArtifactRow.id == artifact_id,
                InvoiceArtifactRow.workspace_id == self.workspace_id,
            )
        )
        return (
            InvoiceArtifact(metadata=_metadata(row), content=row.content)
            if row is not None
            else None
        )
