"""Persist provider-neutral invoice email payloads and send outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoice_deliveries", sa.Column("sender", sa.String(), nullable=True))
    op.add_column("invoice_deliveries", sa.Column("recipient", sa.String(), nullable=True))
    op.add_column("invoice_deliveries", sa.Column("subject", sa.String(), nullable=True))
    op.add_column("invoice_deliveries", sa.Column("body", sa.String(), nullable=True))
    op.add_column(
        "invoice_deliveries",
        sa.Column("attachment_filename", sa.String(), nullable=True),
    )
    op.add_column(
        "invoice_delivery_attempts",
        sa.Column("provider_message_id", sa.String(), nullable=True),
    )

    op.drop_constraint(
        op.f("ck_invoice_deliveries_valid_state"),
        "invoice_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_invoice_deliveries_consistent_state_metadata"),
        "invoice_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_invoice_deliveries_valid_state"),
        "invoice_deliveries",
        "state IN ('pending', 'in_progress', 'sent', 'failed')",
    )
    op.create_check_constraint(
        op.f("ck_invoice_deliveries_consistent_state_metadata"),
        "invoice_deliveries",
        "(state = 'pending' AND active_attempt_id IS NULL AND sent_at IS NULL) OR "
        "(state = 'in_progress' AND active_attempt_id IS NOT NULL "
        "AND sent_at IS NULL AND attempt_count > 0) OR "
        "(state = 'sent' AND active_attempt_id IS NULL "
        "AND sent_at IS NOT NULL AND attempt_count > 0) OR "
        "(state = 'failed' AND active_attempt_id IS NULL "
        "AND sent_at IS NULL AND attempt_count > 0)",
    )
    op.create_check_constraint(
        op.f("ck_invoice_deliveries_complete_message_snapshot"),
        "invoice_deliveries",
        "(sender IS NULL AND recipient IS NULL AND subject IS NULL "
        "AND body IS NULL AND attachment_filename IS NULL) OR "
        "(sender IS NOT NULL AND length(btrim(sender)) > 0 "
        "AND recipient IS NOT NULL AND length(btrim(recipient)) > 0 "
        "AND subject IS NOT NULL AND body IS NOT NULL "
        "AND attachment_filename IS NOT NULL "
        "AND length(btrim(attachment_filename)) > 0)",
    )

    op.drop_constraint(
        op.f("ck_invoice_delivery_attempts_valid_outcome"),
        "invoice_delivery_attempts",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_invoice_delivery_attempts_consistent_outcome_metadata"),
        "invoice_delivery_attempts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_invoice_delivery_attempts_valid_outcome"),
        "invoice_delivery_attempts",
        "outcome IS NULL OR outcome IN ('failed', 'rejected', 'ambiguous', 'sent')",
    )
    op.create_check_constraint(
        op.f("ck_invoice_delivery_attempts_consistent_outcome_metadata"),
        "invoice_delivery_attempts",
        "(outcome IS NULL AND completed_at IS NULL AND failure_reason IS NULL "
        "AND provider_message_id IS NULL) OR "
        "(outcome = 'sent' AND completed_at IS NOT NULL "
        "AND failure_reason IS NULL AND (provider_message_id IS NULL "
        "OR length(btrim(provider_message_id)) > 0)) OR "
        "(outcome IN ('failed', 'rejected', 'ambiguous') "
        "AND completed_at IS NOT NULL AND failure_reason IS NOT NULL "
        "AND length(btrim(failure_reason)) > 0 "
        "AND provider_message_id IS NULL)",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM invoice_deliveries WHERE state = 'failed'
            ) OR EXISTS (
                SELECT 1 FROM invoice_delivery_attempts
                WHERE outcome IN ('rejected', 'ambiguous')
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0008 with rejected or ambiguous delivery history';
            END IF;
        END
        $$
        """
    )
    op.drop_constraint(
        op.f("ck_invoice_delivery_attempts_consistent_outcome_metadata"),
        "invoice_delivery_attempts",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_invoice_delivery_attempts_valid_outcome"),
        "invoice_delivery_attempts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_invoice_delivery_attempts_valid_outcome"),
        "invoice_delivery_attempts",
        "outcome IS NULL OR outcome IN ('failed', 'sent')",
    )
    op.create_check_constraint(
        op.f("ck_invoice_delivery_attempts_consistent_outcome_metadata"),
        "invoice_delivery_attempts",
        "(outcome IS NULL AND completed_at IS NULL AND failure_reason IS NULL) OR "
        "(outcome = 'sent' AND completed_at IS NOT NULL AND failure_reason IS NULL) OR "
        "(outcome = 'failed' AND completed_at IS NOT NULL "
        "AND length(btrim(failure_reason)) > 0)",
    )
    op.drop_column("invoice_delivery_attempts", "provider_message_id")

    op.drop_constraint(
        op.f("ck_invoice_deliveries_complete_message_snapshot"),
        "invoice_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_invoice_deliveries_consistent_state_metadata"),
        "invoice_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_invoice_deliveries_valid_state"),
        "invoice_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_invoice_deliveries_valid_state"),
        "invoice_deliveries",
        "state IN ('pending', 'in_progress', 'sent')",
    )
    op.create_check_constraint(
        op.f("ck_invoice_deliveries_consistent_state_metadata"),
        "invoice_deliveries",
        "(state = 'pending' AND active_attempt_id IS NULL AND sent_at IS NULL) OR "
        "(state = 'in_progress' AND active_attempt_id IS NOT NULL "
        "AND sent_at IS NULL AND attempt_count > 0) OR "
        "(state = 'sent' AND active_attempt_id IS NULL "
        "AND sent_at IS NOT NULL AND attempt_count > 0)",
    )
    op.drop_column("invoice_deliveries", "attachment_filename")
    op.drop_column("invoice_deliveries", "body")
    op.drop_column("invoice_deliveries", "subject")
    op.drop_column("invoice_deliveries", "recipient")
    op.drop_column("invoice_deliveries", "sender")
