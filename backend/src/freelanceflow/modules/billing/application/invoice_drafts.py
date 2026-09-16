"""InvoiceDraft use cases with explicit transactions and no HTTP dependencies."""

import builtins
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceDraft,
    InvoiceLineInput,
    build_invoice_draft,
)
from freelanceflow.modules.billing.domain.pricing import (
    PreparedBillingSegment,
    RateAgreementReference,
    price_prepared_segment,
)
from freelanceflow.modules.clients.domain import Client
from freelanceflow.modules.time_tracking.domain import TimeEntry


class InvoiceDraftResourceNotFound(LookupError):
    """A requested workspace-scoped draft construction resource is unavailable."""


class InvoiceDraftIdentityChangeError(ValueError):
    """A revision attempted to change its logical invoice identity."""


class InvoiceDraftAlreadyIssuedError(ValueError):
    """An issued logical invoice cannot receive another draft revision."""


@dataclass(frozen=True)
class InvoiceAllocationInput:
    """Caller-prepared interval metadata; source ownership and rates are loaded server-side."""

    time_entry_id: UUID
    start: datetime
    end: datetime
    business_date: date


@dataclass(frozen=True)
class InvoiceLineConstructionInput:
    """One caller-defined logical line grouping."""

    allocations: tuple[InvoiceAllocationInput, ...]


class TimeEntryCatalog(Protocol):
    def get(self, entity_id: UUID) -> TimeEntry | None: ...


class InvoiceDraftStore(Protocol):
    def get_client(self, entity_id: UUID) -> Client | None: ...
    def get_time_entry(self, entity_id: UUID) -> TimeEntry | None: ...
    def list_rates(self) -> list[RateAgreementReference]: ...
    def add(self, value: InvoiceDraft) -> None: ...
    def get_for_revision(self, entity_id: UUID) -> InvoiceDraft | None: ...
    def add_revision(self, value: InvoiceDraft) -> None: ...
    def get(self, entity_id: UUID) -> InvoiceDraft | None: ...
    def get_revision(self, entity_id: UUID, revision: int) -> InvoiceDraft | None: ...
    def list_revisions(self, entity_id: UUID) -> list[InvoiceDraft] | None: ...
    def list(self) -> list[InvoiceDraft]: ...


class InvoiceDraftTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[InvoiceDraftStore]: ...


class InvoiceDraftService:
    def __init__(self, transaction: InvoiceDraftTransaction) -> None:
        self.transaction = transaction

    @staticmethod
    def _build(
        *,
        store: InvoiceDraftStore,
        draft_id: UUID,
        revision: int,
        workspace_id: UUID,
        client_id: UUID,
        lines: tuple[InvoiceLineConstructionInput, ...],
    ) -> InvoiceDraft:
        if store.get_client(client_id) is None:
            raise InvoiceDraftResourceNotFound("Invoice draft resource not found")
        rates = store.list_rates()
        line_inputs: list[InvoiceLineInput] = []
        for line in lines:
            priced_segments = []
            for allocation in line.allocations:
                entry = store.get_time_entry(allocation.time_entry_id)
                if entry is None:
                    raise InvoiceDraftResourceNotFound(
                        "Invoice draft resource not found"
                    )
                prepared = PreparedBillingSegment(
                    source_time_entry=entry,
                    start=allocation.start,
                    end=allocation.end,
                    business_date=allocation.business_date,
                )
                priced_segments.append(price_prepared_segment(prepared, rates))
            line_inputs.append(InvoiceLineInput(uuid4(), tuple(priced_segments)))
        return build_invoice_draft(
            draft_id=draft_id,
            revision=revision,
            workspace_id=workspace_id,
            client_id=client_id,
            line_inputs=tuple(line_inputs),
        )

    def create(
        self,
        *,
        workspace_id: UUID,
        client_id: UUID,
        lines: tuple[InvoiceLineConstructionInput, ...],
    ) -> InvoiceDraft:
        with self.transaction(workspace_id) as store:
            draft = self._build(
                store=store,
                draft_id=uuid4(),
                revision=1,
                workspace_id=workspace_id,
                client_id=client_id,
                lines=lines,
            )
            store.add(draft)
        return draft

    def create_revision(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        lines: tuple[InvoiceLineConstructionInput, ...],
    ) -> InvoiceDraft:
        with self.transaction(workspace_id) as store:
            current = store.get_for_revision(draft_id)
            if current is None:
                raise InvoiceDraftResourceNotFound("Invoice draft resource not found")
            revised = self._build(
                store=store,
                draft_id=current.id,
                revision=current.revision + 1,
                workspace_id=current.workspace_id,
                client_id=current.client_id,
                lines=lines,
            )
            if revised.currency != current.currency:
                raise InvoiceDraftIdentityChangeError(
                    "InvoiceDraft currency cannot change across revisions"
                )
            store.add_revision(revised)
        return revised

    def get(self, workspace_id: UUID, draft_id: UUID) -> InvoiceDraft:
        with self.transaction(workspace_id) as store:
            draft = store.get(draft_id)
            if draft is None:
                raise InvoiceDraftResourceNotFound("Invoice draft resource not found")
        return draft

    def list(self, workspace_id: UUID) -> list[InvoiceDraft]:
        with self.transaction(workspace_id) as store:
            return store.list()

    def get_revision(
        self, workspace_id: UUID, draft_id: UUID, revision: int
    ) -> InvoiceDraft:
        with self.transaction(workspace_id) as store:
            draft = store.get_revision(draft_id, revision)
            if draft is None:
                raise InvoiceDraftResourceNotFound("Invoice draft resource not found")
        return draft

    def list_revisions(
        self, workspace_id: UUID, draft_id: UUID
    ) -> builtins.list[InvoiceDraft]:
        with self.transaction(workspace_id) as store:
            revisions = store.list_revisions(draft_id)
            if revisions is None:
                raise InvoiceDraftResourceNotFound("Invoice draft resource not found")
        return revisions
