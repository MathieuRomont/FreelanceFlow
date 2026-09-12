"""Initial core domain persistence."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_clients_workspace_id")),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "client_id"],
            ["clients.workspace_id", "clients.id"],
            name=op.f("fk_projects_workspace_id_clients"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint(
            "workspace_id", "client_id", "id", name=op.f("uq_projects_workspace_id")
        ),
    )
    op.create_table(
        "rate_agreements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("hourly_amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "hourly_amount NOT IN ('NaN', 'Infinity', '-Infinity')",
            name=op.f("ck_rate_agreements_finite_rate"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name=op.f("ck_rate_agreements_validity"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "client_id", "project_id"],
            ["projects.workspace_id", "projects.client_id", "projects.id"],
            name=op.f("fk_rate_agreements_workspace_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "client_id"],
            ["clients.workspace_id", "clients.id"],
            name=op.f("fk_rate_agreements_workspace_id_clients"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rate_agreements")),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "client_id", "project_id"],
            ["projects.workspace_id", "projects.client_id", "projects.id"],
            name=op.f("fk_tasks_workspace_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.UniqueConstraint("workspace_id", "project_id", "id", name=op.f("uq_tasks_workspace_id")),
    )
    op.create_table(
        "time_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_zone", sa.String(), nullable=True),
        sa.Column("end_zone", sa.String(), nullable=True),
        sa.Column("start_offset_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("end_offset_microseconds", sa.BigInteger(), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint('"end" > start', name=op.f("ck_time_entries_positive_interval")),
        sa.CheckConstraint(
            "(client_id IS NULL) = (project_id IS NULL)",
            name=op.f("ck_time_entries_complete_classification"),
        ),
        sa.CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL", name=op.f("ck_time_entries_task_project")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "client_id", "project_id"],
            ["projects.workspace_id", "projects.client_id", "projects.id"],
            name=op.f("fk_time_entries_workspace_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "client_id"],
            ["clients.workspace_id", "clients.id"],
            name=op.f("fk_time_entries_workspace_id_clients"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "task_id"],
            ["tasks.workspace_id", "tasks.project_id", "tasks.id"],
            name=op.f("fk_time_entries_workspace_id_tasks"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_time_entries")),
    )


def downgrade() -> None:
    op.drop_table("time_entries")
    op.drop_table("tasks")
    op.drop_table("rate_agreements")
    op.drop_table("projects")
    op.drop_table("clients")
