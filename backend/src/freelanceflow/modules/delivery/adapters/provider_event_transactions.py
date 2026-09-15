"""Application-owned transactions for delivery-provider event ingestion."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.delivery.adapters.provider_event_repository import (
    InvoiceDeliveryProviderEventRepository,
)
from freelanceflow.modules.delivery.application.provider_events import (
    InvoiceDeliveryProviderEventStore,
)


class SqlAlchemyInvoiceDeliveryProviderEventTransaction:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def __call__(self) -> Iterator[InvoiceDeliveryProviderEventStore]:
        with Session(self.engine) as session, session.begin():
            yield InvoiceDeliveryProviderEventRepository(session)
