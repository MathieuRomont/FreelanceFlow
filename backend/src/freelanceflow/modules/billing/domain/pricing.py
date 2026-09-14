"""Exact deterministic pricing for caller-prepared, single-business-date work segments."""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from math import gcd
from uuid import UUID

from freelanceflow.modules.billing.domain import RateAgreement, resolve_rate
from freelanceflow.modules.time_tracking.domain import TimeEntry

MICROSECONDS_PER_HOUR = 3_600_000_000


class BillingCalculationError(ValueError):
    """Base error for deterministic pricing failures."""


class NonBillableTimeEntryError(BillingCalculationError):
    """A non-billable TimeEntry cannot be priced."""


class UnclassifiedTimeEntryError(BillingCalculationError):
    """An unclassified TimeEntry cannot be priced."""


class InvalidBillingSegmentError(BillingCalculationError):
    """A prepared segment is invalid or falls outside its source TimeEntry."""


class UnpreparedBillingSegmentError(BillingCalculationError):
    """Raw TimeEntries cannot be priced without caller-prepared business-date segments."""


class DuplicateBillingSegmentError(BillingCalculationError):
    """Prepared segments allocate overlapping work from the same TimeEntry."""


class IncompatibleBillingContextError(BillingCalculationError):
    """One source identity was supplied with incompatible TimeEntry snapshots."""


class InvalidRateReferenceError(BillingCalculationError):
    """RateAgreement storage identities must be unique in one pricing operation."""


@dataclass(frozen=True)
class RateAgreementReference:
    """Stable application identity paired with an immutable RateAgreement."""

    id: UUID
    agreement: RateAgreement


@dataclass(frozen=True)
class ExactMoneyAmount:
    """An exact unrounded number of currency units.

    This deliberately has no Decimal conversion or quantization method: choosing a
    finite currency amount requires the unresolved monetary-rounding policy.
    """

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if type(self.numerator) is not int or type(self.denominator) is not int:
            raise TypeError("Exact amount components must be integers")
        if self.denominator == 0:
            raise ValueError("Exact amount denominator must not be zero")
        numerator = self.numerator
        denominator = self.denominator
        if denominator < 0:
            numerator = -numerator
            denominator = -denominator
        divisor = gcd(abs(numerator), denominator)
        object.__setattr__(self, "numerator", numerator // divisor)
        object.__setattr__(self, "denominator", denominator // divisor)


@dataclass(frozen=True)
class PreparedBillingSegment:
    """A caller-prepared portion of one TimeEntry assigned to one business date.

    The caller owns business-date interpretation and any local-day or rate-boundary
    splitting. This type validates only exact instant containment and delegates elapsed
    duration semantics to TimeEntry.
    """

    source_time_entry: TimeEntry
    start: datetime
    end: datetime
    business_date: date
    _duration: timedelta = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.business_date) is not date:
            raise InvalidBillingSegmentError("business_date must be an interpreted date")
        try:
            segment_entry = replace(self.source_time_entry, start=self.start, end=self.end)
        except ValueError as error:
            raise InvalidBillingSegmentError(str(error)) from error
        if (
            self.start.astimezone(UTC) < self.source_time_entry.start.astimezone(UTC)
            or self.end.astimezone(UTC) > self.source_time_entry.end.astimezone(UTC)
        ):
            raise InvalidBillingSegmentError("Segment must be contained in its source TimeEntry")
        object.__setattr__(self, "_duration", segment_entry.duration)

    @classmethod
    def for_complete_entry(
        cls, source_time_entry: TimeEntry, *, business_date: date
    ) -> "PreparedBillingSegment":
        return cls(
            source_time_entry=source_time_entry,
            start=source_time_entry.start,
            end=source_time_entry.end,
            business_date=business_date,
        )

    @property
    def duration(self) -> timedelta:
        return self._duration

    @property
    def duration_microseconds(self) -> int:
        return (
            (self.duration.days * 86_400 + self.duration.seconds) * 1_000_000
            + self.duration.microseconds
        )


@dataclass(frozen=True)
class PricedSegment:
    """Auditable exact pricing result with no invoice-level rounding."""

    segment: PreparedBillingSegment
    applied_rate: RateAgreementReference
    exact_amount: ExactMoneyAmount

    @property
    def source_time_entry_id(self) -> UUID:
        return self.segment.source_time_entry.id

    @property
    def workspace_id(self) -> UUID:
        return self.segment.source_time_entry.workspace_id

    @property
    def client_id(self) -> UUID:
        client = self.segment.source_time_entry.client
        assert client is not None
        return client.id

    @property
    def project_id(self) -> UUID:
        project = self.segment.source_time_entry.project
        assert project is not None
        return project.id

    @property
    def task_id(self) -> UUID | None:
        task = self.segment.source_time_entry.task
        return task.id if task is not None else None

    @property
    def duration(self) -> timedelta:
        return self.segment.duration

    @property
    def duration_microseconds(self) -> int:
        return self.segment.duration_microseconds

    @property
    def hourly_rate(self) -> Decimal:
        return self.applied_rate.agreement.hourly_amount

    @property
    def currency(self) -> str:
        return self.applied_rate.agreement.currency


def _decimal_ratio(value: Decimal) -> tuple[int, int]:
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
    if sign:
        coefficient = -coefficient
    if exponent >= 0:
        return coefficient * 10**exponent, 1
    return coefficient, 10 ** (-exponent)


def _exact_amount(duration_microseconds: int, hourly_rate: Decimal) -> ExactMoneyAmount:
    rate_numerator, rate_denominator = _decimal_ratio(hourly_rate)
    return ExactMoneyAmount(
        numerator=duration_microseconds * rate_numerator,
        denominator=MICROSECONDS_PER_HOUR * rate_denominator,
    )


def _validate_rate_references(rates: list[RateAgreementReference]) -> None:
    identifiers = [rate.id for rate in rates]
    if len(set(identifiers)) != len(identifiers):
        raise InvalidRateReferenceError("RateAgreement IDs must be unique")


def price_prepared_segment(
    segment: PreparedBillingSegment,
    rates: Iterable[RateAgreementReference],
) -> PricedSegment:
    """Price one explicitly dated segment using existing rate resolution."""
    if not isinstance(segment, PreparedBillingSegment):
        raise UnpreparedBillingSegmentError(
            "Pricing requires a caller-prepared segment with an explicit business_date"
        )
    entry = segment.source_time_entry
    if not entry.billable:
        raise NonBillableTimeEntryError("Non-billable TimeEntry cannot be priced")
    if entry.client is None or entry.project is None:
        raise UnclassifiedTimeEntryError("Unclassified TimeEntry cannot be priced")

    references = list(rates)
    _validate_rate_references(references)
    agreement = resolve_rate(
        client=entry.client,
        project=entry.project,
        business_date=segment.business_date,
        agreements=[reference.agreement for reference in references],
    )
    applied_rate = next(
        reference for reference in references if reference.agreement is agreement
    )
    return PricedSegment(
        segment=segment,
        applied_rate=applied_rate,
        exact_amount=_exact_amount(segment.duration_microseconds, agreement.hourly_amount),
    )


def price_prepared_segments(
    segments: Iterable[PreparedBillingSegment],
    rates: Iterable[RateAgreementReference],
) -> tuple[PricedSegment, ...]:
    """Price prepared segments in deterministic source/instant/date order."""
    prepared = list(segments)
    if any(not isinstance(segment, PreparedBillingSegment) for segment in prepared):
        raise UnpreparedBillingSegmentError(
            "Automatic business-date derivation and pricing segmentation are unsupported"
        )
    ordered = sorted(
        prepared,
        key=lambda segment: (
            segment.source_time_entry.workspace_id.int,
            segment.source_time_entry.id.int,
            segment.start.astimezone(UTC),
            segment.end.astimezone(UTC),
            segment.business_date,
        ),
    )
    sources: dict[UUID, TimeEntry] = {}
    for segment in ordered:
        source = segment.source_time_entry
        existing = sources.setdefault(source.id, source)
        if existing != source:
            raise IncompatibleBillingContextError(
                "One TimeEntry ID cannot have multiple ownership or interval contexts"
            )
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if (
            previous.source_time_entry.id == current.source_time_entry.id
            and previous.source_time_entry.workspace_id
            == current.source_time_entry.workspace_id
            and current.start.astimezone(UTC) < previous.end.astimezone(UTC)
        ):
            raise DuplicateBillingSegmentError(
                "Prepared segments must not overlap within one source TimeEntry"
            )
    references = list(rates)
    _validate_rate_references(references)
    return tuple(price_prepared_segment(segment, references) for segment in ordered)
