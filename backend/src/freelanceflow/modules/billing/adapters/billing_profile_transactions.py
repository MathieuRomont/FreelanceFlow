"""Application-owned transactions for legal billing profiles."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.billing_profile_repository import (
    BillingProfileRepository,
)
from freelanceflow.modules.clients.application.catalog import ClientCatalog


class ClientCatalogFactory(Protocol):
    def __call__(self, session: Session, *, workspace_id: UUID) -> ClientCatalog: ...


class SqlAlchemyBillingProfileTransaction:
    def __init__(self, engine: Engine, clients: ClientCatalogFactory) -> None:
        self.engine = engine
        self.clients = clients

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[BillingProfileRepository]:
        with Session(self.engine) as session, session.begin():
            clients = self.clients(session, workspace_id=workspace_id)
            yield BillingProfileRepository(
                session,
                workspace_id=workspace_id,
                clients=clients,
            )
