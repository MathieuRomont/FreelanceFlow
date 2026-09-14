"""Persist immutable approval of one exact revision and artifact."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_invoice_artifacts_approval_target",
        "invoice_artifacts",
        ["id", "workspace_id", "invoice_draft_id", "invoice_revision", "sha256"],
    )
    op.create_table(
        "invoice_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_draft_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_revision", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "invoice_revision > 0",
            name=op.f("ck_invoice_approvals_positive_invoice_revision"),
        ),
        sa.CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_invoice_approvals_canonical_artifact_sha256"),
        ),
        sa.ForeignKeyConstraint(
            ["invoice_draft_id", "invoice_revision", "workspace_id"],
            [
                "invoice_drafts.id",
                "invoice_drafts.revision",
                "invoice_drafts.workspace_id",
            ],
            name=op.f("fk_invoice_approvals_invoice_draft_id_invoice_drafts"),
        ),
        sa.ForeignKeyConstraint(
            [
                "artifact_id",
                "workspace_id",
                "invoice_draft_id",
                "invoice_revision",
                "artifact_sha256",
            ],
            [
                "invoice_artifacts.id",
                "invoice_artifacts.workspace_id",
                "invoice_artifacts.invoice_draft_id",
                "invoice_artifacts.invoice_revision",
                "invoice_artifacts.sha256",
            ],
            name=op.f("fk_invoice_approvals_artifact_id_invoice_artifacts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_approvals")),
        sa.UniqueConstraint(
            "invoice_draft_id",
            "invoice_revision",
            name="uq_invoice_approvals_exact_revision",
        ),
    )


def downgrade() -> None:
    op.drop_table("invoice_approvals")
    op.drop_constraint(
        "uq_invoice_artifacts_approval_target",
        "invoice_artifacts",
        type_="unique",
    )
