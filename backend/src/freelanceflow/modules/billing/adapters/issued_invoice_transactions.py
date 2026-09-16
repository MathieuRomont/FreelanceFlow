"""Application-owned transaction for atomic legal invoice issuance."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.billing_profile_repository import (
    BillingProfileRepository,
)
from freelanceflow.modules.billing.adapters.invoice_draft_repository import (
    InvoiceDraftRepository,
)
from freelanceflow.modules.billing.adapters.invoice_settings_repository import (
    InvoiceSettingsRepository,
)
from freelanceflow.modules.billing.adapters.issued_invoice_repository import (
    IssuedInvoiceRepository,
)
from freelanceflow.modules.billing.adapters.repository import RateAgreementRepository
from freelanceflow.modules.billing.application.invoice_drafts import TimeEntryCatalog
from freelanceflow.modules.billing.application.issued_invoices import InvoiceIssuanceStore
from freelanceflow.modules.clients.application.catalog import ClientCatalog


class ClientCatalogFactory(Protocol):
    def __call__(self, session: Session, *, workspace_id: UUID) -> ClientCatalog: ...


class TimeEntryCatalogFactory(Protocol):
    def __call__(
        self, session: Session, *, workspace_id: UUID, clients: ClientCatalog
    ) -> TimeEntryCatalog: ...


class SqlAlchemyInvoiceIssuanceTransaction:
    def __init__(
        self,
        engine: Engine,
        clients: ClientCatalogFactory,
        time_entries: TimeEntryCatalogFactory,
    ) -> None:
        self.engine = engine
        self.clients = clients
        self.time_entries = time_entries

    @contextmanager
    def __call__(self, workspace_id: UUID) -> Iterator[InvoiceIssuanceStore]:
        with Session(self.engine) as session, session.begin():
            clients = self.clients(session, workspace_id=workspace_id)
            time_entries = self.time_entries(
                session, workspace_id=workspace_id, clients=clients
            )
            rates = RateAgreementRepository(
                session, workspace_id=workspace_id, clients=clients
            )
            drafts = InvoiceDraftRepository(
                session,
                workspace_id=workspace_id,
                clients=clients,
                time_entries=time_entries,
                rates=rates,
            )
            profiles = BillingProfileRepository(
                session, workspace_id=workspace_id, clients=clients
            )
            settings = InvoiceSettingsRepository(session, workspace_id=workspace_id)
            yield IssuedInvoiceRepository(
                session,
                workspace_id=workspace_id,
                drafts=drafts,
                profiles=profiles,
                settings=settings,
            )
