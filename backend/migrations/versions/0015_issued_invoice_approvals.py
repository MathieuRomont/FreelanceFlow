"""Add immutable approval for exact issued-invoice artifacts."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_issued_invoice_artifacts_approval_identity"),
        "issued_invoice_artifacts",
        [
            "id",
            "issued_invoice_id",
            "workspace_id",
            "sha256",
            "representation",
            "renderer_version",
        ],
    )
    op.create_table(
        "issued_invoice_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("issued_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("issued_invoice_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("representation", sa.String(), nullable=False),
        sa.Column("renderer_version", sa.String(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_issued_invoice_approvals_canonical_artifact_sha256"),
        ),
        sa.CheckConstraint(
            "length(btrim(renderer_version)) > 0",
            name=op.f("ck_issued_invoice_approvals_nonblank_renderer_version"),
        ),
        sa.CheckConstraint(
            "representation = 'pdf'",
            name=op.f("ck_issued_invoice_approvals_supported_representation"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_invoice_id", "workspace_id"],
            ["issued_invoices.id", "issued_invoices.workspace_id"],
            name=op.f("fk_issued_invoice_approvals_issued_invoice_id_issued_invoices"),
        ),
        sa.ForeignKeyConstraint(
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
            name=op.f(
                "fk_issued_invoice_approvals_issued_invoice_artifact_id_issued_invoice_artifacts"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issued_invoice_approvals")),
        sa.UniqueConstraint(
            "issued_invoice_id",
            name=op.f("uq_issued_invoice_approvals_one_per_invoice"),
        ),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            "issued_invoice_id",
            "issued_invoice_artifact_id",
            "artifact_sha256",
            "representation",
            "renderer_version",
            name=op.f("uq_issued_invoice_approvals_target_identity"),
        ),
    )


def downgrade() -> None:
    op.drop_table("issued_invoice_approvals")
    op.drop_constraint(
        op.f("uq_issued_invoice_artifacts_approval_identity"),
        "issued_invoice_artifacts",
        type_="unique",
    )
