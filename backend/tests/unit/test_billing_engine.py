from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from freelanceflow.modules.billing.domain import (
    ConflictingRatesError,
    MissingRateError,
    RateAgreement,
)
from freelanceflow.modules.billing.domain.pricing import (
    DuplicateBillingSegmentError,
    ExactMoneyAmount,
    IncompatibleBillingContextError,
    InvalidBillingSegmentError,
    InvalidRateReferenceError,
    NonBillableTimeEntryError,
    PreparedBillingSegment,
    RateAgreementReference,
    UnclassifiedTimeEntryError,
    UnpreparedBillingSegmentError,
    price_prepared_segment,
    price_prepared_segments,
)
from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.domain import TimeEntry

WORKSPACE_ID = UUID(int=1)
CLIENT = Client(UUID(int=2), WORKSPACE_ID, "Client")
PROJECT = Project(UUID(int=3), CLIENT, "Project")
TASK = Task(UUID(int=4), PROJECT, "Task")
START_DATE = date(2026, 1, 1)
CHANGE_DATE = date(2026, 9, 1)


def entry(
    *,
    identifier: int = 10,
    start: datetime | None = None,
    duration: timedelta = timedelta(hours=1),
    billable: bool = True,
    classified: bool = True,
    task: Task | None = TASK,
) -> TimeEntry:
    start = start or datetime(2026, 1, 1, 9, tzinfo=UTC)
    return TimeEntry(
        id=UUID(int=identifier),
        workspace_id=WORKSPACE_ID,
        start=start,
        end=start + duration,
        billable=billable,
        client=CLIENT if classified else None,
        project=PROJECT if classified else None,
        task=task if classified else None,
    )


def rate(
    amount: str = "80",
    *,
    identifier: int = 20,
    project: Project | None = None,
    currency: str = "EUR",
    valid_from: date = START_DATE,
    valid_until: date | None = None,
) -> RateAgreementReference:
    return RateAgreementReference(
        UUID(int=identifier),
        RateAgreement(
            client=CLIENT,
            project=project,
            hourly_amount=Decimal(amount),
            currency=currency,
            valid_from=valid_from,
            valid_until=valid_until,
        ),
    )


def prepared(value: TimeEntry | None = None, day: date = START_DATE) -> PreparedBillingSegment:
    return PreparedBillingSegment.for_complete_entry(value or entry(), business_date=day)


def test_exact_single_entry_pricing_is_auditable() -> None:
    source = entry(duration=timedelta(hours=2), task=TASK)
    applied = rate("80.1200", currency="USD")
    result = price_prepared_segment(prepared(source), [applied])
    assert result.source_time_entry_id == source.id
    assert result.workspace_id == WORKSPACE_ID
    assert result.client_id == CLIENT.id
    assert result.project_id == PROJECT.id
    assert result.task_id == TASK.id
    assert result.duration == timedelta(hours=2)
    assert result.duration_microseconds == 7_200_000_000
    assert result.applied_rate is applied
    assert result.hourly_rate is applied.agreement.hourly_amount
    assert str(result.hourly_rate) == "80.1200"
    assert result.currency == "USD"
    assert result.exact_amount == ExactMoneyAmount(4006, 25)


def test_nonterminating_ordinary_amount_remains_exact_without_rounding() -> None:
    result = price_prepared_segment(
        prepared(entry(duration=timedelta(minutes=20))), [rate("80")]
    )
    assert result.duration == timedelta(minutes=20)
    assert result.exact_amount == ExactMoneyAmount(80, 3)
    assert not hasattr(result.exact_amount, "as_decimal")


def test_decimal_rate_and_microsecond_duration_preserve_exact_precision() -> None:
    result = price_prepared_segment(
        prepared(entry(duration=timedelta(microseconds=1))),
        [rate("80.123456789012345678901234567890123456789")],
    )
    assert result.exact_amount == ExactMoneyAmount(
        80123456789012345678901234567890123456789,
        3_600_000_000 * 10**39,
    )


@pytest.mark.parametrize(
    "amount, expected",
    [
        ("0", ExactMoneyAmount(0, 1)),
        ("-90", ExactMoneyAmount(-45, 1)),
    ],
)
def test_zero_and_negative_rates_remain_supported(
    amount: str, expected: ExactMoneyAmount
) -> None:
    result = price_prepared_segment(
        prepared(entry(duration=timedelta(minutes=30))), [rate(amount)]
    )
    assert result.exact_amount == expected


def test_project_precedence_uses_existing_resolver() -> None:
    client_rates = [rate("80", identifier=21), rate("90", identifier=22)]
    project_rate = rate("100", identifier=23, project=PROJECT)
    result = price_prepared_segment(prepared(), [*client_rates, project_rate])
    assert result.applied_rate is project_rate
    assert result.exact_amount == ExactMoneyAmount(100, 1)


def test_conflicts_and_missing_rates_fail_explicitly() -> None:
    with pytest.raises(ConflictingRatesError, match="Multiple project agreements"):
        price_prepared_segment(
            prepared(),
            [
                rate("100", identifier=21, project=PROJECT),
                rate("110", identifier=22, project=PROJECT),
            ],
        )
    with pytest.raises(ConflictingRatesError, match="Multiple client agreements"):
        price_prepared_segment(
            prepared(), [rate("80", identifier=21), rate("90", identifier=22)]
        )
    with pytest.raises(MissingRateError):
        price_prepared_segment(prepared(), [])


def test_half_open_boundaries_and_open_end_are_preserved() -> None:
    old = rate("80", identifier=21, valid_until=CHANGE_DATE)
    new = rate("90", identifier=22, valid_from=CHANGE_DATE)
    assert price_prepared_segment(prepared(day=START_DATE), [new, old]).applied_rate is old
    assert (
        price_prepared_segment(prepared(day=date(2026, 8, 31)), [new, old]).applied_rate
        is old
    )
    assert price_prepared_segment(prepared(day=CHANGE_DATE), [new, old]).applied_rate is new
    assert (
        price_prepared_segment(prepared(day=date(2099, 1, 1)), [new, old]).applied_rate
        is new
    )


def test_nonbillable_and_unclassified_entries_are_not_priced() -> None:
    with pytest.raises(NonBillableTimeEntryError):
        price_prepared_segment(prepared(entry(billable=False)), [rate()])
    with pytest.raises(UnclassifiedTimeEntryError):
        price_prepared_segment(prepared(entry(classified=False, task=None)), [rate()])


def test_workspace_and_scope_are_not_substituted() -> None:
    other_client = Client(UUID(int=30), UUID(int=31), "Other")
    unrelated = RateAgreementReference(
        UUID(int=32),
        RateAgreement(other_client, Decimal("80"), "EUR", START_DATE),
    )
    with pytest.raises(MissingRateError):
        price_prepared_segment(prepared(), [unrelated])


def test_multiple_entries_have_deterministic_order_and_independent_currency() -> None:
    first = entry(identifier=40, duration=timedelta(minutes=30), task=None)
    second = entry(identifier=41, duration=timedelta(hours=1), task=None)
    eur = rate("80", identifier=42, currency="EUR")
    results = price_prepared_segments([prepared(second), prepared(first)], [eur])
    assert [result.source_time_entry_id for result in results] == [first.id, second.id]
    assert [result.currency for result in results] == ["EUR", "EUR"]
    assert [result.exact_amount for result in results] == [
        ExactMoneyAmount(40, 1),
        ExactMoneyAmount(80, 1),
    ]


def test_dst_duration_reuses_exact_time_entry_instants() -> None:
    paris = ZoneInfo("Europe/Paris")
    source = TimeEntry(
        id=UUID(int=50),
        workspace_id=WORKSPACE_ID,
        start=datetime(2026, 10, 25, 1, 30, tzinfo=paris),
        end=datetime(2026, 10, 25, 3, 30, tzinfo=paris),
        billable=True,
        client=CLIENT,
        project=PROJECT,
    )
    result = price_prepared_segment(prepared(source, date(2026, 10, 25)), [rate()])
    assert source.duration == result.duration == timedelta(hours=3)
    assert result.exact_amount == ExactMoneyAmount(240, 1)


def test_caller_prepared_subsegments_must_be_contained_and_nonoverlapping() -> None:
    source = entry(duration=timedelta(hours=2))
    first = PreparedBillingSegment(
        source, source.start, source.start + timedelta(hours=1), START_DATE
    )
    second = PreparedBillingSegment(source, first.end, source.end, START_DATE)
    assert len(price_prepared_segments([second, first], [rate()])) == 2
    overlapping = replace(second, start=first.end - timedelta(microseconds=1))
    with pytest.raises(DuplicateBillingSegmentError):
        price_prepared_segments([first, overlapping], [rate()])
    with pytest.raises(InvalidBillingSegmentError, match="contained"):
        replace(first, end=source.end + timedelta(microseconds=1))


def test_raw_rate_boundary_spanning_entry_is_deferred_without_timezone_guess() -> None:
    source = entry(
        start=datetime(2026, 8, 31, 23, 30, tzinfo=UTC),
        duration=timedelta(hours=1),
    )
    with pytest.raises(UnpreparedBillingSegmentError, match="Automatic"):
        price_prepared_segments([source], [rate()])  # type: ignore[list-item]


def test_duplicate_rate_identity_is_rejected() -> None:
    first = rate("80", identifier=60)
    with pytest.raises(InvalidRateReferenceError, match="IDs must be unique"):
        price_prepared_segment(prepared(), [first, replace(first, agreement=rate("90").agreement)])


def test_one_source_identity_cannot_mix_ownership_snapshots() -> None:
    source = entry()
    other_client = Client(UUID(int=70), WORKSPACE_ID, "Other")
    other_project = Project(UUID(int=71), other_client, "Other project")
    reclassified = replace(source, client=other_client, project=other_project, task=None)
    with pytest.raises(IncompatibleBillingContextError, match="multiple ownership"):
        price_prepared_segments([prepared(source), prepared(reclassified)], [rate()])
