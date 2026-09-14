from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest

from freelanceflow.modules.clients.application.projects_tasks import (
    ClientNotFound,
    ProjectNotFound,
    ProjectTaskService,
    ProjectTaskStore,
)
from freelanceflow.modules.clients.domain import Client, Project, Task


class MemoryProjectTasks:
    def __init__(self) -> None:
        self.workspace_id = uuid4()
        self.clients: dict[UUID, Client] = {}
        self.projects: dict[UUID, Project] = {}
        self.tasks: dict[UUID, Task] = {}

    def get_client(self, entity_id: UUID) -> Client | None:
        client = self.clients.get(entity_id)
        return client if client and client.workspace_id == self.workspace_id else None

    def add_project(self, value: Project) -> None:
        self.projects[value.id] = value

    def get_project(self, entity_id: UUID) -> Project | None:
        project = self.projects.get(entity_id)
        return project if project and project.client.workspace_id == self.workspace_id else None

    def list_projects(self, client_id: UUID) -> list[Project]:
        return [
            project
            for project in self.projects.values()
            if project.client.id == client_id and project.client.workspace_id == self.workspace_id
        ]

    def add_task(self, value: Task) -> None:
        self.tasks[value.id] = value

    def get_task(self, entity_id: UUID) -> Task | None:
        task = self.tasks.get(entity_id)
        return task if task and task.project.client.workspace_id == self.workspace_id else None

    def list_tasks(self, project_id: UUID) -> list[Task]:
        return [
            task
            for task in self.tasks.values()
            if task.project.id == project_id
            and task.project.client.workspace_id == self.workspace_id
        ]


def test_application_without_http() -> None:
    store = MemoryProjectTasks()
    workspace, foreign_workspace = uuid4(), uuid4()
    client = Client(uuid4(), workspace, "Acme")
    store.clients[client.id] = client

    @contextmanager
    def transaction(workspace_id: UUID) -> Iterator[ProjectTaskStore]:
        store.workspace_id = workspace_id
        yield store

    service = ProjectTaskService(transaction)
    project = service.create_project(workspace, client.id, "Website")
    assert isinstance(project.id, UUID)
    assert project.client == client
    assert service.get_project(workspace, project.id) == project
    assert service.list_projects(workspace, client.id) == [project]
    task = service.create_task(workspace, project.id, "Design")
    assert isinstance(task.id, UUID)
    assert task.project == project
    assert service.get_task(workspace, task.id) == task
    assert service.list_tasks(workspace, project.id) == [task]
    with pytest.raises(ClientNotFound, match="Client not found"):
        service.create_project(workspace, uuid4(), "Missing")
    with pytest.raises(ProjectNotFound, match="Project not found"):
        service.create_task(workspace, uuid4(), "Missing")
    with pytest.raises(ClientNotFound, match="Client not found"):
        service.list_projects(foreign_workspace, client.id)
    with pytest.raises(ProjectNotFound, match="Project not found"):
        service.get_project(foreign_workspace, project.id)
    with pytest.raises(ProjectNotFound, match="Task not found"):
        service.get_task(foreign_workspace, task.id)
