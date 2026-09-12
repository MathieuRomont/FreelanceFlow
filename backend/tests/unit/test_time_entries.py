from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.domain import (
    InvalidTimeEntryError,
    TimeEntry,
    TimeEntryError,
    TimeEntryOwnershipError,
)

CLIENT = Client(UUID(int=1), UUID(int=2), "Client")
PROJECT = Project(UUID(int=3), CLIENT, "Project")
TASK = Task(UUID(int=4), PROJECT, "Task")
START = datetime(2026, 1, 1, 23, tzinfo=UTC)


def entry() -> TimeEntry:
    return TimeEntry(
        UUID(int=5),
        CLIENT.workspace_id,
        START,
        START + timedelta(hours=2),
        True,
        CLIENT,
        PROJECT,
        TASK,
    )


def test_task_ownership() -> None:
    assert TASK.project is PROJECT
    assert TASK.project.client is CLIENT
    assert TASK.project.client.workspace_id == CLIENT.workspace_id


@pytest.mark.parametrize(
    "duration",
    [
        timedelta(microseconds=1),
        timedelta(seconds=1),
        timedelta(hours=2, microseconds=123456),
        timedelta(days=3),
    ],
)
def test_exact_duration_including_midnight(duration: timedelta) -> None:
    result = replace(entry(), end=START + duration)
    assert isinstance(result.duration, timedelta)
    assert result.duration == duration


def test_different_offsets_use_instants() -> None:
    start = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    end = datetime(2026, 1, 1, 8, tzinfo=UTC)
    assert replace(entry(), start=start, end=end).duration == timedelta(hours=1, minutes=30)


@pytest.mark.parametrize("month, day, expected_hours", [(3, 29, 1), (10, 25, 3)])
def test_dst_elapsed_duration(month: int, day: int, expected_hours: int) -> None:
    paris = ZoneInfo("Europe/Paris")
    start = datetime(2026, month, day, 1, 30, tzinfo=paris)
    end = datetime(2026, month, day, 3, 30, tzinfo=paris)
    result = replace(entry(), start=start, end=end)
    assert result.duration == timedelta(hours=expected_hours)
    assert result.start is start
    assert result.end is end
    assert result.start.tzinfo is paris


def test_repeated_hour_uses_fold_and_allows_reversed_wall_clock() -> None:
    paris = ZoneInfo("Europe/Paris")
    start = datetime(2026, 10, 25, 2, 45, tzinfo=paris, fold=0)
    end = datetime(2026, 10, 25, 2, 15, tzinfo=paris, fold=1)
    assert replace(entry(), start=start, end=end).duration == timedelta(minutes=30)
    with pytest.raises(InvalidTimeEntryError):
        replace(entry(), start=end, end=start)
    same_wall = start.replace(fold=1)
    assert replace(entry(), start=start, end=same_wall).duration == timedelta(hours=1)


class NoOffset(tzinfo):
    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> None:
        return None

    def utcoffset(self, dt: datetime | None) -> None:
        return None


@pytest.mark.parametrize("invalid", [START.replace(tzinfo=None), START.replace(tzinfo=NoOffset())])
@pytest.mark.parametrize("boundary", ["start", "end"])
def test_naive_timestamps(invalid: datetime, boundary: str) -> None:
    with pytest.raises(InvalidTimeEntryError, match="timezone-aware"):
        if boundary == "start":
            replace(entry(), start=invalid)
        else:
            replace(entry(), end=invalid)


@pytest.mark.parametrize(
    "end",
    [START, START - timedelta(microseconds=1), START.astimezone(timezone(timedelta(hours=2)))],
)
def test_nonpositive_interval(end: datetime) -> None:
    with pytest.raises(InvalidTimeEntryError, match="strictly after"):
        replace(entry(), end=end)


@pytest.mark.parametrize("billable", [True, False])
@pytest.mark.parametrize("level", ["workspace", "project", "task"])
def test_optional_classification_and_explicit_billable(billable: bool, level: str) -> None:
    result = TimeEntry(
        UUID(int=5),
        CLIENT.workspace_id,
        START,
        START + timedelta(hours=1),
        billable,
        CLIENT if level != "workspace" else None,
        PROJECT if level in ("project", "task") else None,
        TASK if level == "task" else None,
    )
    assert result.billable is billable
    assert (result.task is not None) == (level == "task")
    assert result.duration == timedelta(hours=1)


@pytest.mark.parametrize(
    "other_client", [replace(CLIENT, id=UUID(int=6)), replace(CLIENT, workspace_id=UUID(int=7))]
)
def test_project_client_mismatch(other_client: Client) -> None:
    with pytest.raises(TimeEntryOwnershipError):
        replace(entry(), project=replace(PROJECT, client=other_client), task=None)


def test_client_workspace_mismatch() -> None:
    with pytest.raises(TimeEntryOwnershipError):
        replace(entry(), workspace_id=UUID(int=7))


@pytest.mark.parametrize(
    "other_project",
    [
        replace(PROJECT, id=UUID(int=6)),
        replace(PROJECT, client=replace(CLIENT, id=UUID(int=6))),
        replace(PROJECT, client=replace(CLIENT, workspace_id=UUID(int=7))),
    ],
)
def test_task_project_mismatch(other_project: Project) -> None:
    with pytest.raises(TimeEntryOwnershipError):
        replace(entry(), task=replace(TASK, project=other_project))


def test_incomplete_ownership_chains() -> None:
    with pytest.raises(TimeEntryOwnershipError):
        replace(entry(), client=None, task=None)
    with pytest.raises(TimeEntryOwnershipError):
        replace(entry(), project=None)
    with pytest.raises(TimeEntryOwnershipError):
        replace(entry(), client=None, project=None)


def test_ownership_compares_ids_not_names() -> None:
    renamed_client = replace(CLIENT, name="Renamed client")
    renamed_project = replace(PROJECT, client=renamed_client, name="Renamed project")
    assert replace(entry(), client=renamed_client, project=renamed_project).task is TASK


def test_validated_edits_preserve_original() -> None:
    original = entry()
    edited = replace(original, end=START + timedelta(minutes=30), billable=False, task=None)
    assert edited.duration == timedelta(minutes=30)
    assert original.duration == timedelta(hours=2)
    assert original.billable
    with pytest.raises(FrozenInstanceError):
        original.end = START  # type: ignore[misc]


def test_invalid_transport_values_raise_domain_errors() -> None:
    with pytest.raises(InvalidTimeEntryError):
        replace(entry(), start="2026-01-01")  # type: ignore[arg-type]
    with pytest.raises(InvalidTimeEntryError):
        replace(entry(), billable=1)  # type: ignore[arg-type]
    assert issubclass(InvalidTimeEntryError, TimeEntryError)
    assert issubclass(TimeEntryOwnershipError, TimeEntryError)
