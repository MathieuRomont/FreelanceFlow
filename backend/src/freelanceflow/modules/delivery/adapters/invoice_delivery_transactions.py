"""Application-owned SQLAlchemy transactions for InvoiceDelivery use cases."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.delivery.adapters.invoice_delivery_repository import (
    InvoiceDeliveryRepository,
)
from freelanceflow.modules.delivery.application.invoice_deliveries import (
    InvoiceDeliveryStore,
)


class SqlAlchemyInvoiceDeliveryTransaction:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[InvoiceDeliveryStore]:
        with Session(self.engine) as session, session.begin():
            yield InvoiceDeliveryRepository(session, workspace_id=workspace_id)
