from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest

from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.billing.domain.invoice_drafts import (
    DuplicateInvoiceAllocationError,
    IncompatibleInvoiceContextError,
    IncompatibleInvoiceLineError,
    InvalidInvoiceDraftError,
    InvoiceCurrency,
    InvoiceDraft,
    InvoiceLineInput,
    MixedInvoiceCurrencyError,
    OverlappingInvoiceAllocationError,
    UnsupportedInvoiceCurrencyError,
    UnsupportedNegativeInvoiceAmountError,
    build_invoice_draft,
)
from freelanceflow.modules.billing.domain.pricing import (
    ExactMoneyAmount,
    PreparedBillingSegment,
    PricedSegment,
    RateAgreementReference,
    price_prepared_segment,
)
from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.domain import TimeEntry

WORKSPACE_ID = UUID(int=1)
CLIENT = Client(UUID(int=2), WORKSPACE_ID, "Client")
PROJECT = Project(UUID(int=3), CLIENT, "Project")
TASK = Task(UUID(int=4), PROJECT, "Task")
BUSINESS_DATE = date(2026, 1, 1)
START = datetime(2026, 1, 1, 9, tzinfo=UTC)


def priced(
    amount: str,
    *,
    entry_id: int = 10,
    rate_id: int = 20,
    start: datetime = START,
    duration: timedelta = timedelta(hours=1),
    workspace_id: UUID = WORKSPACE_ID,
    client: Client = CLIENT,
    project: Project = PROJECT,
    task: Task | None = TASK,
    currency: str = "EUR",
) -> PricedSegment:
    entry = TimeEntry(
        id=UUID(int=entry_id),
        workspace_id=workspace_id,
        start=start,
        end=start + duration,
        billable=True,
        client=client,
        project=project,
        task=task,
    )
    rate = RateAgreementReference(
        id=UUID(int=rate_id),
        agreement=RateAgreement(
            client=client,
            project=project,
            hourly_amount=Decimal(amount),
            currency=currency,
            valid_from=BUSINESS_DATE,
        ),
    )
    segment = PreparedBillingSegment.for_complete_entry(
        entry, business_date=BUSINESS_DATE
    )
    return price_prepared_segment(segment, [rate])


def draft(*groups: InvoiceLineInput, revision: int = 1) -> InvoiceDraft:
    return build_invoice_draft(
        draft_id=UUID(int=100),
        revision=revision,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT.id,
        line_inputs=groups,
    )


def line(identifier: int, *segments: PricedSegment) -> InvoiceLineInput:
    return InvoiceLineInput(UUID(int=identifier), segments)


@pytest.mark.parametrize(
    "amount, expected_minor_units",
    [("0.0049", 0), ("0.005", 1), ("0.0051", 1)],
)
def test_half_cent_boundaries_use_explicit_half_up(
    amount: str, expected_minor_units: int
) -> None:
    result = draft(line(30, priced(amount)))
    assert result.currency == InvoiceCurrency("EUR", 2)
    assert result.lines[0].exact_amount == ExactMoneyAmount(
        *Decimal(amount).as_integer_ratio()
    )
    assert result.lines[0].rounded_amount.minor_units == expected_minor_units


def test_rounding_is_independent_from_the_active_decimal_context() -> None:
    segment = priced("0.005")
    with localcontext() as context:
        context.prec = 1
        context.rounding = "ROUND_DOWN"
        result = draft(line(30, segment))
    assert result.lines[0].rounded_amount.minor_units == 1


def test_segments_are_aggregated_exactly_before_one_line_rounding() -> None:
    first = priced("0.004", entry_id=10)
    second = priced("0.004", entry_id=11)
    result = draft(line(30, first, second))
    invoice_line = result.lines[0]
    assert invoice_line.exact_amount == ExactMoneyAmount(1, 125)
    assert invoice_line.rounded_amount.minor_units == 1
    assert [
        draft(line(31 + index, segment)).lines[0].rounded_amount.minor_units
        for index, segment in enumerate((first, second))
    ] == [0, 0]


def test_line_amounts_reconcile_exactly_to_invoice_total() -> None:
    result = draft(
        line(30, priced("0.005", entry_id=10)),
        line(31, priced("1.234", entry_id=11, rate_id=21)),
    )
    assert [value.rounded_amount.minor_units for value in result.lines] == [1, 123]
    assert result.exact_subtotal == ExactMoneyAmount(1239, 1000)
    assert result.subtotal.minor_units == result.total.minor_units == 124
    assert result.total is result.subtotal


def test_eur_precision_is_snapshotted_and_cannot_be_redeclared() -> None:
    result = draft(line(30, priced("80")))
    assert result.currency.code == "EUR"
    assert result.currency.decimal_places == 2
    assert result.lines[0].currency is result.currency
    with pytest.raises(UnsupportedInvoiceCurrencyError, match="requires 2"):
        InvoiceCurrency("EUR", 3)


def test_unsupported_and_mixed_currencies_fail_explicitly() -> None:
    usd = priced("80", currency="USD")
    with pytest.raises(UnsupportedInvoiceCurrencyError, match="USD"):
        draft(line(30, usd))
    with pytest.raises(MixedInvoiceCurrencyError):
        draft(line(30, priced("80")), line(31, usd))


def test_duplicate_source_allocation_is_rejected_across_lines() -> None:
    segment = priced("80")
    with pytest.raises(DuplicateInvoiceAllocationError):
        draft(line(30, segment), line(31, segment))


def test_overlapping_allocations_from_the_same_time_entry_are_rejected() -> None:
    source = priced("80", duration=timedelta(hours=1)).segment.source_time_entry
    rate = priced("80").applied_rate
    first = price_prepared_segment(
        PreparedBillingSegment(
            source, source.start, source.start + timedelta(minutes=40), BUSINESS_DATE
        ),
        [rate],
    )
    second = price_prepared_segment(
        PreparedBillingSegment(
            source,
            source.start + timedelta(minutes=30),
            source.end,
            BUSINESS_DATE,
        ),
        [rate],
    )
    with pytest.raises(OverlappingInvoiceAllocationError):
        draft(line(30, first), line(31, second))


def test_overlapping_distinct_time_entries_are_permitted() -> None:
    result = draft(
        line(30, priced("80", entry_id=10)),
        line(31, priced("80", entry_id=11)),
    )
    assert len(result.lines) == 2
    assert result.total.minor_units == 16_000


@pytest.mark.parametrize("difference", ["workspace", "client", "project", "task", "rate"])
def test_one_line_rejects_incompatible_pricing_context(difference: str) -> None:
    first = priced("80", entry_id=10)
    other_workspace = UUID(int=40)
    other_client = Client(
        UUID(int=41), other_workspace if difference == "workspace" else WORKSPACE_ID, "Other"
    )
    if difference == "workspace":
        second = priced(
            "80",
            entry_id=11,
            workspace_id=other_workspace,
            client=other_client,
            project=Project(UUID(int=42), other_client, "Other"),
            task=None,
        )
    elif difference == "client":
        second_project = Project(UUID(int=42), other_client, "Other")
        second = priced("80", entry_id=11, client=other_client, project=second_project, task=None)
    elif difference == "project":
        second_project = Project(UUID(int=42), CLIENT, "Other")
        second = priced("80", entry_id=11, project=second_project, task=None)
    elif difference == "task":
        second = priced("80", entry_id=11, task=Task(UUID(int=43), PROJECT, "Other"))
    else:
        second = priced("80", entry_id=11, rate_id=21)
    with pytest.raises(IncompatibleInvoiceLineError):
        draft(line(30, first, second))


def test_one_line_rejects_changed_rate_value_under_the_same_identity() -> None:
    first = priced("80", entry_id=10)
    second = priced("80.00", entry_id=11)
    assert first.applied_rate.id == second.applied_rate.id
    with pytest.raises(IncompatibleInvoiceLineError):
        draft(line(30, first, second))


def test_draft_ownership_must_match_every_line() -> None:
    with pytest.raises(IncompatibleInvoiceContextError):
        build_invoice_draft(
            draft_id=UUID(int=100),
            revision=1,
            workspace_id=UUID(int=999),
            client_id=CLIENT.id,
            line_inputs=(line(30, priced("80")),),
        )


def test_allocations_preserve_exact_source_traceability() -> None:
    source = priced("80.1200", duration=timedelta(microseconds=1))
    result = draft(line(30, source))
    allocation = result.lines[0].allocations[0]
    assert allocation.priced_segment is source
    assert allocation.source_time_entry_id == source.source_time_entry_id
    assert allocation.start == source.segment.start
    assert allocation.end == source.segment.end
    assert allocation.duration_microseconds == 1
    assert allocation.exact_amount == source.exact_amount
    assert result.lines[0].hourly_rate.as_tuple() == Decimal("80.1200").as_tuple()


def test_allocation_order_and_draft_output_are_deterministic() -> None:
    first = priced("80", entry_id=10)
    second = priced("80", entry_id=11)
    forward = draft(line(30, first, second), revision=2)
    reverse = draft(line(30, second, first), revision=2)
    assert forward == reverse
    assert forward.revision == 2
    assert [item.source_time_entry_id for item in forward.lines[0].allocations] == [
        first.source_time_entry_id,
        second.source_time_entry_id,
    ]
    with pytest.raises(InvalidInvoiceDraftError, match="positive integer"):
        draft(line(30, first), revision=0)
    with pytest.raises(InvalidInvoiceDraftError, match="positive integer"):
        draft(line(30, first), revision=True)


def test_negative_exact_line_amount_is_deferred_pending_credit_note_policy() -> None:
    with pytest.raises(UnsupportedNegativeInvoiceAmountError, match="credit-note"):
        draft(line(30, priced("-80")))


def test_same_source_identity_cannot_mix_snapshots_across_lines() -> None:
    first = priced("80")
    changed_entry = replace(first.segment.source_time_entry, task=None)
    changed = replace(
        first,
        segment=PreparedBillingSegment.for_complete_entry(
            changed_entry, business_date=BUSINESS_DATE
        ),
    )
    with pytest.raises(IncompatibleInvoiceContextError, match="multiple source snapshots"):
        draft(line(30, first), line(31, changed))
