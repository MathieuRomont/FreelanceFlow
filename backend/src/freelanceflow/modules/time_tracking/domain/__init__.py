"""Pure work intervals and exact elapsed duration."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from freelanceflow.modules.clients.domain import Client, Project, Task


class TimeEntryError(ValueError):
    """Base error for invalid time entries."""


class InvalidTimeEntryError(TimeEntryError):
    """A time entry contains invalid timestamps, interval, or billable state."""


class TimeEntryOwnershipError(TimeEntryError):
    """Classification does not form a consistent workspace/client/project/task chain."""


@dataclass(frozen=True)
class TimeEntry:
    """A work interval with optional classification and explicit billable state.

    Supplied timestamps retain their timezone context. Duration uses UTC instants,
    preserving microseconds even across DST changes. Validated edits can use
    dataclasses.replace; no review or billing eligibility workflow is implied.
    """

    id: UUID
    workspace_id: UUID
    start: datetime
    end: datetime
    billable: bool
    client: Client | None = None
    project: Project | None = None
    task: Task | None = None

    def __post_init__(self) -> None:
        for timestamp in (self.start, self.end):
            if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
                raise InvalidTimeEntryError("Start and end must be timezone-aware timestamps")
        if self.duration <= timedelta(0):
            raise InvalidTimeEntryError("End instant must be strictly after start instant")
        if not isinstance(self.billable, bool):
            raise InvalidTimeEntryError("Billable must be an explicit boolean")
        if self.client is not None and self.client.workspace_id != self.workspace_id:
            raise TimeEntryOwnershipError("Client must belong to the time entry workspace")
        if self.project is not None and (
            self.client is None
            or self.project.client.id != self.client.id
            or self.project.client.workspace_id != self.workspace_id
        ):
            raise TimeEntryOwnershipError(
                "Project must belong to the selected client and workspace"
            )
        if self.task is not None and (
            self.project is None
            or self.task.project.id != self.project.id
            or self.task.project.client.id != self.project.client.id
            or self.task.project.client.workspace_id != self.workspace_id
        ):
            raise TimeEntryOwnershipError("Task must belong to the selected project and ownership")

    @property
    def duration(self) -> timedelta:
        """Actual elapsed time, with no rounding or conversion to floating-point hours."""
        return self.end.astimezone(UTC) - self.start.astimezone(UTC)
