"""InvoiceDraft use cases with explicit transactions and no HTTP dependencies."""

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
    def get(self, entity_id: UUID) -> InvoiceDraft | None: ...
    def list(self) -> list[InvoiceDraft]: ...


class InvoiceDraftTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[InvoiceDraftStore]: ...


class InvoiceDraftService:
    def __init__(self, transaction: InvoiceDraftTransaction) -> None:
        self.transaction = transaction

    def create(
        self,
        *,
        workspace_id: UUID,
        client_id: UUID,
        lines: tuple[InvoiceLineConstructionInput, ...],
    ) -> InvoiceDraft:
        with self.transaction(workspace_id) as store:
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
            draft = build_invoice_draft(
                draft_id=uuid4(),
                revision=1,
                workspace_id=workspace_id,
                client_id=client_id,
                line_inputs=tuple(line_inputs),
            )
            store.add(draft)
        return draft

    def get(self, workspace_id: UUID, draft_id: UUID) -> InvoiceDraft:
        with self.transaction(workspace_id) as store:
            draft = store.get(draft_id)
            if draft is None:
                raise InvoiceDraftResourceNotFound("Invoice draft resource not found")
        return draft

    def list(self, workspace_id: UUID) -> list[InvoiceDraft]:
        with self.transaction(workspace_id) as store:
            return store.list()
