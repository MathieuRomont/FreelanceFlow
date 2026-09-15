"""Application-owned transactions for workspace invoice settings."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.invoice_settings_repository import (
    InvoiceSettingsRepository,
)


class SqlAlchemyInvoiceSettingsTransaction:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[InvoiceSettingsRepository]:
        with Session(self.engine) as session, session.begin():
            yield InvoiceSettingsRepository(session, workspace_id=workspace_id)
