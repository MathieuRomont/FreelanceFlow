from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from freelanceflow.modules.billing.application.rate_agreements import (
    IdentifiedRateAgreement,
    RateAgreementResourceNotFound,
    RateAgreementService,
    RateAgreementStore,
)
from freelanceflow.modules.billing.domain import RateAgreement, RateOwnershipError
from freelanceflow.modules.clients.domain import Client, Project


class MemoryRates:
    def __init__(self, workspace_id: UUID) -> None:
        self.workspace_id = workspace_id
        self.clients: dict[UUID, Client] = {}
        self.projects: dict[UUID, Project] = {}
        self.rates: dict[UUID, RateAgreement] = {}

    def get_client(self, entity_id: UUID) -> Client | None:
        client = self.clients.get(entity_id)
        return client if client and client.workspace_id == self.workspace_id else None

    def get_project(self, entity_id: UUID) -> Project | None:
        project = self.projects.get(entity_id)
        return project if project and project.client.workspace_id == self.workspace_id else None

    def add(self, agreement_id: UUID, value: RateAgreement) -> None:
        self.rates[agreement_id] = value

    def get(self, agreement_id: UUID) -> RateAgreement | None:
        value = self.rates.get(agreement_id)
        return value if value and value.client.workspace_id == self.workspace_id else None

    def list(self) -> list[IdentifiedRateAgreement]:
        return [
            IdentifiedRateAgreement(identifier, agreement)
            for identifier, agreement in self.rates.items()
            if agreement.client.workspace_id == self.workspace_id
        ]


def test_application_create_get_list_and_ownership() -> None:
    workspace, other_workspace = uuid4(), uuid4()
    client = Client(uuid4(), workspace, "Acme")
    other_client = Client(uuid4(), workspace, "Other")
    project = Project(uuid4(), client, "Website")
    other_project = Project(uuid4(), other_client, "Other project")
    store = MemoryRates(workspace)
    store.clients = {client.id: client, other_client.id: other_client}
    store.projects = {project.id: project, other_project.id: other_project}

    @contextmanager
    def transaction(workspace_id: UUID) -> Iterator[RateAgreementStore]:
        store.workspace_id = workspace_id
        yield store

    service = RateAgreementService(transaction)
    client_rate = service.create(
        workspace_id=workspace,
        client_id=client.id,
        project_id=None,
        hourly_amount=Decimal("-0.1200"),
        currency="EUR",
        valid_from=date(2026, 1, 1),
        valid_until=None,
    )
    project_rate = service.create(
        workspace_id=workspace,
        client_id=client.id,
        project_id=project.id,
        hourly_amount=Decimal("100.0000000000000000001"),
        currency="USD",
        valid_from=date(2026, 2, 1),
        valid_until=date(2026, 3, 1),
    )
    assert isinstance(client_rate.id, UUID) and client_rate.id != project_rate.id
    assert str(client_rate.agreement.hourly_amount) == "-0.1200"
    assert project_rate.agreement.project == project
    assert service.get(workspace, project_rate.id) == project_rate
    assert service.list(workspace) == [client_rate, project_rate]

    with pytest.raises(RateAgreementResourceNotFound):
        service.get(other_workspace, client_rate.id)
    with pytest.raises(RateAgreementResourceNotFound):
        service.create(
            workspace_id=workspace,
            client_id=uuid4(),
            project_id=None,
            hourly_amount=Decimal("80"),
            currency="EUR",
            valid_from=date(2026, 1, 1),
            valid_until=None,
        )
    with pytest.raises(RateOwnershipError):
        service.create(
            workspace_id=workspace,
            client_id=client.id,
            project_id=other_project.id,
            hourly_amount=Decimal("80"),
            currency="EUR",
            valid_from=date(2026, 1, 1),
            valid_until=None,
        )
