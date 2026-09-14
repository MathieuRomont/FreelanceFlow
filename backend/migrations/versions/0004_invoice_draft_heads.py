"""Serialize immutable InvoiceDraft revision creation through logical heads."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_draft_heads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("currency_decimal_places", sa.Integer(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "current_revision > 0",
            name=op.f("ck_invoice_draft_heads_positive_current_revision"),
        ),
        sa.CheckConstraint(
            "currency = 'EUR' AND currency_decimal_places = 2",
            name=op.f("ck_invoice_draft_heads_supported_currency_precision"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_draft_heads")),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            "client_id",
            "currency",
            "currency_decimal_places",
            name=op.f("uq_invoice_draft_heads_id"),
        ),
    )
    op.execute(
        """
        INSERT INTO invoice_draft_heads (
            id,
            workspace_id,
            client_id,
            currency,
            currency_decimal_places,
            current_revision
        )
        SELECT
            id,
            workspace_id,
            client_id,
            currency,
            currency_decimal_places,
            max(revision)
        FROM invoice_drafts
        GROUP BY id, workspace_id, client_id, currency, currency_decimal_places
        """
    )
    op.create_foreign_key(
        op.f("fk_invoice_drafts_id_invoice_draft_heads"),
        "invoice_drafts",
        "invoice_draft_heads",
        ["id", "workspace_id", "client_id", "currency", "currency_decimal_places"],
        ["id", "workspace_id", "client_id", "currency", "currency_decimal_places"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_invoice_drafts_id_invoice_draft_heads"),
        "invoice_drafts",
        type_="foreignkey",
    )
    op.drop_table("invoice_draft_heads")
