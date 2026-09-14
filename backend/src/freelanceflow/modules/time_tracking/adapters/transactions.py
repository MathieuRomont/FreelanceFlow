"""Commit TimeEntry use cases on success and roll them back on failure."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.clients.application.catalog import ClientCatalog
from freelanceflow.modules.time_tracking.adapters.repository import TimeEntryRepository
from freelanceflow.modules.time_tracking.application.time_entries import TimeEntryStore


class ClientCatalogFactory(Protocol):
    def __call__(self, session: Session, *, workspace_id: UUID) -> ClientCatalog: ...


class SqlAlchemyTimeEntryTransaction:
    def __init__(self, engine: Engine, clients: ClientCatalogFactory) -> None:
        self.engine = engine
        self.clients = clients

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[TimeEntryStore]:
        with Session(self.engine) as session, session.begin():
            clients = self.clients(session, workspace_id=workspace_id)
            yield TimeEntryRepository(session, workspace_id=workspace_id, clients=clients)
