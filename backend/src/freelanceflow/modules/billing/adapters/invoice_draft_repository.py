"""Relational InvoiceDraft snapshots independent of mutable source rows."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.models import (
    InvoiceAllocationRow,
    InvoiceDraftRow,
    InvoiceLineRow,
)
from freelanceflow.modules.billing.adapters.repository import RateAgreementRepository
from freelanceflow.modules.billing.application.invoice_drafts import TimeEntryCatalog
from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceAllocation,
    InvoiceCurrency,
    InvoiceDraft,
    InvoiceLine,
    RoundedMoneyAmount,
)
from freelanceflow.modules.billing.domain.pricing import (
    ExactMoneyAmount,
    PreparedBillingSegment,
    PricedSegment,
    RateAgreementReference,
)
from freelanceflow.modules.clients.application.catalog import ClientCatalog
from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.domain import TimeEntry


def _offset(value: datetime) -> int:
    offset = value.utcoffset()
    assert offset is not None
    return offset // timedelta(microseconds=1)


def _zone(value: datetime) -> str | None:
    return value.tzinfo.key if isinstance(value.tzinfo, ZoneInfo) else None


def _restore(value: datetime, zone: str | None, offset: int) -> datetime:
    target = ZoneInfo(zone) if zone else timezone(timedelta(microseconds=offset))
    return value.astimezone(target)


def _integer(value: Decimal) -> int:
    integer = int(value)
    if Decimal(integer) != value:
        raise ValueError("Persisted exact monetary component is not integral")
    return integer


class InvoiceDraftRepository:
    def __init__(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        clients: ClientCatalog,
        time_entries: TimeEntryCatalog,
        rates: RateAgreementRepository,
    ) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.clients = clients
        self.time_entries = time_entries
        self.rates = rates

    def get_client(self, entity_id: UUID) -> Client | None:
        return self.clients.get_client(entity_id)

    def get_time_entry(self, entity_id: UUID) -> TimeEntry | None:
        return self.time_entries.get(entity_id)

    def list_rates(self) -> list[RateAgreementReference]:
        return [
            RateAgreementReference(value.id, value.agreement) for value in self.rates.list()
        ]

    def add(self, value: InvoiceDraft) -> None:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        self.session.add(
            InvoiceDraftRow(
                id=value.id,
                revision=value.revision,
                workspace_id=value.workspace_id,
                client_id=value.client_id,
                currency=value.currency.code,
                currency_decimal_places=value.currency.decimal_places,
                exact_subtotal_numerator=Decimal(value.exact_subtotal.numerator),
                exact_subtotal_denominator=Decimal(value.exact_subtotal.denominator),
                subtotal_minor_units=Decimal(value.subtotal.minor_units),
                total_minor_units=Decimal(value.total.minor_units),
            )
        )
        self.session.flush()
        for line_position, line in enumerate(value.lines):
            first = line.allocations[0].priced_segment
            source = first.segment.source_time_entry
            client = source.client
            project = source.project
            assert client is not None and project is not None
            task = source.task
            rate = first.applied_rate.agreement
            self.session.add(
                InvoiceLineRow(
                    invoice_draft_id=value.id,
                    invoice_revision=value.revision,
                    id=line.id,
                    position=line_position,
                    workspace_id=line.workspace_id,
                    client_id=line.client_id,
                    client_name=client.name,
                    project_id=line.project_id,
                    project_name=project.name,
                    task_id=line.task_id,
                    task_name=task.name if task else None,
                    rate_agreement_id=line.applied_rate_agreement_id,
                    rate_scope_project_id=rate.project.id if rate.project else None,
                    rate_valid_from=rate.valid_from,
                    rate_valid_until=rate.valid_until,
                    hourly_amount=line.hourly_rate,
                    currency=line.currency.code,
                    currency_decimal_places=line.currency.decimal_places,
                    duration_microseconds=line.duration_microseconds,
                    exact_amount_numerator=Decimal(line.exact_amount.numerator),
                    exact_amount_denominator=Decimal(line.exact_amount.denominator),
                    rounded_minor_units=Decimal(line.rounded_amount.minor_units),
                )
            )
        self.session.flush()
        for line in value.lines:
            for allocation_position, allocation in enumerate(line.allocations):
                priced = allocation.priced_segment
                source = priced.segment.source_time_entry
                self.session.add(
                    InvoiceAllocationRow(
                        invoice_draft_id=value.id,
                        invoice_revision=value.revision,
                        invoice_line_id=line.id,
                        position=allocation_position,
                        source_time_entry_id=source.id,
                        source_start=source.start.astimezone(UTC),
                        source_end=source.end.astimezone(UTC),
                        source_start_zone=_zone(source.start),
                        source_end_zone=_zone(source.end),
                        source_start_offset_microseconds=_offset(source.start),
                        source_end_offset_microseconds=_offset(source.end),
                        source_billable=source.billable,
                        segment_start=priced.segment.start.astimezone(UTC),
                        segment_end=priced.segment.end.astimezone(UTC),
                        segment_start_zone=_zone(priced.segment.start),
                        segment_end_zone=_zone(priced.segment.end),
                        segment_start_offset_microseconds=_offset(priced.segment.start),
                        segment_end_offset_microseconds=_offset(priced.segment.end),
                        business_date=priced.segment.business_date,
                        duration_microseconds=priced.duration_microseconds,
                        exact_amount_numerator=Decimal(priced.exact_amount.numerator),
                        exact_amount_denominator=Decimal(priced.exact_amount.denominator),
                    )
                )
        self.session.flush()

    def _restore_line(self, row: InvoiceLineRow) -> InvoiceLine:
        client = Client(row.client_id, row.workspace_id, row.client_name)
        project = Project(row.project_id, client, row.project_name)
        if row.task_id is not None and row.task_name is None:
            raise ValueError("Persisted Task snapshot is incomplete")
        task = (
            Task(row.task_id, project, row.task_name)
            if row.task_id is not None and row.task_name is not None
            else None
        )
        rate_project = project if row.rate_scope_project_id is not None else None
        rate = RateAgreementReference(
            row.rate_agreement_id,
            RateAgreement(
                client=client,
                project=rate_project,
                hourly_amount=row.hourly_amount,
                currency=row.currency,
                valid_from=row.rate_valid_from,
                valid_until=row.rate_valid_until,
            ),
        )
        allocation_rows = self.session.scalars(
            select(InvoiceAllocationRow)
            .where(
                InvoiceAllocationRow.invoice_draft_id == row.invoice_draft_id,
                InvoiceAllocationRow.invoice_revision == row.invoice_revision,
                InvoiceAllocationRow.invoice_line_id == row.id,
            )
            .order_by(InvoiceAllocationRow.position)
        )
        allocations: list[InvoiceAllocation] = []
        for allocation_row in allocation_rows:
            source = TimeEntry(
                id=allocation_row.source_time_entry_id,
                workspace_id=row.workspace_id,
                start=_restore(
                    allocation_row.source_start,
                    allocation_row.source_start_zone,
                    allocation_row.source_start_offset_microseconds,
                ),
                end=_restore(
                    allocation_row.source_end,
                    allocation_row.source_end_zone,
                    allocation_row.source_end_offset_microseconds,
                ),
                billable=allocation_row.source_billable,
                client=client,
                project=project,
                task=task,
            )
            segment = PreparedBillingSegment(
                source_time_entry=source,
                start=_restore(
                    allocation_row.segment_start,
                    allocation_row.segment_start_zone,
                    allocation_row.segment_start_offset_microseconds,
                ),
                end=_restore(
                    allocation_row.segment_end,
                    allocation_row.segment_end_zone,
                    allocation_row.segment_end_offset_microseconds,
                ),
                business_date=allocation_row.business_date,
            )
            if segment.duration_microseconds != allocation_row.duration_microseconds:
                raise ValueError("Persisted allocation duration is inconsistent")
            allocations.append(
                InvoiceAllocation(
                    PricedSegment(
                        segment=segment,
                        applied_rate=rate,
                        exact_amount=ExactMoneyAmount(
                            _integer(allocation_row.exact_amount_numerator),
                            _integer(allocation_row.exact_amount_denominator),
                        ),
                    )
                )
            )
        currency = InvoiceCurrency(row.currency, row.currency_decimal_places)
        return InvoiceLine(
            id=row.id,
            workspace_id=row.workspace_id,
            client_id=row.client_id,
            project_id=row.project_id,
            task_id=row.task_id,
            applied_rate_agreement_id=row.rate_agreement_id,
            hourly_rate=row.hourly_amount,
            currency=currency,
            allocations=tuple(allocations),
            duration_microseconds=row.duration_microseconds,
            exact_amount=ExactMoneyAmount(
                _integer(row.exact_amount_numerator),
                _integer(row.exact_amount_denominator),
            ),
            rounded_amount=RoundedMoneyAmount(
                currency, _integer(row.rounded_minor_units)
            ),
        )

    def _restore_draft(self, row: InvoiceDraftRow) -> InvoiceDraft:
        line_rows = self.session.scalars(
            select(InvoiceLineRow)
            .where(
                InvoiceLineRow.invoice_draft_id == row.id,
                InvoiceLineRow.invoice_revision == row.revision,
            )
            .order_by(InvoiceLineRow.position)
        )
        currency = InvoiceCurrency(row.currency, row.currency_decimal_places)
        subtotal = RoundedMoneyAmount(currency, _integer(row.subtotal_minor_units))
        return InvoiceDraft(
            id=row.id,
            revision=row.revision,
            workspace_id=row.workspace_id,
            client_id=row.client_id,
            currency=currency,
            lines=tuple(self._restore_line(line) for line in line_rows),
            exact_subtotal=ExactMoneyAmount(
                _integer(row.exact_subtotal_numerator),
                _integer(row.exact_subtotal_denominator),
            ),
            subtotal=subtotal,
            total=RoundedMoneyAmount(currency, _integer(row.total_minor_units)),
        )

    def get(self, entity_id: UUID) -> InvoiceDraft | None:
        row = self.session.scalar(
            select(InvoiceDraftRow)
            .where(
                InvoiceDraftRow.id == entity_id,
                InvoiceDraftRow.workspace_id == self.workspace_id,
            )
            .order_by(InvoiceDraftRow.revision.desc())
            .limit(1)
        )
        return self._restore_draft(row) if row is not None else None

    def list(self) -> list[InvoiceDraft]:
        rows = self.session.scalars(
            select(InvoiceDraftRow)
            .where(InvoiceDraftRow.workspace_id == self.workspace_id)
            .order_by(InvoiceDraftRow.id, InvoiceDraftRow.revision)
        )
        return [self._restore_draft(row) for row in rows]
