"""Persist immutable artifacts bound to exact InvoiceDraft revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_invoice_drafts_exact_revision_workspace",
        "invoice_drafts",
        ["id", "revision", "workspace_id"],
    )
    op.create_table(
        "invoice_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_draft_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_revision", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "invoice_revision > 0",
            name=op.f("ck_invoice_artifacts_positive_invoice_revision"),
        ),
        sa.CheckConstraint(
            "length(btrim(media_type, U&'"
            r"\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020"
            r"\0085\00A0\1680\2000\2001\2002\2003\2004\2005"
            r"\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000"
            "')) > 0",
            name=op.f("ck_invoice_artifacts_nonblank_media_type"),
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_invoice_artifacts_canonical_sha256"),
        ),
        sa.CheckConstraint(
            "byte_size > 0 AND octet_length(content) = byte_size",
            name=op.f("ck_invoice_artifacts_consistent_nonempty_content_size"),
        ),
        sa.ForeignKeyConstraint(
            ["invoice_draft_id", "invoice_revision", "workspace_id"],
            [
                "invoice_drafts.id",
                "invoice_drafts.revision",
                "invoice_drafts.workspace_id",
            ],
            name=op.f("fk_invoice_artifacts_invoice_draft_id_invoice_drafts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_artifacts")),
    )


def downgrade() -> None:
    op.drop_table("invoice_artifacts")
    op.drop_constraint(
        "uq_invoice_drafts_exact_revision_workspace",
        "invoice_drafts",
        type_="unique",
    )
