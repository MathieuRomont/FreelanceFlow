"""Project and task use cases with explicit transaction ownership and no HTTP dependencies."""

from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.clients.domain import Client, Project, Task


class ClientNotFound(LookupError):
    """No client exists in the requested workspace."""


class ProjectNotFound(LookupError):
    """No project exists in the requested workspace."""


class ProjectTaskStore(Protocol):
    def get_client(self, entity_id: UUID) -> Client | None: ...
    def add_project(self, value: Project) -> None: ...
    def get_project(self, entity_id: UUID) -> Project | None: ...
    def list_projects(self, client_id: UUID) -> list[Project]: ...
    def add_task(self, value: Task) -> None: ...
    def get_task(self, entity_id: UUID) -> Task | None: ...
    def list_tasks(self, project_id: UUID) -> list[Task]: ...


class ProjectTaskTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[ProjectTaskStore]: ...


class ProjectTaskService:
    def __init__(self, transaction: ProjectTaskTransaction) -> None:
        self.transaction = transaction

    def create_project(self, workspace_id: UUID, client_id: UUID, name: str) -> Project:
        with self.transaction(workspace_id) as store:
            client = store.get_client(client_id)
            if client is None:
                raise ClientNotFound("Client not found")
            project = Project(uuid4(), client, name)
            store.add_project(project)
        return project

    def get_project(self, workspace_id: UUID, project_id: UUID) -> Project:
        with self.transaction(workspace_id) as store:
            project = store.get_project(project_id)
            if project is None:
                raise ProjectNotFound("Project not found")
        return project

    def list_projects(self, workspace_id: UUID, client_id: UUID) -> list[Project]:
        with self.transaction(workspace_id) as store:
            if store.get_client(client_id) is None:
                raise ClientNotFound("Client not found")
            return store.list_projects(client_id)

    def create_task(self, workspace_id: UUID, project_id: UUID, name: str) -> Task:
        with self.transaction(workspace_id) as store:
            project = store.get_project(project_id)
            if project is None:
                raise ProjectNotFound("Project not found")
            task = Task(uuid4(), project, name)
            store.add_task(task)
        return task

    def get_task(self, workspace_id: UUID, task_id: UUID) -> Task:
        with self.transaction(workspace_id) as store:
            task = store.get_task(task_id)
            if task is None:
                raise ProjectNotFound("Task not found")
        return task

    def list_tasks(self, workspace_id: UUID, project_id: UUID) -> list[Task]:
        with self.transaction(workspace_id) as store:
            if store.get_project(project_id) is None:
                raise ProjectNotFound("Project not found")
            return store.list_tasks(project_id)
