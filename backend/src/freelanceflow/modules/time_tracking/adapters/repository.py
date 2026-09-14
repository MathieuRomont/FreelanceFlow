"""TimeEntry mappings preserve instants plus IANA or fixed-offset context."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from freelanceflow.modules.clients.application.catalog import ClientCatalog
from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.adapters.models import TimeEntryRow
from freelanceflow.modules.time_tracking.domain import TimeEntry


def _offset(value: datetime) -> int:
    offset = value.utcoffset()
    assert offset is not None
    return offset // timedelta(microseconds=1)


def _restore(value: datetime, zone: str | None, offset: int) -> datetime:
    return value.astimezone(ZoneInfo(zone) if zone else timezone(timedelta(microseconds=offset)))


def to_row(value: TimeEntry) -> TimeEntryRow:
    return TimeEntryRow(
        id=value.id,
        workspace_id=value.workspace_id,
        start=value.start.astimezone(UTC),
        end=value.end.astimezone(UTC),
        start_zone=value.start.tzinfo.key if isinstance(value.start.tzinfo, ZoneInfo) else None,
        end_zone=value.end.tzinfo.key if isinstance(value.end.tzinfo, ZoneInfo) else None,
        start_offset_microseconds=_offset(value.start),
        end_offset_microseconds=_offset(value.end),
        billable=value.billable,
        client_id=value.client.id if value.client else None,
        project_id=value.project.id if value.project else None,
        task_id=value.task.id if value.task else None,
    )


class TimeEntryRepository:
    def __init__(self, session: Session, *, workspace_id: UUID, clients: ClientCatalog) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.clients = clients

    def add(self, value: TimeEntry) -> None:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(to_row(value))
        self.session.flush()

    def get_client(self, entity_id: UUID) -> Client | None:
        return self.clients.get_client(entity_id)

    def get_project(self, entity_id: UUID) -> Project | None:
        return self.clients.get_project(entity_id)

    def get_task(self, entity_id: UUID) -> Task | None:
        return self.clients.get_task(entity_id)

    def get(self, entity_id: UUID) -> TimeEntry | None:
        row = self.session.scalar(
            select(TimeEntryRow).where(
                TimeEntryRow.id == entity_id, TimeEntryRow.workspace_id == self.workspace_id
            )
        )
        if row is None:
            return None
        client = self.clients.get_client(row.client_id) if row.client_id else None
        project = self.clients.get_project(row.project_id) if row.project_id else None
        task = self.clients.get_task(row.task_id) if row.task_id else None
        if any(
            (identifier is not None and value is None)
            for identifier, value in (
                (row.client_id, client),
                (row.project_id, project),
                (row.task_id, task),
            )
        ):
            raise ValueError("Referenced ownership chain is unavailable in this workspace")
        return TimeEntry(
            row.id,
            row.workspace_id,
            _restore(row.start, row.start_zone, row.start_offset_microseconds),
            _restore(row.end, row.end_zone, row.end_offset_microseconds),
            row.billable,
            client,
            project,
            task,
        )

    def list(self) -> list[TimeEntry]:
        identifiers = self.session.scalars(
            select(TimeEntryRow.id)
            .where(TimeEntryRow.workspace_id == self.workspace_id)
            .order_by(TimeEntryRow.id)
        )
        entries: list[TimeEntry] = []
        for entity_id in identifiers:
            entry = self.get(entity_id)
            assert entry is not None
            entries.append(entry)
        return entries

    def update_classification(self, value: TimeEntry) -> None:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        row = self.session.scalar(
            select(TimeEntryRow).where(
                TimeEntryRow.id == value.id,
                TimeEntryRow.workspace_id == self.workspace_id,
            )
        )
        if row is None:
            raise ValueError("TimeEntry is unavailable in this workspace")
        row.client_id = value.client.id if value.client else None
        row.project_id = value.project.id if value.project else None
        row.task_id = value.task.id if value.task else None
        self.session.flush()
