"""Pure client and project domain objects."""

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
