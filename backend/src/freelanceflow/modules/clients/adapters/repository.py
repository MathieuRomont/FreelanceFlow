"""Explicit mappings; related records must already exist. No implicit commits."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from freelanceflow.modules.clients.adapters.models import ClientRow, ProjectRow, TaskRow
from freelanceflow.modules.clients.domain import Client, Project, Task


class ClientRepository:
    def __init__(self, session: Session, *, workspace_id: UUID) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def add_client(self, value: Client) -> None:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(ClientRow(id=value.id, workspace_id=self.workspace_id, name=value.name))
        self.session.flush()

    def get_client(self, entity_id: UUID) -> Client | None:
        row = self.session.scalar(
            select(ClientRow).where(
                ClientRow.id == entity_id, ClientRow.workspace_id == self.workspace_id
            )
        )
        if row is None:
            return None
        return Client(row.id, row.workspace_id, row.name)

    def list_clients(self) -> list[Client]:
        rows = self.session.scalars(
            select(ClientRow)
            .where(ClientRow.workspace_id == self.workspace_id)
            .order_by(ClientRow.id)
        )
        return [Client(row.id, row.workspace_id, row.name) for row in rows]

    def add_project(self, value: Project) -> None:
        if value.client.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(
            ProjectRow(
                id=value.id,
                workspace_id=self.workspace_id,
                name=value.name,
                client_id=value.client.id,
            )
        )
        self.session.flush()

    def get_project(self, entity_id: UUID) -> Project | None:
        row = self.session.scalar(
            select(ProjectRow).where(
                ProjectRow.id == entity_id, ProjectRow.workspace_id == self.workspace_id
            )
        )
        if row is None:
            return None
        client = self.get_client(row.client_id)
        assert client is not None
        return Project(row.id, client, row.name)

    def add_task(self, value: Task) -> None:
        if value.project.client.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(
            TaskRow(
                id=value.id,
                workspace_id=self.workspace_id,
                name=value.name,
                client_id=value.project.client.id,
                project_id=value.project.id,
            )
        )
        self.session.flush()

    def get_task(self, entity_id: UUID) -> Task | None:
        row = self.session.scalar(
            select(TaskRow).where(
                TaskRow.id == entity_id, TaskRow.workspace_id == self.workspace_id
            )
        )
        if row is None:
            return None
        project = self.get_project(row.project_id)
        assert project is not None
        return Task(row.id, project, row.name)
