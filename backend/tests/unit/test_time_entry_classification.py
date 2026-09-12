from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.domain import (
    TimeEntry,
    TimeEntryOwnershipError,
    classify_time_entry,
    clear_time_entry_classification,
)

CLIENT = Client(UUID(int=1), UUID(int=2), "Client")
PROJECT = Project(UUID(int=3), CLIENT, "Project")
TASK = Task(UUID(int=4), PROJECT, "Task")


def unclassified_entry(billable: bool = True) -> TimeEntry:
    paris = ZoneInfo("Europe/Paris")
    return TimeEntry(
        id=UUID(int=5),
        workspace_id=CLIENT.workspace_id,
        start=datetime(2026, 10, 25, 2, 45, tzinfo=paris, fold=0),
        end=datetime(2026, 10, 25, 2, 15, 0, 123456, tzinfo=paris, fold=1),
        billable=billable,
    )


@pytest.mark.parametrize("billable", [True, False])
@pytest.mark.parametrize("task", [None, TASK])
def test_classification_lifecycle_preserves_interval_and_originals(
    billable: bool, task: Task | None
) -> None:
    original = unclassified_entry(billable)
    assert (original.client, original.project, original.task) == (None, None, None)

    classified = classify_time_entry(original, client=CLIENT, project=PROJECT, task=task)
    assert (classified.client, classified.project, classified.task) == (CLIENT, PROJECT, task)

    other_client = replace(CLIENT, id=UUID(int=6))
    other_project = replace(PROJECT, id=UUID(int=7), client=other_client)
    reclassified = classify_time_entry(classified, client=other_client, project=other_project)
    assert (reclassified.client, reclassified.project, reclassified.task) == (
        other_client,
        other_project,
        None,
    )
    other_task = replace(TASK, id=UUID(int=8), project=other_project)
    with_task = classify_time_entry(
        reclassified, client=other_client, project=other_project, task=other_task
    )
    assert with_task.task is other_task
    cleared = clear_time_entry_classification(with_task)
    cleared_again = clear_time_entry_classification(cleared)
    assert (cleared.client, cleared.project, cleared.task) == (None, None, None)
    assert cleared_again == original

    results = [original, classified, reclassified, with_task, cleared, cleared_again]
    assert len({id(result) for result in results}) == len(results)
    for result in results:
        assert result.id == original.id
        assert result.workspace_id == original.workspace_id
        assert result.start is original.start
        assert result.end is original.end
        assert result.duration == timedelta(minutes=30, microseconds=123456)
        assert result.billable is billable
        with pytest.raises(FrozenInstanceError):
            result.client = other_client  # type: ignore[misc]

    assert (original.client, original.project, original.task) == (None, None, None)
    assert (classified.client, classified.project, classified.task) == (CLIENT, PROJECT, task)
    assert reclassified.task is None
    assert with_task.task is other_task


@pytest.mark.parametrize("already_classified", [False, True])
@pytest.mark.parametrize(
    "client, project, task",
    [
        (replace(CLIENT, id=UUID(int=6)), PROJECT, None),
        (CLIENT, PROJECT, replace(TASK, project=replace(PROJECT, id=UUID(int=6)))),
        (replace(CLIENT, workspace_id=UUID(int=6)), PROJECT, None),
        (CLIENT, replace(PROJECT, client=replace(CLIENT, workspace_id=UUID(int=6))), None),
        (
            CLIENT,
            PROJECT,
            replace(
                TASK, project=replace(PROJECT, client=replace(CLIENT, workspace_id=UUID(int=6)))
            ),
        ),
        (
            CLIENT,
            PROJECT,
            replace(TASK, project=replace(PROJECT, client=replace(CLIENT, id=UUID(int=6)))),
        ),
    ],
)
def test_invalid_ownership_is_rejected_without_mutation(
    already_classified: bool, client: Client, project: Project, task: Task | None
) -> None:
    original = unclassified_entry()
    if already_classified:
        original = classify_time_entry(original, client=CLIENT, project=PROJECT, task=TASK)
    snapshot = replace(original)
    with pytest.raises(TimeEntryOwnershipError):
        classify_time_entry(original, client=client, project=project, task=task)
    assert original == snapshot


@pytest.mark.parametrize("missing", ["client", "project"])
def test_classification_requires_client_and_project(missing: str) -> None:
    with pytest.raises(TimeEntryOwnershipError, match="requires both"):
        if missing == "client":
            classify_time_entry(unclassified_entry(), client=None, project=PROJECT)  # type: ignore[arg-type]
        else:
            classify_time_entry(unclassified_entry(), client=CLIENT, project=None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "client, project, task",
    [
        pytest.param(CLIENT, None, None, id="client-only"),
        pytest.param(None, PROJECT, None, id="project-only"),
        pytest.param(None, None, TASK, id="task-only"),
        pytest.param(CLIENT, None, TASK, id="task-without-project"),
        pytest.param(None, PROJECT, TASK, id="task-without-client"),
    ],
)
@pytest.mark.parametrize(
    "construction", ["constructor", "replace-unclassified", "replace-classified"]
)
def test_partial_classification_is_rejected_centrally(
    client: Client | None, project: Project | None, task: Task | None, construction: str
) -> None:
    original = unclassified_entry()
    if construction == "replace-classified":
        original = classify_time_entry(original, client=CLIENT, project=PROJECT, task=TASK)
    snapshot = replace(original)
    with pytest.raises(TimeEntryOwnershipError):
        if construction == "constructor":
            TimeEntry(
                id=original.id,
                workspace_id=original.workspace_id,
                start=original.start,
                end=original.end,
                billable=original.billable,
                client=client,
                project=project,
                task=task,
            )
        else:
            replace(original, client=client, project=project, task=task)
    assert original == snapshot


def test_explicit_none_task_clears_existing_task() -> None:
    original = classify_time_entry(unclassified_entry(), client=CLIENT, project=PROJECT, task=TASK)
    result = classify_time_entry(original, client=CLIENT, project=PROJECT, task=None)
    assert result == replace(original, task=None)
    assert result is not original
    assert result.task is None
    assert original.task is TASK
