"""Application-owned transaction for issued-invoice artifact operations."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.issued_invoice_artifact_repository import (
    IssuedInvoiceArtifactRepository,
)
from freelanceflow.modules.billing.application.issued_invoice_artifacts import (
    IssuedInvoiceArtifactStore,
)


class SqlAlchemyIssuedInvoiceArtifactTransaction:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[IssuedInvoiceArtifactStore]:
        with Session(self.engine) as session, session.begin():
            yield IssuedInvoiceArtifactRepository(
                session, workspace_id=workspace_id
            )
