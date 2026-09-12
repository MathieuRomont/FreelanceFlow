from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class ClientRow(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint(
            "length(btrim(name, U&'"
            r"\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020"
            r"\0085\00A0\1680\2000\2001\2002\2003\2004\2005"
            r"\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000"
            "')) > 0",
            name="nonblank_name",
        ),
    )

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
