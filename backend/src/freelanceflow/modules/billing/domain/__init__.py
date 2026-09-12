"""Pure effective-dated rate agreements and resolution."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from freelanceflow.modules.clients.domain import Client, Project


class RateError(ValueError):
    """Base error for invalid agreements or rate resolution."""


class InvalidRateAgreementError(RateError):
    """An agreement contains invalid values."""


class RateOwnershipError(RateError):
    """A project does not belong to the requested client and workspace."""


class MissingRateError(RateError):
    """No agreement applies to the requested business date and scope."""


class ConflictingRatesError(RateError):
    """Multiple agreements apply at the same precedence level."""


def _same_client(left: Client, right: Client) -> bool:
    return left.id == right.id and left.workspace_id == right.workspace_id


def _validate_project(client: Client, project: Project | None) -> None:
    if project is not None and not _same_client(client, project.client):
        raise RateOwnershipError("Project must belong to the same client and workspace")


@dataclass(frozen=True)
class RateAgreement:
    """Hourly rate over [valid_from, valid_until) in supplied business dates.

    No timezone conversion, rounding, currency conversion, or sign policy is applied.
    Client and optional project references carry workspace ownership.
    """

    client: Client
    hourly_amount: Decimal
    currency: str
    valid_from: date
    valid_until: date | None = None
    project: Project | None = None

    def __post_init__(self) -> None:
        _validate_project(self.client, self.project)
        if not isinstance(self.hourly_amount, Decimal) or not self.hourly_amount.is_finite():
            raise InvalidRateAgreementError("Hourly amount must be a finite Decimal")
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise InvalidRateAgreementError("Currency must be explicit and nonblank")
        if type(self.valid_from) is not date or (
            self.valid_until is not None and type(self.valid_until) is not date
        ):
            raise InvalidRateAgreementError("Validity boundaries must be dates, not timestamps")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise InvalidRateAgreementError("valid_until must be later than valid_from")


def resolve_rate(
    *,
    client: Client,
    business_date: date,
    agreements: Iterable[RateAgreement],
    project: Project | None = None,
) -> RateAgreement:
    """Return the applicable agreement, preserving its exact amount and currency.

    Dates are already interpreted by the caller. Unrelated scopes are ignored.
    Only the highest applicable precedence level is checked for conflicts.
    This checks applicability on the supplied date, not an entire rate schedule.
    """
    _validate_project(client, project)
    if type(business_date) is not date:
        raise RateError("business_date must be an already-interpreted date, not a timestamp")
    client_rates: list[RateAgreement] = []
    project_rates: list[RateAgreement] = []
    for agreement in agreements:
        if not _same_client(client, agreement.client):
            continue
        if business_date < agreement.valid_from or (
            agreement.valid_until is not None and business_date >= agreement.valid_until
        ):
            continue
        if agreement.project is None:
            client_rates.append(agreement)
        elif project is not None and agreement.project.id == project.id:
            project_rates.append(agreement)

    level, applicable = ("project", project_rates) if project_rates else ("client", client_rates)
    if len(applicable) > 1:
        raise ConflictingRatesError(f"Multiple {level} agreements apply on {business_date}")
    if applicable:
        return applicable[0]
    raise MissingRateError(f"No rate applies on {business_date}")
