"""Add immutable deterministic artifacts for legally issued invoices."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issued_invoice_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("issued_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("representation", sa.String(), nullable=False),
        sa.Column("renderer_version", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_issued_invoice_artifacts_canonical_sha256"),
        ),
        sa.CheckConstraint(
            "byte_size > 0 AND octet_length(content) = byte_size",
            name=op.f(
                "ck_issued_invoice_artifacts_consistent_nonempty_content_size"
            ),
        ),
        sa.CheckConstraint(
            "length(btrim(renderer_version)) > 0",
            name=op.f("ck_issued_invoice_artifacts_nonblank_renderer_version"),
        ),
        sa.CheckConstraint(
            "media_type = 'application/pdf'",
            name=op.f("ck_issued_invoice_artifacts_supported_media_type"),
        ),
        sa.CheckConstraint(
            "representation = 'pdf'",
            name=op.f("ck_issued_invoice_artifacts_supported_representation"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
            name=op.f(
                "fk_issued_invoice_artifacts_issued_invoice_id_issued_invoices"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issued_invoice_artifacts")),
        sa.UniqueConstraint(
            "issued_invoice_id",
            "representation",
            "renderer_version",
            name=op.f("uq_issued_invoice_artifacts_canonical_generation"),
        ),
        sa.UniqueConstraint(
            "id",
            "issued_invoice_id",
            "workspace_id",
            "sha256",
            name=op.f("uq_issued_invoice_artifacts_integrity_identity"),
        ),
    )


def downgrade() -> None:
    op.drop_table("issued_invoice_artifacts")
