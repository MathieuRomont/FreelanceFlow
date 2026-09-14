from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from freelanceflow.modules.clients.application.projects_tasks import (
    ClientNotFound,
    ProjectNotFound,
    ProjectTaskService,
)
from freelanceflow.modules.clients.domain import Project, Task

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["projects", "tasks"])


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class ProjectResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    client_id: UUID
    name: str

    @classmethod
    def from_project(cls, project: Project) -> "ProjectResponse":
        return cls(
            id=project.id,
            workspace_id=project.client.workspace_id,
            client_id=project.client.id,
            name=project.name,
        )


class TaskResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    client_id: UUID
    project_id: UUID
    name: str

    @classmethod
    def from_task(cls, task: Task) -> "TaskResponse":
        return cls(
            id=task.id,
            workspace_id=task.project.client.workspace_id,
            client_id=task.project.client.id,
            project_id=task.project.id,
            name=task.name,
        )


def get_project_task_service() -> ProjectTaskService:
    raise RuntimeError("Project/task service must be supplied by bootstrap")


Service = Annotated[ProjectTaskService, Depends(get_project_task_service)]


def not_found(error: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post("/clients/{client_id}/projects", status_code=201, response_model=ProjectResponse)
def create_project(
    workspace_id: UUID, client_id: UUID, body: CreateProjectRequest, service: Service
) -> ProjectResponse:
    try:
        project = service.create_project(workspace_id, client_id, body.name)
        return ProjectResponse.from_project(project)
    except ClientNotFound as error:
        raise not_found(error) from error


@router.get("/clients/{client_id}/projects", response_model=list[ProjectResponse])
def list_projects(
    workspace_id: UUID, client_id: UUID, service: Service
) -> list[ProjectResponse]:
    try:
        return [
            ProjectResponse.from_project(project)
            for project in service.list_projects(workspace_id, client_id)
        ]
    except ClientNotFound as error:
        raise not_found(error) from error


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(workspace_id: UUID, project_id: UUID, service: Service) -> ProjectResponse:
    try:
        return ProjectResponse.from_project(service.get_project(workspace_id, project_id))
    except ProjectNotFound as error:
        raise not_found(error) from error


@router.post("/projects/{project_id}/tasks", status_code=201, response_model=TaskResponse)
def create_task(
    workspace_id: UUID, project_id: UUID, body: CreateTaskRequest, service: Service
) -> TaskResponse:
    try:
        return TaskResponse.from_task(service.create_task(workspace_id, project_id, body.name))
    except ProjectNotFound as error:
        raise not_found(error) from error


@router.get("/projects/{project_id}/tasks", response_model=list[TaskResponse])
def list_tasks(workspace_id: UUID, project_id: UUID, service: Service) -> list[TaskResponse]:
    try:
        tasks = service.list_tasks(workspace_id, project_id)
        return [TaskResponse.from_task(task) for task in tasks]
    except ProjectNotFound as error:
        raise not_found(error) from error


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(workspace_id: UUID, task_id: UUID, service: Service) -> TaskResponse:
    try:
        return TaskResponse.from_task(service.get_task(workspace_id, task_id))
    except ProjectNotFound as error:
        raise not_found(error) from error
