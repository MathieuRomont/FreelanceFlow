import os
import time
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from freelanceflow.modules.billing.domain.invoice_dates import (
    InvalidInvoiceDateInputError,
    MissingBillingTimezoneError,
    derive_invoice_issue_date,
    derive_payment_due_date,
)
from freelanceflow.modules.billing.domain.invoice_settings import (
    BillingTimezone,
    InvalidInvoiceSettings,
    PaymentDueRule,
    PaymentTerms,
)


def test_billing_timezone_requires_a_valid_iana_identifier() -> None:
    paris = BillingTimezone("Europe/Paris")
    assert paris.name == "Europe/Paris"
    assert paris.to_zoneinfo().key == "Europe/Paris"

    for value in ("", " ", "+02:00", "Europe/Not_A_Zone"):
        with pytest.raises(InvalidInvoiceSettings, match="timezone"):
            BillingTimezone(value)
    with pytest.raises(InvalidInvoiceSettings, match="timezone"):
        BillingTimezone(cast(Any, 2))


def test_issue_date_changes_at_local_midnight_not_utc_midnight() -> None:
    paris = BillingTimezone("Europe/Paris")
    assert derive_invoice_issue_date(
        datetime(2026, 1, 31, 22, 59, 59, 999999, tzinfo=UTC), paris
    ) == date(2026, 1, 31)
    assert derive_invoice_issue_date(datetime(2026, 1, 31, 23, 0, tzinfo=UTC), paris) == date(
        2026, 2, 1
    )


def test_issue_date_is_deterministic_across_paris_spring_dst_transition() -> None:
    paris = BillingTimezone("Europe/Paris")
    before_jump = datetime(2026, 3, 29, 0, 59, 59, 999999, tzinfo=UTC)
    after_jump = datetime(2026, 3, 29, 1, 0, tzinfo=UTC)

    assert before_jump.astimezone(paris.to_zoneinfo()).isoformat() == (
        "2026-03-29T01:59:59.999999+01:00"
    )
    assert after_jump.astimezone(paris.to_zoneinfo()).isoformat() == ("2026-03-29T03:00:00+02:00")
    assert derive_invoice_issue_date(before_jump, paris) == date(2026, 3, 29)
    assert derive_invoice_issue_date(after_jump, paris) == date(2026, 3, 29)


def test_issue_date_is_deterministic_across_paris_autumn_dst_fold() -> None:
    paris = BillingTimezone("Europe/Paris")
    first_occurrence = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    second_occurrence = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    first_local = first_occurrence.astimezone(paris.to_zoneinfo())
    second_local = second_occurrence.astimezone(paris.to_zoneinfo())

    assert (first_local.hour, first_local.minute, first_local.fold) == (2, 30, 0)
    assert (second_local.hour, second_local.minute, second_local.fold) == (2, 30, 1)
    assert derive_invoice_issue_date(first_occurrence, paris) == date(2026, 10, 25)
    assert derive_invoice_issue_date(second_occurrence, paris) == date(2026, 10, 25)


def test_issue_date_does_not_depend_on_host_timezone() -> None:
    original_timezone = os.environ.get("TZ")
    instant = datetime(2026, 7, 1, 22, 30, tzinfo=UTC)
    paris = BillingTimezone("Europe/Paris")
    try:
        results = []
        for host_timezone in ("Pacific/Honolulu", "Asia/Tokyo", "UTC"):
            os.environ["TZ"] = host_timezone
            time.tzset()
            results.append(derive_invoice_issue_date(instant, paris))
    finally:
        if original_timezone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_timezone
        time.tzset()

    assert results == [date(2026, 7, 2)] * 3


def test_issue_date_requires_configured_timezone_and_utc_aware_instant() -> None:
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(MissingBillingTimezoneError, match="not configured"):
        derive_invoice_issue_date(instant, None)
    with pytest.raises(InvalidInvoiceDateInputError, match="UTC"):
        derive_invoice_issue_date(datetime(2026, 1, 1), BillingTimezone("Europe/Paris"))
    with pytest.raises(InvalidInvoiceDateInputError, match="UTC"):
        derive_invoice_issue_date(
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
            BillingTimezone("Europe/Paris"),
        )


@pytest.mark.parametrize(
    "issue_date,payment_terms,expected",
    [
        (
            date(2026, 3, 1),
            PaymentTerms(PaymentDueRule.DUE_ON_ISSUE),
            date(2026, 3, 1),
        ),
        (
            date(2026, 12, 20),
            PaymentTerms(PaymentDueRule.NET_DAYS_AFTER_ISSUE, 30),
            date(2027, 1, 19),
        ),
        (
            date(2026, 3, 1),
            PaymentTerms(PaymentDueRule.INVOICE_MONTH_END_PLUS_45_DAYS),
            date(2026, 5, 15),
        ),
        (
            date(2026, 3, 1),
            PaymentTerms(PaymentDueRule.END_OF_MONTH_AFTER_45_DAYS),
            date(2026, 4, 30),
        ),
    ],
)
def test_every_supported_payment_term_has_an_exact_calendar_algorithm(
    issue_date: date,
    payment_terms: PaymentTerms,
    expected: date,
) -> None:
    assert derive_payment_due_date(issue_date, payment_terms) == expected


def test_month_end_calculations_handle_leap_february() -> None:
    issue_date = date(2024, 1, 15)
    assert derive_payment_due_date(
        issue_date,
        PaymentTerms(PaymentDueRule.INVOICE_MONTH_END_PLUS_45_DAYS),
    ) == date(2024, 3, 16)
    assert derive_payment_due_date(
        issue_date,
        PaymentTerms(PaymentDueRule.END_OF_MONTH_AFTER_45_DAYS),
    ) == date(2024, 2, 29)


def test_month_end_plus_45_crosses_year_boundary_deterministically() -> None:
    assert derive_payment_due_date(
        date(2026, 12, 1),
        PaymentTerms(PaymentDueRule.INVOICE_MONTH_END_PLUS_45_DAYS),
    ) == date(2027, 2, 14)


def test_due_date_rejects_timestamp_and_date_overflow() -> None:
    with pytest.raises(InvalidInvoiceDateInputError, match="must be a date"):
        derive_payment_due_date(
            cast(Any, datetime(2026, 1, 1, tzinfo=UTC)),
            PaymentTerms(PaymentDueRule.DUE_ON_ISSUE),
        )
    with pytest.raises(InvalidInvoiceDateInputError, match="exceeds"):
        derive_payment_due_date(
            date.max,
            PaymentTerms(PaymentDueRule.NET_DAYS_AFTER_ISSUE, 1),
        )
