"""Add optional workspace billing timezone without historical backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_invoice_settings",
        sa.Column("billing_timezone", sa.String(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_workspace_invoice_settings_nonblank_billing_timezone"),
        "workspace_invoice_settings",
        "billing_timezone IS NULL OR length(btrim(billing_timezone)) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_workspace_invoice_settings_nonblank_billing_timezone"),
        "workspace_invoice_settings",
        type_="check",
    )
    op.drop_column("workspace_invoice_settings", "billing_timezone")
