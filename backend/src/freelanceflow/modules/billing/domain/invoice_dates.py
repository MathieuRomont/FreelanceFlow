"""Pure deterministic invoice issue-date and payment-due-date policies."""

from calendar import monthrange
from datetime import date, datetime, timedelta

from freelanceflow.modules.billing.domain.invoice_settings import (
    BillingTimezone,
    PaymentDueRule,
    PaymentTerms,
)


class InvoiceDatePolicyError(ValueError):
    """Base error for invoice date-policy failures."""


class MissingBillingTimezoneError(InvoiceDatePolicyError):
    """Invoice dates cannot be derived without configured billing timezone."""


class InvalidInvoiceDateInputError(InvoiceDatePolicyError):
    """A supplied instant, date, or payment rule cannot be interpreted safely."""


class UnsupportedPaymentDueRuleError(InvoiceDatePolicyError):
    """A payment rule has no confirmed deterministic due-date policy."""


def derive_invoice_issue_date(
    issued_at_utc: datetime,
    billing_timezone: BillingTimezone | None,
) -> date:
    """Convert one explicit UTC instant to its configured local business date."""
    if not isinstance(issued_at_utc, datetime) or issued_at_utc.utcoffset() != timedelta(0):
        raise InvalidInvoiceDateInputError(
            "Invoice issue instant must be a timezone-aware UTC timestamp"
        )
    if billing_timezone is None:
        raise MissingBillingTimezoneError("Workspace billing timezone is not configured")
    if not isinstance(billing_timezone, BillingTimezone):
        raise InvalidInvoiceDateInputError("Workspace billing timezone is invalid")
    return issued_at_utc.astimezone(billing_timezone.to_zoneinfo()).date()


def _end_of_month(value: date) -> date:
    return date(value.year, value.month, monthrange(value.year, value.month)[1])


def derive_payment_due_date(issue_date: date, payment_terms: PaymentTerms) -> date:
    """Apply one confirmed calendar payment rule to an explicit invoice issue date."""
    if type(issue_date) is not date:
        raise InvalidInvoiceDateInputError("Invoice issue date must be a date")
    if not isinstance(payment_terms, PaymentTerms):
        raise InvalidInvoiceDateInputError("Payment terms are invalid")
    try:
        if payment_terms.due_rule is PaymentDueRule.DUE_ON_ISSUE:
            return issue_date
        if payment_terms.due_rule is PaymentDueRule.NET_DAYS_AFTER_ISSUE:
            assert payment_terms.net_days is not None
            return issue_date + timedelta(days=payment_terms.net_days)
        if payment_terms.due_rule is PaymentDueRule.INVOICE_MONTH_END_PLUS_45_DAYS:
            return _end_of_month(issue_date) + timedelta(days=45)
        if payment_terms.due_rule is PaymentDueRule.END_OF_MONTH_AFTER_45_DAYS:
            return _end_of_month(issue_date + timedelta(days=45))
    except OverflowError as error:
        raise InvalidInvoiceDateInputError(
            "Derived payment due date exceeds the supported date range"
        ) from error
    raise UnsupportedPaymentDueRuleError(
        f"Payment due rule {payment_terms.due_rule!r} is unsupported"
    )
