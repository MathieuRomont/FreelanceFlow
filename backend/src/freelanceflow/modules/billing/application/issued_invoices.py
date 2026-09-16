"""Atomic HTTP-independent invoice issuance use cases."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.billing.domain.billing_profiles import (
    ClientBillingProfile,
    WorkspaceBillingProfile,
)
from freelanceflow.modules.billing.domain.invoice_dates import (
    derive_invoice_issue_date,
    derive_payment_due_date,
)
from freelanceflow.modules.billing.domain.invoice_drafts import InvoiceDraft
from freelanceflow.modules.billing.domain.invoice_settings import WorkspaceInvoiceSettings
from freelanceflow.modules.billing.domain.issued_invoices import (
    InvoiceLineDescription,
    IssuedInvoice,
    LegalInvoiceNumber,
    issue_invoice,
)
from freelanceflow.modules.billing.domain.vat import calculate_invoice_vat


class IssuedInvoiceResourceNotFound(LookupError):
    """A workspace-scoped source draft or issued invoice is unavailable."""


class InvoiceIssuanceConflictError(ValueError):
    """The source is stale/frozen or a duplicate request conflicts with history."""


class InvoiceIssuanceConfigurationError(ValueError):
    """Required current legal configuration is unavailable."""


class InvoiceNumberChronologyError(InvoiceIssuanceConflictError):
    """The requested issue date would violate legal-number chronology."""


@dataclass(frozen=True)
class LockedInvoiceDraft:
    draft: InvoiceDraft
    issued_invoice_id: UUID | None


@dataclass(frozen=True)
class IssueInvoiceCommand:
    source_revision: int
    service_completion_date: date
    line_descriptions: tuple[InvoiceLineDescription, ...]
    purchase_order_number: str | None = None


class InvoiceIssuanceStore(Protocol):
    def lock_draft(self, invoice_id: UUID) -> LockedInvoiceDraft | None: ...
    def get_workspace_profile_for_snapshot(self) -> WorkspaceBillingProfile | None: ...
    def get_client_profile_for_snapshot(
        self, client_id: UUID
    ) -> ClientBillingProfile | None: ...
    def get_settings_for_snapshot(self) -> WorkspaceInvoiceSettings | None: ...
    def allocate_number(self, issue_date: date) -> LegalInvoiceNumber: ...
    def add(self, value: IssuedInvoice) -> None: ...
    def freeze_draft(self, value: IssuedInvoice) -> None: ...
    def get(self, issued_invoice_id: UUID) -> IssuedInvoice | None: ...
    def list(self) -> list[IssuedInvoice]: ...


class InvoiceIssuanceTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[InvoiceIssuanceStore]: ...


def _same_request(existing: IssuedInvoice, command: IssueInvoiceCommand) -> bool:
    description_ids = tuple(item.invoice_line_id for item in command.line_descriptions)
    if len(description_ids) != len(set(description_ids)):
        return False
    requested_descriptions = {
        item.invoice_line_id: item.description for item in command.line_descriptions
    }
    existing_descriptions = {
        line.source_invoice_line_id: line.description for line in existing.lines
    }
    return (
        existing.source_revision == command.source_revision
        and existing.service_completion_date == command.service_completion_date
        and existing.purchase_order_number == command.purchase_order_number
        and existing_descriptions == requested_descriptions
    )


class InvoiceIssuanceService:
    def __init__(
        self,
        transaction: InvoiceIssuanceTransaction,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self.transaction = transaction
        self.clock = clock

    def issue(
        self,
        *,
        workspace_id: UUID,
        invoice_id: UUID,
        command: IssueInvoiceCommand,
    ) -> IssuedInvoice:
        with self.transaction(workspace_id) as store:
            locked = store.lock_draft(invoice_id)
            if locked is None:
                raise IssuedInvoiceResourceNotFound("Invoice issuance resource not found")
            if locked.issued_invoice_id is not None:
                existing = store.get(locked.issued_invoice_id)
                if existing is None:
                    raise RuntimeError("InvoiceDraft head references a missing issuance")
                if _same_request(existing, command):
                    return existing
                raise InvoiceIssuanceConflictError(
                    "Logical invoice was already issued with different immutable facts"
                )
            if command.source_revision != locked.draft.revision:
                raise InvoiceIssuanceConflictError(
                    "Only the current InvoiceDraft revision may be issued"
                )

            seller = store.get_workspace_profile_for_snapshot()
            client = store.get_client_profile_for_snapshot(locked.draft.client_id)
            settings = store.get_settings_for_snapshot()
            missing = [
                label
                for label, value in (
                    ("workspace billing profile", seller),
                    ("client billing profile", client),
                    ("workspace invoice settings", settings),
                )
                if value is None
            ]
            if missing:
                raise InvoiceIssuanceConfigurationError(
                    f"Missing required {' and '.join(missing)}"
                )
            assert seller is not None and client is not None and settings is not None

            issued_at = self.clock()
            issue_date = derive_invoice_issue_date(issued_at, settings.billing_timezone)
            due_date = derive_payment_due_date(issue_date, settings.payment_terms)
            tax = calculate_invoice_vat(locked.draft, settings)
            number = store.allocate_number(issue_date)
            issued = issue_invoice(
                issued_invoice_id=uuid4(),
                number=number,
                draft=locked.draft,
                seller_profile=seller,
                client_profile=client,
                settings=settings,
                tax=tax,
                issued_at=issued_at,
                issue_date=issue_date,
                service_completion_date=command.service_completion_date,
                due_date=due_date,
                line_descriptions=command.line_descriptions,
                purchase_order_number=command.purchase_order_number,
            )
            store.add(issued)
            store.freeze_draft(issued)
        return issued

    def get(
        self, workspace_id: UUID, issued_invoice_id: UUID
    ) -> IssuedInvoice:
        with self.transaction(workspace_id) as store:
            value = store.get(issued_invoice_id)
            if value is None:
                raise IssuedInvoiceResourceNotFound("Issued invoice not found")
        return value

    def list(self, workspace_id: UUID) -> list[IssuedInvoice]:
        with self.transaction(workspace_id) as store:
            return store.list()
