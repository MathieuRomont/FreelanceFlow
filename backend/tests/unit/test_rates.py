from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from freelanceflow.modules.billing.domain import (
    ConflictingRatesError,
    InvalidRateAgreementError,
    MissingRateError,
    RateAgreement,
    RateError,
    RateOwnershipError,
    resolve_rate,
)
from freelanceflow.modules.clients.domain import Client, Project

CLIENT = Client(UUID(int=1), UUID(int=2), "Example client")
PROJECT = Project(UUID(int=3), CLIENT, "Example project")
START = date(2026, 1, 1)
CHANGE = date(2026, 9, 1)


def rate(amount: str = "80", *, project: Project | None = None) -> RateAgreement:
    return RateAgreement(CLIENT, Decimal(amount), "EUR", START, project=project)


def test_project_belongs_to_one_client_and_workspace() -> None:
    assert PROJECT.client is CLIENT
    assert PROJECT.client.workspace_id == UUID(int=2)


def test_client_rate() -> None:
    agreement = rate()
    result = resolve_rate(client=CLIENT, business_date=START, agreements=[agreement])
    assert result is agreement
    assert result.hourly_amount == Decimal("80")
    assert result.currency == "EUR"


@pytest.mark.parametrize("reverse", [False, True])
def test_project_override(reverse: bool) -> None:
    project_rate = rate("100", project=PROJECT)
    agreements = [rate(), project_rate]
    if reverse:
        agreements.reverse()
    result = resolve_rate(
        client=CLIENT, project=PROJECT, business_date=START, agreements=agreements
    )
    assert result is project_rate
    assert result.hourly_amount == Decimal("100")


@pytest.mark.parametrize("day", [START, date(2026, 8, 31), CHANGE, date(2099, 1, 1)])
def test_historical_rates_and_half_open_boundaries(day: date) -> None:
    old = replace(rate(), valid_until=CHANGE)
    new = replace(rate("90"), valid_from=CHANGE)
    result = resolve_rate(client=CLIENT, business_date=day, agreements=[new, old])
    assert result is (old if day < CHANGE else new)


@pytest.mark.parametrize("day", [date(2025, 12, 31), CHANGE, date(2027, 1, 1)])
def test_missing_outside_validity(day: date) -> None:
    with pytest.raises(MissingRateError):
        resolve_rate(
            client=CLIENT, business_date=day, agreements=[replace(rate(), valid_until=CHANGE)]
        )


def test_missing_without_agreements() -> None:
    with pytest.raises(MissingRateError):
        resolve_rate(client=CLIENT, business_date=START, agreements=[])


def test_project_falls_back_to_client_outside_project_validity() -> None:
    client_rate = rate()
    project_rate = replace(rate("100", project=PROJECT), valid_from=CHANGE)
    assert (
        resolve_rate(
            client=CLIENT,
            project=PROJECT,
            business_date=START,
            agreements=[client_rate, project_rate],
        )
        is client_rate
    )


@pytest.mark.parametrize("project", [None, PROJECT])
@pytest.mark.parametrize("second_amount", ["80", "90"])
def test_same_level_conflicts(project: Project | None, second_amount: str) -> None:
    with pytest.raises(ConflictingRatesError):
        resolve_rate(
            client=CLIENT,
            project=project,
            business_date=CHANGE,
            agreements=[
                rate(project=project),
                replace(rate(second_amount, project=project), valid_from=CHANGE),
            ],
        )


@pytest.mark.parametrize("reverse", [False, True])
def test_unique_project_rate_overrides_client_conflict(reverse: bool) -> None:
    project_rate = rate("100", project=PROJECT)
    agreements = [rate(), rate("90"), project_rate]
    if reverse:
        agreements.reverse()
    assert resolve_rate(
        client=CLIENT, project=PROJECT, business_date=START, agreements=agreements
    ) is project_rate


@pytest.mark.parametrize("day", [date(2025, 12, 31), CHANGE])
def test_client_conflict_when_no_project_rate_applies(day: date) -> None:
    project_rate = replace(rate("100", project=PROJECT), valid_until=CHANGE)
    client_rates = [replace(rate(amount), valid_from=date(2025, 1, 1)) for amount in ("80", "90")]
    with pytest.raises(ConflictingRatesError, match="Multiple client agreements"):
        resolve_rate(
            client=CLIENT, project=PROJECT, business_date=day,
            agreements=[project_rate, *client_rates],
        )


@pytest.mark.parametrize("client_amounts", [("80",), ("80", "90")])
def test_conflicting_project_rates_do_not_fall_back_to_client(
    client_amounts: tuple[str, ...],
) -> None:
    with pytest.raises(ConflictingRatesError, match="Multiple project agreements"):
        resolve_rate(
            client=CLIENT,
            project=PROJECT,
            business_date=START,
            agreements=[
                *(rate(amount) for amount in client_amounts),
                rate("100", project=PROJECT), rate("110", project=PROJECT),
            ],
        )


def test_decimal_precision_is_preserved_without_rounding() -> None:
    amount = "80.123456789012345678901234567890123456789"
    result = resolve_rate(client=CLIENT, business_date=START, agreements=[rate(amount)])
    assert isinstance(result.hourly_amount, Decimal)
    assert str(result.hourly_amount) == amount


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_nonfinite_amount_is_invalid(amount: Decimal) -> None:
    with pytest.raises(InvalidRateAgreementError):
        replace(rate(), hourly_amount=amount)


def test_float_amount_is_rejected_without_conversion() -> None:
    with pytest.raises(InvalidRateAgreementError):
        RateAgreement(CLIENT, 80.1, "EUR", START)  # type: ignore[arg-type]


@pytest.mark.parametrize("currency", ["", "   "])
def test_currency_is_required(currency: str) -> None:
    with pytest.raises(InvalidRateAgreementError):
        replace(rate(), currency=currency)


def test_different_currencies_do_not_hide_same_scope_conflicts() -> None:
    with pytest.raises(ConflictingRatesError):
        resolve_rate(
            client=CLIENT,
            business_date=START,
            agreements=[rate(), replace(rate(), currency="USD")],
        )


@pytest.mark.parametrize("end", [START, date(2025, 1, 1)])
def test_empty_or_reversed_interval_is_invalid(end: date) -> None:
    with pytest.raises(InvalidRateAgreementError):
        replace(rate(), valid_until=end)


def test_timestamps_are_not_business_dates() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(InvalidRateAgreementError):
        replace(rate(), valid_from=timestamp)
    with pytest.raises(InvalidRateAgreementError):
        replace(rate(), valid_until=timestamp)
    with pytest.raises(RateError):
        resolve_rate(client=CLIENT, business_date=timestamp, agreements=[rate()])


@pytest.mark.parametrize(
    "other_client",
    [
        replace(CLIENT, id=UUID(int=4)),
        replace(CLIENT, workspace_id=UUID(int=5)),
    ],
)
def test_ownership_mismatch_is_rejected(other_client: Client) -> None:
    wrong_project = replace(PROJECT, client=other_client)
    with pytest.raises(RateOwnershipError):
        rate(project=wrong_project)
    with pytest.raises(RateOwnershipError):
        resolve_rate(client=CLIENT, project=wrong_project, business_date=START, agreements=[rate()])


def test_unrelated_scopes_are_ignored() -> None:
    unrelated = [
        replace(rate(), client=replace(CLIENT, id=UUID(int=4))),
        replace(rate(), client=replace(CLIENT, workspace_id=UUID(int=5))),
        rate(project=replace(PROJECT, id=UUID(int=6))),
    ]
    with pytest.raises(MissingRateError):
        resolve_rate(client=CLIENT, project=PROJECT, business_date=START, agreements=unrelated)
    with pytest.raises(MissingRateError):
        resolve_rate(client=CLIENT, business_date=START, agreements=[rate(project=PROJECT)])


def test_client_identity_does_not_depend_on_name() -> None:
    agreement = rate()
    assert (
        resolve_rate(
            client=replace(CLIENT, name="Renamed"), business_date=START, agreements=[agreement]
        )
        is agreement
    )
