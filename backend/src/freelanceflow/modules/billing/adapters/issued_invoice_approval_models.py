"""PostgreSQL row for immutable final issued-invoice approvals."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class IssuedInvoiceApprovalRow(Base):
    __tablename__ = "issued_invoice_approvals"
    __table_args__ = (
        UniqueConstraint(
            "issued_invoice_id",
            name="uq_issued_invoice_approvals_one_per_invoice",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            "issued_invoice_id",
            "issued_invoice_artifact_id",
            "artifact_sha256",
            "representation",
            "renderer_version",
            name="uq_issued_invoice_approvals_target_identity",
        ),
        ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
        ),
        ForeignKeyConstraint(
            [
                "issued_invoice_artifact_id",
                "issued_invoice_id",
                "workspace_id",
                "artifact_sha256",
                "representation",
                "renderer_version",
            ],
            [
                "issued_invoice_artifacts.id",
                "issued_invoice_artifacts.issued_invoice_id",
                "issued_invoice_artifacts.workspace_id",
                "issued_invoice_artifacts.sha256",
                "issued_invoice_artifacts.representation",
                "issued_invoice_artifacts.renderer_version",
            ],
        ),
        CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="canonical_artifact_sha256",
        ),
        CheckConstraint("representation = 'pdf'", name="supported_representation"),
        CheckConstraint(
            "length(btrim(renderer_version)) > 0",
            name="nonblank_renderer_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    issued_invoice_id: Mapped[UUID]
    issued_invoice_artifact_id: Mapped[UUID]
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    representation: Mapped[str]
    renderer_version: Mapped[str]
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
