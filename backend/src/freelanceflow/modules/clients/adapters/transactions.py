"""Commit on successful use-case exit; roll back on any failure."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.clients.adapters.repository import ClientRepository


class SqlAlchemyClientTransaction:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[ClientRepository]:
        with Session(self.engine) as session, session.begin():
            yield ClientRepository(session, workspace_id=workspace_id)
