from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictBool, field_validator

from freelanceflow.modules.time_tracking.application.time_entries import (
    TimeEntryResourceNotFound,
    TimeEntryService,
)
from freelanceflow.modules.time_tracking.domain import TimeEntry, TimeEntryError

router = APIRouter(prefix="/workspaces/{workspace_id}/time-entries", tags=["time-entries"])


class CreateTimeEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime
    end: AwareDatetime
    billable: StrictBool
    client_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None

    @field_validator("start", "end", mode="before")
    @classmethod
    def require_iso_string(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("Timestamp must be an offset-aware ISO-8601 string")
        return value


class ClassifyTimeEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    project_id: UUID
    task_id: UUID | None = None


class TimeEntryResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    start: datetime
    end: datetime
    duration: timedelta
    billable: bool
    client_id: UUID | None
    project_id: UUID | None
    task_id: UUID | None

    @classmethod
    def from_entry(cls, entry: TimeEntry) -> "TimeEntryResponse":
        return cls(
            id=entry.id,
            workspace_id=entry.workspace_id,
            start=entry.start,
            end=entry.end,
            duration=entry.duration,
            billable=entry.billable,
            client_id=entry.client.id if entry.client else None,
            project_id=entry.project.id if entry.project else None,
            task_id=entry.task.id if entry.task else None,
        )


def get_time_entry_service() -> TimeEntryService:
    raise RuntimeError("TimeEntry service must be supplied by bootstrap")


Service = Annotated[TimeEntryService, Depends(get_time_entry_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post("", status_code=201, response_model=TimeEntryResponse)
def create_time_entry(
    workspace_id: UUID, body: CreateTimeEntryRequest, service: Service
) -> TimeEntryResponse:
    try:
        entry = service.create(
            workspace_id=workspace_id,
            start=body.start,
            end=body.end,
            billable=body.billable,
            client_id=body.client_id,
            project_id=body.project_id,
            task_id=body.task_id,
        )
    except TimeEntryResourceNotFound as error:
        raise _not_found() from error
    except TimeEntryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return TimeEntryResponse.from_entry(entry)


@router.get("", response_model=list[TimeEntryResponse])
def list_time_entries(workspace_id: UUID, service: Service) -> list[TimeEntryResponse]:
    return [TimeEntryResponse.from_entry(entry) for entry in service.list(workspace_id)]


@router.get("/{time_entry_id}", response_model=TimeEntryResponse)
def get_time_entry(
    workspace_id: UUID, time_entry_id: UUID, service: Service
) -> TimeEntryResponse:
    try:
        entry = service.get(workspace_id, time_entry_id)
    except TimeEntryResourceNotFound as error:
        raise _not_found() from error
    return TimeEntryResponse.from_entry(entry)


@router.put("/{time_entry_id}/classification", response_model=TimeEntryResponse)
def classify_entry(
    workspace_id: UUID,
    time_entry_id: UUID,
    body: ClassifyTimeEntryRequest,
    service: Service,
) -> TimeEntryResponse:
    try:
        entry = service.classify(
            workspace_id=workspace_id,
            entry_id=time_entry_id,
            client_id=body.client_id,
            project_id=body.project_id,
            task_id=body.task_id,
        )
    except TimeEntryResourceNotFound as error:
        raise _not_found() from error
    except TimeEntryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return TimeEntryResponse.from_entry(entry)


@router.delete("/{time_entry_id}/classification", response_model=TimeEntryResponse)
def clear_entry_classification(
    workspace_id: UUID, time_entry_id: UUID, service: Service
) -> TimeEntryResponse:
    try:
        entry = service.clear_classification(workspace_id, time_entry_id)
    except TimeEntryResourceNotFound as error:
        raise _not_found() from error
    return TimeEntryResponse.from_entry(entry)
