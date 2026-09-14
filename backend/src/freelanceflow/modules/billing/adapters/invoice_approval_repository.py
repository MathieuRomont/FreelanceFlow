"""PostgreSQL persistence for immutable invoice approvals."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.models import (
    InvoiceApprovalRow,
    InvoiceArtifactRow,
    InvoiceDraftRow,
)
from freelanceflow.modules.billing.domain.invoice_approvals import InvoiceApproval
from freelanceflow.modules.billing.domain.invoice_artifacts import InvoiceArtifactMetadata


def _approval(row: InvoiceApprovalRow) -> InvoiceApproval:
    return InvoiceApproval(
        id=row.id,
        workspace_id=row.workspace_id,
        invoice_id=row.invoice_draft_id,
        invoice_revision=row.invoice_revision,
        artifact_id=row.artifact_id,
        artifact_sha256=row.artifact_sha256,
        approved_at=row.approved_at,
    )


def _artifact_metadata(row: InvoiceArtifactRow) -> InvoiceArtifactMetadata:
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


class InvoiceApprovalRepository:
    def __init__(self, session: Session, *, workspace_id: UUID) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def lock_revision(self, invoice_id: UUID, revision: int) -> bool:
        return (
            self.session.scalar(
                select(InvoiceDraftRow.id)
                .where(
                    InvoiceDraftRow.id == invoice_id,
                    InvoiceDraftRow.revision == revision,
                    InvoiceDraftRow.workspace_id == self.workspace_id,
                )
                .with_for_update()
            )
            is not None
        )

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

    def get_artifact_for_revision(
        self, invoice_id: UUID, revision: int, artifact_id: UUID
    ) -> InvoiceArtifactMetadata | None:
        row = self.session.scalar(
            select(InvoiceArtifactRow).where(
                InvoiceArtifactRow.id == artifact_id,
                InvoiceArtifactRow.workspace_id == self.workspace_id,
                InvoiceArtifactRow.invoice_draft_id == invoice_id,
                InvoiceArtifactRow.invoice_revision == revision,
            )
        )
        return _artifact_metadata(row) if row is not None else None

    def get(self, invoice_id: UUID, revision: int) -> InvoiceApproval | None:
        row = self.session.scalar(
            select(InvoiceApprovalRow).where(
                InvoiceApprovalRow.workspace_id == self.workspace_id,
                InvoiceApprovalRow.invoice_draft_id == invoice_id,
                InvoiceApprovalRow.invoice_revision == revision,
            )
        )
        return _approval(row) if row is not None else None

    def add(self, value: InvoiceApproval) -> None:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(
            InvoiceApprovalRow(
                id=value.id,
                workspace_id=value.workspace_id,
                invoice_draft_id=value.invoice_id,
                invoice_revision=value.invoice_revision,
                artifact_id=value.artifact_id,
                artifact_sha256=value.artifact_sha256,
                approved_at=value.approved_at,
            )
        )
        self.session.flush()
