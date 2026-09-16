"""PostgreSQL persistence for immutable final issued-invoice approvals."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.issued_invoice_approval_models import (
    IssuedInvoiceApprovalRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_artifact_models import (
    IssuedInvoiceArtifactRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_models import IssuedInvoiceRow
from freelanceflow.modules.billing.domain.issued_invoice_approvals import (
    IssuedInvoiceApproval,
)
from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    IssuedInvoiceArtifactMetadata,
    IssuedInvoiceRepresentation,
)


def _approval(row: IssuedInvoiceApprovalRow) -> IssuedInvoiceApproval:
    return IssuedInvoiceApproval(
        id=row.id,
        workspace_id=row.workspace_id,
        issued_invoice_id=row.issued_invoice_id,
        issued_invoice_artifact_id=row.issued_invoice_artifact_id,
        artifact_sha256=row.artifact_sha256,
        representation=IssuedInvoiceRepresentation(row.representation),
        renderer_version=row.renderer_version,
        approved_at=row.approved_at,
    )


def _artifact(row: IssuedInvoiceArtifactRow) -> IssuedInvoiceArtifactMetadata:
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


class IssuedInvoiceApprovalRepository:
    def __init__(self, session: Session, *, workspace_id: UUID) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def lock_issued_invoice(self, issued_invoice_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(IssuedInvoiceRow.id)
                .where(
                    IssuedInvoiceRow.id == issued_invoice_id,
                    IssuedInvoiceRow.workspace_id == self.workspace_id,
                )
                .with_for_update()
            )
            is not None
        )

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

    def get_artifact(
        self, issued_invoice_id: UUID, artifact_id: UUID
    ) -> IssuedInvoiceArtifactMetadata | None:
        row = self.session.scalar(
            select(IssuedInvoiceArtifactRow).where(
                IssuedInvoiceArtifactRow.id == artifact_id,
                IssuedInvoiceArtifactRow.issued_invoice_id == issued_invoice_id,
                IssuedInvoiceArtifactRow.workspace_id == self.workspace_id,
            )
        )
        return _artifact(row) if row is not None else None

    def get(self, issued_invoice_id: UUID) -> IssuedInvoiceApproval | None:
        row = self.session.scalar(
            select(IssuedInvoiceApprovalRow).where(
                IssuedInvoiceApprovalRow.issued_invoice_id == issued_invoice_id,
                IssuedInvoiceApprovalRow.workspace_id == self.workspace_id,
            )
        )
        return _approval(row) if row is not None else None

    def add(self, value: IssuedInvoiceApproval) -> None:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(
            IssuedInvoiceApprovalRow(
                id=value.id,
                workspace_id=value.workspace_id,
                issued_invoice_id=value.issued_invoice_id,
                issued_invoice_artifact_id=value.issued_invoice_artifact_id,
                artifact_sha256=value.artifact_sha256,
                representation=value.representation.value,
                renderer_version=value.renderer_version,
                approved_at=value.approved_at,
            )
        )
        self.session.flush()
