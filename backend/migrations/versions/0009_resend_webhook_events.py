"""Add immutable Resend delivery-event history and correlation."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_invoice_delivery_attempts_provider_message_id",
        "invoice_delivery_attempts",
        ["provider_message_id"],
    )
    op.create_unique_constraint(
        "uq_invoice_delivery_attempts_delivery_provider_message",
        "invoice_delivery_attempts",
        ["delivery_id", "provider_message_id"],
    )
    op.create_table(
        "invoice_delivery_provider_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_event_id", sa.String(), nullable=False),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("raw_event_type", sa.String(), nullable=False),
        sa.Column("event_kind", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "length(btrim(provider_event_id)) > 0",
            name=op.f(
                "ck_invoice_delivery_provider_events_nonblank_provider_event_id"
            ),
        ),
        sa.CheckConstraint(
            "provider_message_id IS NULL OR "
            "length(btrim(provider_message_id)) > 0",
            name=op.f(
                "ck_invoice_delivery_provider_events_nonblank_provider_message_id"
            ),
        ),
        sa.CheckConstraint(
            "length(btrim(raw_event_type)) > 0",
            name=op.f(
                "ck_invoice_delivery_provider_events_nonblank_raw_event_type"
            ),
        ),
        sa.CheckConstraint(
            "event_kind IN ('provider_accepted', 'recipient_delivered', "
            "'delivery_delayed', 'bounced', 'provider_failed', "
            "'complained', 'unsupported')",
            name=op.f("ck_invoice_delivery_provider_events_valid_event_kind"),
        ),
        sa.CheckConstraint(
            "event_kind = 'unsupported' OR provider_message_id IS NOT NULL",
            name=op.f(
                "ck_invoice_delivery_provider_events_supported_event_has_provider_message"
            ),
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_invoice_delivery_provider_events_canonical_payload_sha256"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_invoice_delivery_provider_events")
        ),
        sa.UniqueConstraint(
            "provider_event_id",
            name="uq_invoice_delivery_provider_events_provider_event_id",
        ),
        sa.UniqueConstraint(
            "id",
            "provider_message_id",
            name="uq_invoice_delivery_provider_events_id_provider_message",
        ),
    )
    op.create_index(
        "ix_invoice_delivery_provider_events_provider_message_id",
        "invoice_delivery_provider_events",
        ["provider_message_id"],
    )
    op.create_table(
        "invoice_delivery_provider_event_matches",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_message_id", sa.String(), nullable=False),
        sa.Column("correlated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(provider_message_id)) > 0",
            name=op.f(
                "ck_invoice_delivery_provider_event_matches_nonblank_provider_message_id"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "provider_message_id"],
            [
                "invoice_delivery_provider_events.id",
                "invoice_delivery_provider_events.provider_message_id",
            ],
            name=op.f(
                "fk_invoice_delivery_provider_event_matches_event_id_"
                "invoice_delivery_provider_events"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id", "provider_message_id"],
            [
                "invoice_delivery_attempts.delivery_id",
                "invoice_delivery_attempts.provider_message_id",
            ],
            name=op.f(
                "fk_invoice_delivery_provider_event_matches_delivery_id_"
                "invoice_delivery_attempts"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id", "workspace_id"],
            ["invoice_deliveries.id", "invoice_deliveries.workspace_id"],
            name=op.f(
                "fk_invoice_delivery_provider_event_matches_delivery_id_"
                "invoice_deliveries"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "event_id", name=op.f("pk_invoice_delivery_provider_event_matches")
        ),
    )


def downgrade() -> None:
    op.drop_table("invoice_delivery_provider_event_matches")
    op.drop_index(
        "ix_invoice_delivery_provider_events_provider_message_id",
        table_name="invoice_delivery_provider_events",
    )
    op.drop_table("invoice_delivery_provider_events")
    op.drop_constraint(
        "uq_invoice_delivery_attempts_delivery_provider_message",
        "invoice_delivery_attempts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_invoice_delivery_attempts_provider_message_id",
        "invoice_delivery_attempts",
        type_="unique",
    )
