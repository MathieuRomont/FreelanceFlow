"""Add durable invoice deliveries and immutable attempt history."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_invoice_approvals_delivery_target",
        "invoice_approvals",
        [
            "id",
            "workspace_id",
            "invoice_draft_id",
            "invoice_revision",
            "artifact_id",
            "artifact_sha256",
        ],
    )
    op.create_table(
        "invoice_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_draft_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_revision", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "invoice_revision > 0",
            name=op.f("ck_invoice_deliveries_positive_invoice_revision"),
        ),
        sa.CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_invoice_deliveries_canonical_artifact_sha256"),
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'in_progress', 'sent')",
            name=op.f("ck_invoice_deliveries_valid_state"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_invoice_deliveries_nonnegative_attempt_count"),
        ),
        sa.CheckConstraint(
            "(state = 'pending' AND active_attempt_id IS NULL AND sent_at IS NULL) OR "
            "(state = 'in_progress' AND active_attempt_id IS NOT NULL "
            "AND sent_at IS NULL AND attempt_count > 0) OR "
            "(state = 'sent' AND active_attempt_id IS NULL "
            "AND sent_at IS NOT NULL AND attempt_count > 0)",
            name=op.f("ck_invoice_deliveries_consistent_state_metadata"),
        ),
        sa.CheckConstraint(
            "sent_at IS NULL OR sent_at >= requested_at",
            name=op.f("ck_invoice_deliveries_sent_after_request"),
        ),
        sa.ForeignKeyConstraint(
            [
                "approval_id",
                "workspace_id",
                "invoice_draft_id",
                "invoice_revision",
                "artifact_id",
                "artifact_sha256",
            ],
            [
                "invoice_approvals.id",
                "invoice_approvals.workspace_id",
                "invoice_approvals.invoice_draft_id",
                "invoice_approvals.invoice_revision",
                "invoice_approvals.artifact_id",
                "invoice_approvals.artifact_sha256",
            ],
            name=op.f("fk_invoice_deliveries_approval_id_invoice_approvals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_deliveries")),
        sa.UniqueConstraint(
            "approval_id", name="uq_invoice_deliveries_approval_id"
        ),
        sa.UniqueConstraint(
            "id", "workspace_id", name="uq_invoice_deliveries_workspace"
        ),
    )
    op.create_table(
        "invoice_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.CheckConstraint(
            "sequence > 0",
            name=op.f("ck_invoice_delivery_attempts_positive_sequence"),
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('failed', 'sent')",
            name=op.f("ck_invoice_delivery_attempts_valid_outcome"),
        ),
        sa.CheckConstraint(
            "(outcome IS NULL AND completed_at IS NULL AND failure_reason IS NULL) OR "
            "(outcome = 'sent' AND completed_at IS NOT NULL "
            "AND failure_reason IS NULL) OR "
            "(outcome = 'failed' AND completed_at IS NOT NULL "
            "AND length(btrim(failure_reason)) > 0)",
            name=op.f("ck_invoice_delivery_attempts_consistent_outcome_metadata"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name=op.f("ck_invoice_delivery_attempts_completion_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id", "workspace_id"],
            ["invoice_deliveries.id", "invoice_deliveries.workspace_id"],
            name=op.f(
                "fk_invoice_delivery_attempts_delivery_id_invoice_deliveries"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_delivery_attempts")),
        sa.UniqueConstraint(
            "delivery_id",
            "id",
            name="uq_invoice_delivery_attempts_delivery_id_id",
        ),
        sa.UniqueConstraint(
            "delivery_id",
            "sequence",
            name="uq_invoice_delivery_attempts_delivery_sequence",
        ),
    )
    op.create_index(
        "uq_invoice_delivery_attempts_open_delivery",
        "invoice_delivery_attempts",
        ["delivery_id"],
        unique=True,
        postgresql_where=sa.text("outcome IS NULL"),
    )
    op.create_foreign_key(
        "fk_invoice_deliveries_active_attempt",
        "invoice_deliveries",
        "invoice_delivery_attempts",
        ["id", "active_attempt_id"],
        ["delivery_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_invoice_deliveries_active_attempt",
        "invoice_deliveries",
        type_="foreignkey",
    )
    op.drop_table("invoice_delivery_attempts")
    op.drop_table("invoice_deliveries")
    op.drop_constraint(
        "uq_invoice_approvals_delivery_target",
        "invoice_approvals",
        type_="unique",
    )
