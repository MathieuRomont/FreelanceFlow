"""Application-owned SQLAlchemy transactions for InvoiceArtifact use cases."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.invoice_artifact_repository import (
    InvoiceArtifactRepository,
)
from freelanceflow.modules.billing.application.invoice_artifacts import (
    InvoiceArtifactStore,
)


class SqlAlchemyInvoiceArtifactTransaction:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[InvoiceArtifactStore]:
        with Session(self.engine) as session, session.begin():
            yield InvoiceArtifactRepository(session, workspace_id=workspace_id)
