"""Application-owned SQLAlchemy transactions for InvoiceApproval use cases."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.invoice_approval_repository import (
    InvoiceApprovalRepository,
)
from freelanceflow.modules.billing.application.invoice_approvals import (
    InvoiceApprovalStore,
)


class SqlAlchemyInvoiceApprovalTransaction:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[InvoiceApprovalStore]:
        with Session(self.engine) as session, session.begin():
            yield InvoiceApprovalRepository(session, workspace_id=workspace_id)
