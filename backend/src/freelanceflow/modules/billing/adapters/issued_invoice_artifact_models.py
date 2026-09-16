"""PostgreSQL row for immutable issued-invoice representations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class IssuedInvoiceArtifactRow(Base):
    __tablename__ = "issued_invoice_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
        ),
        UniqueConstraint(
            "issued_invoice_id",
            "representation",
            "renderer_version",
            name="uq_issued_invoice_artifacts_canonical_generation",
        ),
        UniqueConstraint(
            "id",
            "issued_invoice_id",
            "workspace_id",
            "sha256",
            name="uq_issued_invoice_artifacts_integrity_identity",
        ),
        UniqueConstraint(
            "id",
            "issued_invoice_id",
            "workspace_id",
            "sha256",
            "representation",
            "renderer_version",
            name="uq_issued_invoice_artifacts_approval_identity",
        ),
        CheckConstraint("representation = 'pdf'", name="supported_representation"),
        CheckConstraint("media_type = 'application/pdf'", name="supported_media_type"),
        CheckConstraint(
            "length(btrim(renderer_version)) > 0", name="nonblank_renderer_version"
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="canonical_sha256"),
        CheckConstraint(
            "byte_size > 0 AND octet_length(content) = byte_size",
            name="consistent_nonempty_content_size",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    issued_invoice_id: Mapped[UUID]
    representation: Mapped[str]
    renderer_version: Mapped[str]
    media_type: Mapped[str]
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
