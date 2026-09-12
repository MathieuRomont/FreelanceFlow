"""Rate storage identity is explicit because the domain agreement has no ID."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.models import RateAgreementRow
from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.clients.application.catalog import ClientCatalog


class RateAgreementRepository:
    def __init__(self, session: Session, *, workspace_id: UUID, clients: ClientCatalog) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.clients = clients

    def add(self, agreement_id: UUID, value: RateAgreement) -> None:
        if value.client.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(
            RateAgreementRow(
                id=agreement_id,
                workspace_id=self.workspace_id,
                client_id=value.client.id,
                project_id=value.project.id if value.project else None,
                hourly_amount=value.hourly_amount,
                currency=value.currency,
                valid_from=value.valid_from,
                valid_until=value.valid_until,
            )
        )
        self.session.flush()

    def get(self, agreement_id: UUID) -> RateAgreement | None:
        row = self.session.scalar(
            select(RateAgreementRow).where(
                RateAgreementRow.id == agreement_id,
                RateAgreementRow.workspace_id == self.workspace_id,
            )
        )
        if row is None:
            return None
        client = self.clients.get_client(row.client_id)
        project = self.clients.get_project(row.project_id) if row.project_id else None
        if client is None or (row.project_id is not None and project is None):
            raise ValueError("Referenced ownership chain is unavailable in this workspace")
        return RateAgreement(
            client, row.hourly_amount, row.currency, row.valid_from, row.valid_until, project
        )
