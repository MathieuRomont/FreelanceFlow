"""RateAgreement use cases with explicit transactions and no HTTP dependencies."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.clients.domain import Client, Project


class RateAgreementResourceNotFound(LookupError):
    """A requested workspace-scoped rate resource is unavailable."""


@dataclass(frozen=True)
class IdentifiedRateAgreement:
    """Application-facing storage identity paired with its domain agreement."""

    id: UUID
    agreement: RateAgreement


class RateAgreementStore(Protocol):
    def get_client(self, entity_id: UUID) -> Client | None: ...
    def get_project(self, entity_id: UUID) -> Project | None: ...
    def add(self, agreement_id: UUID, value: RateAgreement) -> None: ...
    def get(self, agreement_id: UUID) -> RateAgreement | None: ...
    def list(self) -> list[IdentifiedRateAgreement]: ...


class RateAgreementTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[RateAgreementStore]: ...


class RateAgreementService:
    def __init__(self, transaction: RateAgreementTransaction) -> None:
        self.transaction = transaction

    def create(
        self,
        *,
        workspace_id: UUID,
        client_id: UUID,
        project_id: UUID | None,
        hourly_amount: Decimal,
        currency: str,
        valid_from: date,
        valid_until: date | None,
    ) -> IdentifiedRateAgreement:
        with self.transaction(workspace_id) as store:
            client = store.get_client(client_id)
            if client is None:
                raise RateAgreementResourceNotFound("Rate agreement resource not found")
            project = None
            if project_id is not None:
                project = store.get_project(project_id)
                if project is None:
                    raise RateAgreementResourceNotFound("Rate agreement resource not found")
            agreement = RateAgreement(
                client=client,
                project=project,
                hourly_amount=hourly_amount,
                currency=currency,
                valid_from=valid_from,
                valid_until=valid_until,
            )
            identified = IdentifiedRateAgreement(uuid4(), agreement)
            store.add(identified.id, agreement)
        return identified

    def get(self, workspace_id: UUID, agreement_id: UUID) -> IdentifiedRateAgreement:
        with self.transaction(workspace_id) as store:
            agreement = store.get(agreement_id)
            if agreement is None:
                raise RateAgreementResourceNotFound("Rate agreement resource not found")
        return IdentifiedRateAgreement(agreement_id, agreement)

    def list(self, workspace_id: UUID) -> list[IdentifiedRateAgreement]:
        with self.transaction(workspace_id) as store:
            return store.list()
