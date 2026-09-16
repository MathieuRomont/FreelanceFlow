"""Application-owned transaction for final issued-invoice approval."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.issued_invoice_approval_repository import (
    IssuedInvoiceApprovalRepository,
)
from freelanceflow.modules.billing.application.issued_invoice_approvals import (
    IssuedInvoiceApprovalStore,
)


class SqlAlchemyIssuedInvoiceApprovalTransaction:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[IssuedInvoiceApprovalStore]:
        with Session(self.engine) as session, session.begin():
            yield IssuedInvoiceApprovalRepository(session, workspace_id=workspace_id)
