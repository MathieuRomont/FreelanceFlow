"""TimeEntry use cases with explicit transactions and no HTTP dependencies."""

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.domain import (
    TimeEntry,
    TimeEntryOwnershipError,
    classify_time_entry,
    clear_time_entry_classification,
)


class TimeEntryResourceNotFound(LookupError):
    """A requested workspace-scoped time-tracking resource is unavailable."""


class TimeEntryStore(Protocol):
    def get_client(self, entity_id: UUID) -> Client | None: ...
    def get_project(self, entity_id: UUID) -> Project | None: ...
    def get_task(self, entity_id: UUID) -> Task | None: ...
    def add(self, value: TimeEntry) -> None: ...
    def get(self, entity_id: UUID) -> TimeEntry | None: ...
    def list(self) -> list[TimeEntry]: ...
    def update_classification(self, value: TimeEntry) -> None: ...


class TimeEntryTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[TimeEntryStore]: ...


def _require_complete_classification(
    client_id: UUID | None, project_id: UUID | None, task_id: UUID | None
) -> None:
    if (client_id is None) != (project_id is None) or (
        task_id is not None and project_id is None
    ):
        raise TimeEntryOwnershipError(
            "Classification must be empty or contain client and project with an optional task"
        )


def _get_classification(
    store: TimeEntryStore,
    client_id: UUID,
    project_id: UUID,
    task_id: UUID | None,
) -> tuple[Client, Project, Task | None]:
    client = store.get_client(client_id)
    project = store.get_project(project_id)
    task = store.get_task(task_id) if task_id is not None else None
    if client is None or project is None or (task_id is not None and task is None):
        raise TimeEntryResourceNotFound("TimeEntry resource not found")
    return client, project, task


class TimeEntryService:
    def __init__(self, transaction: TimeEntryTransaction) -> None:
        self.transaction = transaction

    def create(
        self,
        *,
        workspace_id: UUID,
        start: datetime,
        end: datetime,
        billable: bool,
        client_id: UUID | None,
        project_id: UUID | None,
        task_id: UUID | None,
    ) -> TimeEntry:
        _require_complete_classification(client_id, project_id, task_id)
        with self.transaction(workspace_id) as store:
            client: Client | None = None
            project: Project | None = None
            task: Task | None = None
            if client_id is not None and project_id is not None:
                client, project, task = _get_classification(
                    store, client_id, project_id, task_id
                )
            entry = TimeEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                start=start,
                end=end,
                billable=billable,
                client=client,
                project=project,
                task=task,
            )
            store.add(entry)
        return entry

    def get(self, workspace_id: UUID, entry_id: UUID) -> TimeEntry:
        with self.transaction(workspace_id) as store:
            entry = store.get(entry_id)
            if entry is None:
                raise TimeEntryResourceNotFound("TimeEntry resource not found")
        return entry

    def list(self, workspace_id: UUID) -> list[TimeEntry]:
        with self.transaction(workspace_id) as store:
            return store.list()

    def classify(
        self,
        *,
        workspace_id: UUID,
        entry_id: UUID,
        client_id: UUID,
        project_id: UUID,
        task_id: UUID | None,
    ) -> TimeEntry:
        with self.transaction(workspace_id) as store:
            entry = store.get(entry_id)
            if entry is None:
                raise TimeEntryResourceNotFound("TimeEntry resource not found")
            client, project, task = _get_classification(
                store, client_id, project_id, task_id
            )
            classified = classify_time_entry(
                entry, client=client, project=project, task=task
            )
            store.update_classification(classified)
        return classified

    def clear_classification(self, workspace_id: UUID, entry_id: UUID) -> TimeEntry:
        with self.transaction(workspace_id) as store:
            entry = store.get(entry_id)
            if entry is None:
                raise TimeEntryResourceNotFound("TimeEntry resource not found")
            cleared = clear_time_entry_classification(entry)
            store.update_classification(cleared)
        return cleared
