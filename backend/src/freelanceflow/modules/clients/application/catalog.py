"""Read interface for resolving existing client ownership chains."""

from typing import Protocol
from uuid import UUID

from freelanceflow.modules.clients.domain import Client, Project, Task


class ClientCatalog(Protocol):
    def get_client(self, entity_id: UUID) -> Client | None: ...
    def get_project(self, entity_id: UUID) -> Project | None: ...
    def get_task(self, entity_id: UUID) -> Task | None: ...
