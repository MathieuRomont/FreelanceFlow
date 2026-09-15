from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any, cast
from uuid import UUID

import pytest

from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceCurrency,
    InvoiceDraft,
    InvoiceLine,
    InvoiceLineInput,
    build_invoice_draft,
)
from freelanceflow.modules.billing.domain.invoice_settings import (
    EarlyPaymentDiscount,
    EarlyPaymentDiscountKind,
    FiscalSettings,
    FranchiseLegalBasis,
    InvoiceOperationCategory,
    PaymentDueRule,
    PaymentTerms,
    RecoveryIndemnityPolicy,
    VatRegime,
    WorkspaceInvoiceSettings,
)
from freelanceflow.modules.billing.domain.pricing import (
    ExactMoneyAmount,
    PreparedBillingSegment,
    PricedSegment,
    RateAgreementReference,
    price_prepared_segment,
)
from freelanceflow.modules.billing.domain.vat import (
    IncompatibleInvoiceTaxContextError,
    InvalidVatRateError,
    InvoiceLineVatRate,
    UnsupportedVatTreatmentError,
    VatRate,
    VatRoundingPolicy,
    calculate_invoice_vat,
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
    duration: timedelta = timedelta(hours=1),
) -> PricedSegment:
    entry = TimeEntry(
        id=UUID(int=entry_id),
        workspace_id=WORKSPACE_ID,
        start=START,
        end=START + duration,
        billable=True,
        client=CLIENT,
        project=PROJECT,
        task=TASK,
    )
    rate = RateAgreementReference(
        id=UUID(int=rate_id),
        agreement=RateAgreement(
            client=CLIENT,
            project=PROJECT,
            hourly_amount=Decimal(amount),
            currency="EUR",
            valid_from=BUSINESS_DATE,
        ),
    )
    segment = PreparedBillingSegment.for_complete_entry(entry, business_date=BUSINESS_DATE)
    return price_prepared_segment(segment, [rate])


def draft(*amounts: str, revision: int = 1) -> InvoiceDraft:
    return build_invoice_draft(
        draft_id=UUID(int=100),
        revision=revision,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT.id,
        line_inputs=tuple(
            InvoiceLineInput(
                id=UUID(int=30 + index),
                priced_segments=(priced(amount, entry_id=10 + index, rate_id=20 + index),),
            )
            for index, amount in enumerate(amounts)
        ),
    )


def settings(
    fiscal: FiscalSettings, *, workspace_id: UUID = WORKSPACE_ID
) -> WorkspaceInvoiceSettings:
    return WorkspaceInvoiceSettings(
        workspace_id=workspace_id,
        fiscal=fiscal,
        payment_terms=PaymentTerms(PaymentDueRule.NET_DAYS_AFTER_ISSUE, 30),
        early_payment_discount=EarlyPaymentDiscount(EarlyPaymentDiscountKind.NONE),
        late_payment_penalty_annual_rate_percent=Decimal("12.5"),
        recovery_indemnity_policy=RecoveryIndemnityPolicy.FRENCH_B2B_40_EUR,
        operation_category=InvoiceOperationCategory.SERVICES,
    )


def franchise() -> WorkspaceInvoiceSettings:
    return settings(
        FiscalSettings(
            vat_regime=VatRegime.FRANCHISE_EN_BASE,
            franchise_legal_basis=FranchiseLegalBasis.CGI_ARTICLE_293_B,
            default_vat_rate_percent=None,
            vat_on_debits=False,
        )
    )


def taxable(rate: str = "20") -> WorkspaceInvoiceSettings:
    return settings(
        FiscalSettings(
            vat_regime=VatRegime.TAXABLE,
            franchise_legal_basis=None,
            default_vat_rate_percent=Decimal(rate),
            vat_on_debits=True,
        )
    )


def test_franchise_en_base_retains_legal_treatment_without_zero_rate() -> None:
    invoice = draft("100")
    result = calculate_invoice_vat(invoice, franchise())
    breakdown = result.vat_breakdowns[0]

    assert result.vat_regime is VatRegime.FRANCHISE_EN_BASE
    assert breakdown.vat_rate is None
    assert breakdown.franchise_legal_basis is FranchiseLegalBasis.CGI_ARTICLE_293_B
    assert breakdown.franchise_invoice_mention == "TVA non applicable, article 293 B du CGI"
    assert breakdown.exact_vat_amount == ExactMoneyAmount(0, 1)
    assert result.ht_total.minor_units == 10_000
    assert result.vat_total.minor_units == 0
    assert result.ttc_total.minor_units == 10_000


def test_taxable_invoice_uses_exact_rate_and_reconciles_ht_vat_ttc() -> None:
    invoice = draft("100", revision=3)
    result = calculate_invoice_vat(invoice, taxable("20.000"))
    breakdown = result.vat_breakdowns[0]

    assert result.invoice_id == invoice.id
    assert result.invoice_revision == 3
    assert result.rounding_policy is VatRoundingPolicy.PER_RATE_SUBTOTAL_HALF_UP
    assert breakdown.vat_rate == VatRate(Decimal("20.000"))
    assert breakdown.exact_vat_amount == ExactMoneyAmount(20, 1)
    assert result.ht_total.minor_units == 10_000
    assert result.vat_total.minor_units == 2_000
    assert result.ttc_total.minor_units == 12_000


@pytest.mark.parametrize(
    "rate,expected_vat_minor_units",
    [("0.49", 0), ("0.5", 1), ("0.51", 1)],
)
def test_vat_half_cent_boundaries_use_explicit_half_up(
    rate: str, expected_vat_minor_units: int
) -> None:
    result = calculate_invoice_vat(draft("1"), taxable(rate))
    assert result.vat_total.minor_units == expected_vat_minor_units


def test_vat_is_rounded_once_per_rate_subtotal_not_per_line() -> None:
    invoice = draft("0.02", "0.02")
    result = calculate_invoice_vat(invoice, taxable("20"))

    assert [line.rounded_amount.minor_units for line in invoice.lines] == [2, 2]
    assert result.vat_breakdowns[0].ht_base.minor_units == 4
    assert result.vat_breakdowns[0].exact_vat_amount == ExactMoneyAmount(1, 125)
    assert result.vat_total.minor_units == 1
    # Rounding each line's 0.004 EUR VAT would incorrectly produce zero in total.


def test_vat_base_uses_rounded_lines_while_exact_source_ht_remains_auditable() -> None:
    invoice = draft("0.004", "0.004")
    result = calculate_invoice_vat(invoice, taxable("20"))
    breakdown = result.vat_breakdowns[0]

    assert invoice.exact_subtotal == ExactMoneyAmount(1, 125)
    assert breakdown.exact_source_ht == invoice.exact_subtotal
    assert breakdown.ht_base.minor_units == 0
    assert breakdown.exact_vat_amount == ExactMoneyAmount(0, 1)


def test_multiple_explicit_rate_groups_are_complete_ordered_and_reconciled() -> None:
    invoice = draft("100", "100")
    assignments = (
        InvoiceLineVatRate(invoice.lines[0].id, VatRate(Decimal("20"))),
        InvoiceLineVatRate(invoice.lines[1].id, VatRate(Decimal("10"))),
    )
    result = calculate_invoice_vat(invoice, taxable("20"), line_vat_rates=assignments)

    assert [item.vat_rate.percent for item in result.vat_breakdowns if item.vat_rate] == [
        Decimal("10"),
        Decimal("20"),
    ]
    assert [item.invoice_line_ids for item in result.vat_breakdowns] == [
        (invoice.lines[1].id,),
        (invoice.lines[0].id,),
    ]
    assert result.ht_total.minor_units == 20_000
    assert result.vat_total.minor_units == 3_000
    assert result.ttc_total.minor_units == 23_000


def test_zero_base_and_zero_taxable_rate_remain_explicitly_taxable() -> None:
    result = calculate_invoice_vat(draft("0"), taxable("0"))
    breakdown = result.vat_breakdowns[0]
    assert result.vat_regime is VatRegime.TAXABLE
    assert breakdown.vat_rate == VatRate(Decimal("0"))
    assert result.ht_total.minor_units == 0
    assert result.vat_total.minor_units == 0
    assert result.ttc_total.minor_units == 0


@pytest.mark.parametrize(
    "value",
    [Decimal("-0.01"), Decimal("100.01"), Decimal("NaN"), Decimal("Infinity")],
)
def test_invalid_vat_rates_fail_explicitly(value: Decimal) -> None:
    with pytest.raises(InvalidVatRateError):
        VatRate(value)
    with pytest.raises(InvalidVatRateError):
        VatRate(cast(Any, 20.0))


def test_explicit_rates_must_cover_each_line_exactly_once() -> None:
    invoice = draft("1", "2")
    rate = VatRate(Decimal("20"))
    missing = (InvoiceLineVatRate(invoice.lines[0].id, rate),)
    duplicate = (missing[0], missing[0])
    unknown = (
        missing[0],
        InvoiceLineVatRate(UUID(int=999), rate),
    )
    for assignments in (missing, duplicate, unknown):
        with pytest.raises(IncompatibleInvoiceTaxContextError):
            calculate_invoice_vat(invoice, taxable(), line_vat_rates=assignments)
    with pytest.raises(IncompatibleInvoiceTaxContextError):
        calculate_invoice_vat(
            invoice,
            taxable(),
            line_vat_rates=cast(Any, list(missing)),
        )


def test_franchise_rejects_ordinary_vat_rate_assignments() -> None:
    invoice = draft("1")
    assignment = InvoiceLineVatRate(invoice.lines[0].id, VatRate(Decimal("0")))
    with pytest.raises(IncompatibleInvoiceTaxContextError, match="Franchise"):
        calculate_invoice_vat(invoice, franchise(), line_vat_rates=(assignment,))


def test_workspace_mismatch_and_unsupported_inputs_fail() -> None:
    invoice = draft("1")
    other_settings = settings(
        taxable().fiscal,
        workspace_id=UUID(int=999),
    )
    with pytest.raises(IncompatibleInvoiceTaxContextError, match="workspace"):
        calculate_invoice_vat(invoice, other_settings)
    with pytest.raises(IncompatibleInvoiceTaxContextError):
        calculate_invoice_vat(cast(Any, object()), taxable())
    with pytest.raises(UnsupportedVatTreatmentError):
        calculate_invoice_vat(invoice, cast(Any, object()))


def test_corrupt_mixed_currency_snapshot_is_rejected_at_tax_boundary() -> None:
    invoice = draft("1")
    other_currency = object.__new__(InvoiceCurrency)
    object.__setattr__(other_currency, "code", "USD")
    object.__setattr__(other_currency, "decimal_places", 2)
    bad_line = object.__new__(InvoiceLine)
    for field in fields(InvoiceLine):
        object.__setattr__(bad_line, field.name, getattr(invoice.lines[0], field.name))
    object.__setattr__(bad_line, "currency", other_currency)
    corrupted = object.__new__(InvoiceDraft)
    for field in fields(InvoiceDraft):
        object.__setattr__(corrupted, field.name, getattr(invoice, field.name))
    object.__setattr__(corrupted, "lines", (bad_line,))

    with pytest.raises(IncompatibleInvoiceTaxContextError, match="currency"):
        calculate_invoice_vat(corrupted, taxable())


def test_calculation_is_deterministic_independent_of_decimal_context() -> None:
    invoice = draft("123.45", "0.02")
    assignments = tuple(
        InvoiceLineVatRate(line.id, VatRate(Decimal("19.625"))) for line in invoice.lines
    )
    expected = calculate_invoice_vat(invoice, taxable(), line_vat_rates=assignments)
    with localcontext() as context:
        context.prec = 1
        context.rounding = ROUND_DOWN
        actual = calculate_invoice_vat(invoice, taxable(), line_vat_rates=assignments)
    assert actual == expected
