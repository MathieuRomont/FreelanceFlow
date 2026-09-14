"""Pure invoice-draft construction from exact priced segments."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import gcd
from typing import Final
from uuid import UUID

from freelanceflow.modules.billing.domain.pricing import ExactMoneyAmount, PricedSegment

_SUPPORTED_CURRENCY_PRECISION: Final[dict[str, int]] = {"EUR": 2}


class InvoiceDraftError(ValueError):
    """Base error for invoice-draft construction failures."""


class InvalidInvoiceDraftError(InvoiceDraftError):
    """The requested draft or line has invalid structural data."""


class UnsupportedInvoiceCurrencyError(InvoiceDraftError):
    """The currency has no confirmed invoice precision policy."""


class MixedInvoiceCurrencyError(InvoiceDraftError):
    """One invoice cannot contain more than one currency."""


class IncompatibleInvoiceLineError(InvoiceDraftError):
    """Segments in one logical line do not share pricing-relevant context."""


class IncompatibleInvoiceContextError(InvoiceDraftError):
    """An allocation does not belong to the draft ownership context."""


class DuplicateInvoiceAllocationError(InvoiceDraftError):
    """The same source interval is allocated more than once."""


class OverlappingInvoiceAllocationError(InvoiceDraftError):
    """Allocations overlap within one source TimeEntry."""


class UnsupportedNegativeInvoiceAmountError(InvoiceDraftError):
    """Negative invoice and credit-note semantics are not defined."""


@dataclass(frozen=True)
class InvoiceCurrency:
    """The supported currency precision snapshotted into an invoice draft."""

    code: str
    decimal_places: int

    def __post_init__(self) -> None:
        if not isinstance(self.code, str):
            raise UnsupportedInvoiceCurrencyError("Invoice currency code must be a string")
        expected = _SUPPORTED_CURRENCY_PRECISION.get(self.code)
        if expected is None:
            raise UnsupportedInvoiceCurrencyError(
                f"Currency {self.code!r} is not supported for invoice drafts"
            )
        if type(self.decimal_places) is not int or self.decimal_places != expected:
            raise UnsupportedInvoiceCurrencyError(
                f"Currency {self.code!r} requires {expected} decimal places"
            )


@dataclass(frozen=True)
class RoundedMoneyAmount:
    """A HALF_UP-rounded invoice amount stored in integer minor units."""

    currency: InvoiceCurrency
    minor_units: int

    def __post_init__(self) -> None:
        if not isinstance(self.currency, InvoiceCurrency):
            raise TypeError("Rounded amount currency must be an InvoiceCurrency")
        if type(self.minor_units) is not int:
            raise TypeError("Rounded amount minor_units must be an integer")


@dataclass(frozen=True)
class InvoiceAllocation:
    """One immutable, auditable allocation back to an exact priced segment."""

    priced_segment: PricedSegment

    def __post_init__(self) -> None:
        if not isinstance(self.priced_segment, PricedSegment):
            raise InvalidInvoiceDraftError("InvoiceAllocation requires a PricedSegment")

    @property
    def source_time_entry_id(self) -> UUID:
        return self.priced_segment.source_time_entry_id

    @property
    def start(self) -> datetime:
        return self.priced_segment.segment.start

    @property
    def end(self) -> datetime:
        return self.priced_segment.segment.end

    @property
    def duration_microseconds(self) -> int:
        return self.priced_segment.duration_microseconds

    @property
    def exact_amount(self) -> ExactMoneyAmount:
        return self.priced_segment.exact_amount


@dataclass(frozen=True)
class InvoiceLineInput:
    """A caller-selected logical grouping; no presentation grouping is inferred."""

    id: UUID
    priced_segments: tuple[PricedSegment, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise InvalidInvoiceDraftError("InvoiceLine ID must be a UUID")
        if type(self.priced_segments) is not tuple:
            raise InvalidInvoiceDraftError("InvoiceLine priced_segments must be a tuple")
        if not self.priced_segments:
            raise InvalidInvoiceDraftError("InvoiceLine requires at least one priced segment")
        if any(not isinstance(segment, PricedSegment) for segment in self.priced_segments):
            raise InvalidInvoiceDraftError("InvoiceLine inputs must be PricedSegments")


@dataclass(frozen=True)
class InvoiceLine:
    """An exact logical aggregation rounded exactly once to invoice minor units."""

    id: UUID
    workspace_id: UUID
    client_id: UUID
    project_id: UUID
    task_id: UUID | None
    applied_rate_agreement_id: UUID
    hourly_rate: Decimal
    currency: InvoiceCurrency
    allocations: tuple[InvoiceAllocation, ...]
    duration_microseconds: int
    exact_amount: ExactMoneyAmount
    rounded_amount: RoundedMoneyAmount

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise InvalidInvoiceDraftError("InvoiceLine ID must be a UUID")
        if not isinstance(self.workspace_id, UUID) or not isinstance(self.client_id, UUID):
            raise InvalidInvoiceDraftError("InvoiceLine ownership IDs must be UUIDs")
        if type(self.allocations) is not tuple:
            raise InvalidInvoiceDraftError("InvoiceLine allocations must be a tuple")
        if any(not isinstance(value, InvoiceAllocation) for value in self.allocations):
            raise InvalidInvoiceDraftError("InvoiceLine allocations are invalid")
        if not self.allocations:
            raise InvalidInvoiceDraftError("InvoiceLine requires at least one allocation")
        segments = tuple(allocation.priced_segment for allocation in self.allocations)
        first = segments[0]
        if any(_line_context(segment) != _line_context(first) for segment in segments[1:]):
            raise IncompatibleInvoiceLineError(
                "One line requires matching pricing-relevant context"
            )
        expected_duration = sum(
            allocation.duration_microseconds for allocation in self.allocations
        )
        expected_exact = _sum_exact(
            tuple(allocation.exact_amount for allocation in self.allocations)
        )
        if (
            self.workspace_id != first.workspace_id
            or self.client_id != first.client_id
            or self.project_id != first.project_id
            or self.task_id != first.task_id
            or self.applied_rate_agreement_id != first.applied_rate.id
            or self.hourly_rate.as_tuple() != first.hourly_rate.as_tuple()
            or self.currency.code != first.currency
            or self.duration_microseconds != expected_duration
            or self.exact_amount != expected_exact
            or self.rounded_amount != _round_half_up(expected_exact, self.currency)
        ):
            raise InvalidInvoiceDraftError("InvoiceLine derived values are inconsistent")

    @property
    def duration(self) -> timedelta:
        return timedelta(microseconds=self.duration_microseconds)


@dataclass(frozen=True)
class InvoiceDraft:
    """A tax-free MVP draft whose displayed totals sum its rounded lines exactly."""

    id: UUID
    revision: int
    workspace_id: UUID
    client_id: UUID
    currency: InvoiceCurrency
    lines: tuple[InvoiceLine, ...]
    exact_subtotal: ExactMoneyAmount
    subtotal: RoundedMoneyAmount
    total: RoundedMoneyAmount

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise InvalidInvoiceDraftError("InvoiceDraft ID must be a UUID")
        if type(self.revision) is not int or self.revision < 1:
            raise InvalidInvoiceDraftError("InvoiceDraft revision must be a positive integer")
        if not isinstance(self.workspace_id, UUID) or not isinstance(self.client_id, UUID):
            raise InvalidInvoiceDraftError("InvoiceDraft ownership IDs must be UUIDs")
        if not isinstance(self.currency, InvoiceCurrency):
            raise InvalidInvoiceDraftError("InvoiceDraft currency snapshot is invalid")
        if type(self.lines) is not tuple or any(
            not isinstance(line, InvoiceLine) for line in self.lines
        ):
            raise InvalidInvoiceDraftError("InvoiceDraft lines must be InvoiceLines")
        if not self.lines:
            raise InvalidInvoiceDraftError("InvoiceDraft requires at least one line")
        if len({line.id for line in self.lines}) != len(self.lines):
            raise InvalidInvoiceDraftError("InvoiceLine IDs must be unique within a draft")
        if any(
            line.workspace_id != self.workspace_id or line.client_id != self.client_id
            for line in self.lines
        ):
            raise IncompatibleInvoiceContextError(
                "Every InvoiceLine must belong to the draft workspace and client"
            )
        if any(line.currency != self.currency for line in self.lines):
            raise MixedInvoiceCurrencyError("InvoiceDraft requires exactly one currency")
        expected_exact = _sum_exact(tuple(line.exact_amount for line in self.lines))
        expected_subtotal = RoundedMoneyAmount(
            currency=self.currency,
            minor_units=sum(line.rounded_amount.minor_units for line in self.lines),
        )
        if (
            self.exact_subtotal != expected_exact
            or self.subtotal != expected_subtotal
            or self.total != expected_subtotal
        ):
            raise InvalidInvoiceDraftError("InvoiceDraft totals are inconsistent")
        _validate_allocations(self.lines)


def _currency_for(code: str) -> InvoiceCurrency:
    precision = _SUPPORTED_CURRENCY_PRECISION.get(code)
    if precision is None:
        raise UnsupportedInvoiceCurrencyError(
            f"Currency {code!r} is not supported for invoice drafts"
        )
    return InvoiceCurrency(code=code, decimal_places=precision)


def _add_exact(left: ExactMoneyAmount, right: ExactMoneyAmount) -> ExactMoneyAmount:
    common_divisor = gcd(left.denominator, right.denominator)
    return ExactMoneyAmount(
        left.numerator * (right.denominator // common_divisor)
        + right.numerator * (left.denominator // common_divisor),
        (left.denominator // common_divisor) * right.denominator,
    )


def _sum_exact(amounts: tuple[ExactMoneyAmount, ...]) -> ExactMoneyAmount:
    total = ExactMoneyAmount(0, 1)
    for amount in amounts:
        total = _add_exact(total, amount)
    return total


def _round_half_up(amount: ExactMoneyAmount, currency: InvoiceCurrency) -> RoundedMoneyAmount:
    """Round a nonnegative exact amount once, without Decimal context involvement."""
    if amount.numerator < 0:
        raise UnsupportedNegativeInvoiceAmountError(
            "Negative invoice amounts require a future credit-note policy"
        )
    scaled_numerator = amount.numerator * 10**currency.decimal_places
    minor_units, remainder = divmod(scaled_numerator, amount.denominator)
    if remainder * 2 >= amount.denominator:
        minor_units += 1
    return RoundedMoneyAmount(currency=currency, minor_units=minor_units)


def _line_context(segment: PricedSegment) -> tuple[object, ...]:
    return (
        segment.workspace_id,
        segment.client_id,
        segment.project_id,
        segment.task_id,
        segment.currency,
        segment.applied_rate.id,
        segment.hourly_rate.as_tuple(),
        segment.applied_rate.agreement,
    )


def _allocation_order(allocation: InvoiceAllocation) -> tuple[object, ...]:
    segment = allocation.priced_segment
    return (
        segment.workspace_id.int,
        segment.source_time_entry_id.int,
        allocation.start.astimezone(UTC),
        allocation.end.astimezone(UTC),
        segment.segment.business_date,
    )


def _build_line(value: InvoiceLineInput, currency: InvoiceCurrency) -> InvoiceLine:
    first = value.priced_segments[0]
    expected_context = _line_context(first)
    if any(_line_context(segment) != expected_context for segment in value.priced_segments[1:]):
        raise IncompatibleInvoiceLineError(
            "One line requires matching workspace, client, project, task, currency, "
            "RateAgreement identity, and exact hourly rate"
        )
    allocations = tuple(
        sorted(
            (InvoiceAllocation(segment) for segment in value.priced_segments),
            key=_allocation_order,
        )
    )
    exact_amount = _sum_exact(tuple(item.exact_amount for item in allocations))
    return InvoiceLine(
        id=value.id,
        workspace_id=first.workspace_id,
        client_id=first.client_id,
        project_id=first.project_id,
        task_id=first.task_id,
        applied_rate_agreement_id=first.applied_rate.id,
        hourly_rate=first.hourly_rate,
        currency=currency,
        allocations=allocations,
        duration_microseconds=sum(item.duration_microseconds for item in allocations),
        exact_amount=exact_amount,
        rounded_amount=_round_half_up(exact_amount, currency),
    )


def _validate_allocations(lines: tuple[InvoiceLine, ...]) -> None:
    allocations = sorted(
        (allocation for line in lines for allocation in line.allocations),
        key=_allocation_order,
    )
    source_snapshots: dict[tuple[UUID, UUID], object] = {}
    for allocation in allocations:
        segment = allocation.priced_segment
        source = segment.segment.source_time_entry
        source_key = (segment.workspace_id, segment.source_time_entry_id)
        previous = source_snapshots.setdefault(source_key, source)
        if previous != source:
            raise IncompatibleInvoiceContextError(
                "One TimeEntry ID cannot have multiple source snapshots in a draft"
            )
    for previous, current in zip(allocations, allocations[1:], strict=False):
        previous_segment = previous.priced_segment
        current_segment = current.priced_segment
        if (
            previous_segment.workspace_id != current_segment.workspace_id
            or previous.source_time_entry_id != current.source_time_entry_id
        ):
            continue
        previous_start = previous.start.astimezone(UTC)
        previous_end = previous.end.astimezone(UTC)
        current_start = current.start.astimezone(UTC)
        current_end = current.end.astimezone(UTC)
        if previous_start == current_start and previous_end == current_end:
            raise DuplicateInvoiceAllocationError(
                "The same TimeEntry source segment cannot be allocated more than once"
            )
        if current_start < previous_end:
            raise OverlappingInvoiceAllocationError(
                "Allocations from the same TimeEntry must not overlap"
            )


def build_invoice_draft(
    *,
    draft_id: UUID,
    revision: int,
    workspace_id: UUID,
    client_id: UUID,
    line_inputs: tuple[InvoiceLineInput, ...],
) -> InvoiceDraft:
    """Build an auditable draft using caller-defined groups and confirmed MVP rounding."""
    if not isinstance(draft_id, UUID):
        raise InvalidInvoiceDraftError("InvoiceDraft ID must be a UUID")
    if type(revision) is not int or revision < 1:
        raise InvalidInvoiceDraftError("InvoiceDraft revision must be a positive integer")
    if not isinstance(workspace_id, UUID) or not isinstance(client_id, UUID):
        raise InvalidInvoiceDraftError("InvoiceDraft ownership IDs must be UUIDs")
    if type(line_inputs) is not tuple or any(
        not isinstance(line, InvoiceLineInput) for line in line_inputs
    ):
        raise InvalidInvoiceDraftError("InvoiceDraft line_inputs must be InvoiceLineInputs")
    if not line_inputs:
        raise InvalidInvoiceDraftError("InvoiceDraft requires at least one line")
    if len({line.id for line in line_inputs}) != len(line_inputs):
        raise InvalidInvoiceDraftError("InvoiceLine IDs must be unique within a draft")

    segments = tuple(segment for line in line_inputs for segment in line.priced_segments)
    currencies = {segment.currency for segment in segments}
    if len(currencies) != 1:
        raise MixedInvoiceCurrencyError("InvoiceDraft requires exactly one currency")
    currency = _currency_for(next(iter(currencies)))
    lines = tuple(_build_line(line, currency) for line in line_inputs)
    for line in lines:
        if line.workspace_id != workspace_id or line.client_id != client_id:
            raise IncompatibleInvoiceContextError(
                "Every InvoiceLine must belong to the draft workspace and client"
            )
    _validate_allocations(lines)
    exact_subtotal = _sum_exact(tuple(line.exact_amount for line in lines))
    subtotal = RoundedMoneyAmount(
        currency=currency,
        minor_units=sum(line.rounded_amount.minor_units for line in lines),
    )
    return InvoiceDraft(
        id=draft_id,
        revision=revision,
        workspace_id=workspace_id,
        client_id=client_id,
        currency=currency,
        lines=lines,
        exact_subtotal=exact_subtotal,
        subtotal=subtotal,
        total=subtotal,
    )
