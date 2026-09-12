"""Pure client, project, and task domain objects."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Client:
    id: UUID
    workspace_id: UUID
    name: str


@dataclass(frozen=True)
class Project:
    """A project inherits workspace ownership from its single client."""

    id: UUID
    client: Client
    name: str


@dataclass(frozen=True)
class Task:
    """A work category inheriting client and workspace ownership from one project."""

    id: UUID
    project: Project
    name: str
