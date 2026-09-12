from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class ClientRow(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("workspace_id", "id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    name: Mapped[str]


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "client_id", "id"),
        ForeignKeyConstraint(["workspace_id", "client_id"], ["clients.workspace_id", "clients.id"]),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    client_id: Mapped[UUID]
    name: Mapped[str]


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "client_id", "project_id"],
            ["projects.workspace_id", "projects.client_id", "projects.id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    client_id: Mapped[UUID]
    project_id: Mapped[UUID]
    name: Mapped[str]
