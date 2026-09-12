from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class TimeEntryRow(Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "client_id"], ["clients.workspace_id", "clients.id"]),
        ForeignKeyConstraint(
            ["workspace_id", "client_id", "project_id"],
            ["projects.workspace_id", "projects.client_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "task_id"],
            ["tasks.workspace_id", "tasks.project_id", "tasks.id"],
        ),
        CheckConstraint('"end" > start', name="positive_interval"),
        CheckConstraint(
            "(client_id IS NULL) = (project_id IS NULL)", name="complete_classification"
        ),
        CheckConstraint("task_id IS NULL OR project_id IS NOT NULL", name="task_project"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_zone: Mapped[str | None]
    end_zone: Mapped[str | None]
    start_offset_microseconds: Mapped[int] = mapped_column(BigInteger)
    end_offset_microseconds: Mapped[int] = mapped_column(BigInteger)
    billable: Mapped[bool]
    client_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    task_id: Mapped[UUID | None]
