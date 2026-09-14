from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.application.time_entries import (
    TimeEntryResourceNotFound,
    TimeEntryService,
    TimeEntryStore,
)
from freelanceflow.modules.time_tracking.domain import TimeEntry, TimeEntryOwnershipError


class MemoryTimeEntries:
    def __init__(self, workspace_id: UUID) -> None:
        self.workspace_id = workspace_id
        self.clients: dict[UUID, Client] = {}
        self.projects: dict[UUID, Project] = {}
        self.tasks: dict[UUID, Task] = {}
        self.entries: dict[UUID, TimeEntry] = {}

    def get_client(self, entity_id: UUID) -> Client | None:
        value = self.clients.get(entity_id)
        return value if value and value.workspace_id == self.workspace_id else None

    def get_project(self, entity_id: UUID) -> Project | None:
        value = self.projects.get(entity_id)
        return value if value and value.client.workspace_id == self.workspace_id else None

    def get_task(self, entity_id: UUID) -> Task | None:
        value = self.tasks.get(entity_id)
        return value if value and value.project.client.workspace_id == self.workspace_id else None

    def add(self, value: TimeEntry) -> None:
        self.entries[value.id] = value

    def get(self, entity_id: UUID) -> TimeEntry | None:
        value = self.entries.get(entity_id)
        return value if value and value.workspace_id == self.workspace_id else None

    def list(self) -> list[TimeEntry]:
        return [value for value in self.entries.values() if value.workspace_id == self.workspace_id]

    def update_classification(self, value: TimeEntry) -> None:
        self.entries[value.id] = value


def test_application_lifecycle_preserves_time_and_billable_state() -> None:
    workspace, other_workspace = uuid4(), uuid4()
    client = Client(uuid4(), workspace, "Acme")
    project = Project(uuid4(), client, "Website")
    task = Task(uuid4(), project, "Design")
    other_client = Client(uuid4(), workspace, "Other")
    other_project = Project(uuid4(), other_client, "Other project")
    store = MemoryTimeEntries(workspace)
    store.clients = {client.id: client, other_client.id: other_client}
    store.projects = {project.id: project, other_project.id: other_project}
    store.tasks = {task.id: task}

    @contextmanager
    def transaction(workspace_id: UUID) -> Iterator[TimeEntryStore]:
        store.workspace_id = workspace_id
        yield store

    service = TimeEntryService(transaction)
    start = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    end = datetime(2026, 1, 1, 8, 0, 0, 1, tzinfo=UTC)
    entry = service.create(
        workspace_id=workspace,
        start=start,
        end=end,
        billable=False,
        client_id=None,
        project_id=None,
        task_id=None,
    )
    assert isinstance(entry.id, UUID)
    assert entry.duration == timedelta(hours=1, minutes=30, microseconds=1)
    assert service.get(workspace, entry.id) == entry
    assert service.list(workspace) == [entry]
    second = service.create(
        workspace_id=workspace,
        start=start,
        end=end,
        billable=True,
        client_id=None,
        project_id=None,
        task_id=None,
    )
    assert isinstance(second.id, UUID) and second.id != entry.id

    classified = service.classify(
        workspace_id=workspace,
        entry_id=entry.id,
        client_id=client.id,
        project_id=project.id,
        task_id=task.id,
    )
    without_task = service.classify(
        workspace_id=workspace,
        entry_id=entry.id,
        client_id=client.id,
        project_id=project.id,
        task_id=None,
    )
    cleared = service.clear_classification(workspace, entry.id)
    assert (classified.client, classified.project, classified.task) == (client, project, task)
    assert (without_task.client, without_task.project, without_task.task) == (
        client,
        project,
        None,
    )
    assert (cleared.client, cleared.project, cleared.task) == (None, None, None)
    for changed in (classified, without_task, cleared):
        assert changed.id == entry.id
        assert changed.start is start and changed.end is end
        assert changed.duration == entry.duration
        assert changed.billable is False

    with pytest.raises(TimeEntryOwnershipError):
        service.create(
            workspace_id=workspace,
            start=start,
            end=end,
            billable=True,
            client_id=client.id,
            project_id=None,
            task_id=None,
        )
    with pytest.raises(TimeEntryOwnershipError):
        service.classify(
            workspace_id=workspace,
            entry_id=entry.id,
            client_id=client.id,
            project_id=other_project.id,
            task_id=None,
        )
    with pytest.raises(TimeEntryResourceNotFound):
        service.get(other_workspace, entry.id)
    with pytest.raises(TimeEntryResourceNotFound):
        service.classify(
            workspace_id=workspace,
            entry_id=uuid4(),
            client_id=client.id,
            project_id=project.id,
            task_id=None,
        )
