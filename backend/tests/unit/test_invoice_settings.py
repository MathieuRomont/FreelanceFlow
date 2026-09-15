from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest

from freelanceflow.modules.billing.domain.invoice_settings import (
    EarlyPaymentDiscount,
    EarlyPaymentDiscountKind,
    FiscalSettings,
    FranchiseLegalBasis,
    InvalidInvoiceSettings,
    InvoiceOperationCategory,
    PaymentDueRule,
    PaymentTerms,
    RecoveryIndemnityPolicy,
    VatRegime,
    WorkspaceInvoiceSettings,
    canonical_franchise_invoice_mention,
    parse_exact_percentage,
)

WORKSPACE_ID = UUID(int=1)


def franchise_fiscal(
    basis: FranchiseLegalBasis = FranchiseLegalBasis.CGI_ARTICLE_293_B,
) -> FiscalSettings:
    return FiscalSettings(
        vat_regime=VatRegime.FRANCHISE_EN_BASE,
        franchise_legal_basis=basis,
        default_vat_rate_percent=None,
        vat_on_debits=False,
    )


def taxable_fiscal(rate: Decimal = Decimal("20.000")) -> FiscalSettings:
    return FiscalSettings(
        vat_regime=VatRegime.TAXABLE,
        franchise_legal_basis=None,
        default_vat_rate_percent=rate,
        vat_on_debits=True,
    )


def settings(**changes: object) -> WorkspaceInvoiceSettings:
    values: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "fiscal": franchise_fiscal(),
        "payment_terms": PaymentTerms(PaymentDueRule.NET_DAYS_AFTER_ISSUE, 30),
        "early_payment_discount": EarlyPaymentDiscount(EarlyPaymentDiscountKind.NONE),
        "late_payment_penalty_annual_rate_percent": Decimal("12.50"),
        "recovery_indemnity_policy": RecoveryIndemnityPolicy.FRENCH_B2B_40_EUR,
        "operation_category": InvoiceOperationCategory.SERVICES,
    }
    values.update(changes)
    return WorkspaceInvoiceSettings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "basis,mention",
    [
        (
            FranchiseLegalBasis.CGI_ARTICLE_293_B,
            "TVA non applicable, article 293 B du CGI",
        ),
        (
            FranchiseLegalBasis.CGI_ARTICLE_293_B_BIS,
            "TVA non applicable, article 293 B bis du CGI",
        ),
        (
            FranchiseLegalBasis.EU_DIRECTIVE_2006_112_ARTICLE_284,
            "TVA non applicable, article 284 de la directive 2006/112/CE",
        ),
    ],
)
def test_franchise_en_base_has_structured_basis_and_canonical_mention(
    basis: FranchiseLegalBasis, mention: str
) -> None:
    fiscal = franchise_fiscal(basis)
    assert fiscal.franchise_invoice_mention == mention
    assert canonical_franchise_invoice_mention(basis) == mention
    assert fiscal.default_vat_rate_percent is None


def test_taxable_configuration_preserves_exact_vat_rate_and_debits_choice() -> None:
    fiscal = taxable_fiscal(Decimal("20.000"))
    assert str(fiscal.default_vat_rate_percent) == "20.000"
    assert fiscal.franchise_invoice_mention is None
    assert fiscal.vat_on_debits is True


@pytest.mark.parametrize(
    "arguments,match",
    [
        (
            (VatRegime.FRANCHISE_EN_BASE, None, None, False),
            "legal basis",
        ),
        (
            (
                VatRegime.FRANCHISE_EN_BASE,
                FranchiseLegalBasis.CGI_ARTICLE_293_B,
                Decimal("20"),
                False,
            ),
            "must not define",
        ),
        (
            (
                VatRegime.FRANCHISE_EN_BASE,
                FranchiseLegalBasis.CGI_ARTICLE_293_B,
                None,
                True,
            ),
            "cannot select",
        ),
        (
            (
                VatRegime.TAXABLE,
                FranchiseLegalBasis.CGI_ARTICLE_293_B,
                Decimal("20"),
                False,
            ),
            "must not define",
        ),
        ((VatRegime.TAXABLE, None, None, False), "required"),
        ((VatRegime.TAXABLE, None, Decimal("-0.01"), False), "nonnegative"),
        ((VatRegime.TAXABLE, None, Decimal("100.01"), False), "exceed"),
        ((VatRegime.TAXABLE, None, Decimal("NaN"), False), "finite"),
        ((VatRegime.TAXABLE, None, 20.0, False), "finite Decimal"),
    ],
)
def test_invalid_vat_regime_combinations(
    arguments: tuple[object, object, object, object], match: str
) -> None:
    with pytest.raises(InvalidInvoiceSettings, match=match):
        FiscalSettings(*arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "terms",
    [
        PaymentTerms(PaymentDueRule.DUE_ON_ISSUE),
        PaymentTerms(PaymentDueRule.NET_DAYS_AFTER_ISSUE, 1),
        PaymentTerms(PaymentDueRule.NET_DAYS_AFTER_ISSUE, 60),
        PaymentTerms(PaymentDueRule.INVOICE_MONTH_END_PLUS_45_DAYS),
        PaymentTerms(PaymentDueRule.END_OF_MONTH_AFTER_45_DAYS),
    ],
)
def test_payment_term_rules_are_explicit_without_calculating_due_date(
    terms: PaymentTerms,
) -> None:
    assert isinstance(terms.due_rule, PaymentDueRule)


@pytest.mark.parametrize(
    "rule,days",
    [
        (PaymentDueRule.NET_DAYS_AFTER_ISSUE, None),
        (PaymentDueRule.NET_DAYS_AFTER_ISSUE, 0),
        (PaymentDueRule.NET_DAYS_AFTER_ISSUE, 61),
        (PaymentDueRule.DUE_ON_ISSUE, 1),
        (PaymentDueRule.INVOICE_MONTH_END_PLUS_45_DAYS, 45),
    ],
)
def test_invalid_payment_terms(rule: PaymentDueRule, days: int | None) -> None:
    with pytest.raises(InvalidInvoiceSettings):
        PaymentTerms(rule, days)


def test_early_payment_discount_is_structured() -> None:
    none = EarlyPaymentDiscount(EarlyPaymentDiscountKind.NONE)
    offered = EarlyPaymentDiscount(
        EarlyPaymentDiscountKind.PERCENTAGE_WITHIN_DAYS,
        Decimal("2.500"),
        10,
    )
    assert none.rate_percent is None
    assert str(offered.rate_percent) == "2.500"
    assert offered.days_after_issue == 10


@pytest.mark.parametrize(
    "discount",
    [
        lambda: EarlyPaymentDiscount(EarlyPaymentDiscountKind.NONE, Decimal("1"), None),
        lambda: EarlyPaymentDiscount(EarlyPaymentDiscountKind.PERCENTAGE_WITHIN_DAYS, None, 10),
        lambda: EarlyPaymentDiscount(
            EarlyPaymentDiscountKind.PERCENTAGE_WITHIN_DAYS, Decimal("0"), 10
        ),
        lambda: EarlyPaymentDiscount(
            EarlyPaymentDiscountKind.PERCENTAGE_WITHIN_DAYS, Decimal("1"), 0
        ),
        lambda: EarlyPaymentDiscount(
            EarlyPaymentDiscountKind.PERCENTAGE_WITHIN_DAYS, cast(Any, 1.0), 10
        ),
    ],
)
def test_invalid_early_payment_discount(discount: Callable[[], object]) -> None:
    with pytest.raises(InvalidInvoiceSettings):
        discount()


def test_late_penalty_and_recovery_indemnity_semantics() -> None:
    value = settings()
    assert value.late_payment_penalty_annual_rate_percent == Decimal("12.50")
    assert value.recovery_indemnity_policy is RecoveryIndemnityPolicy.FRENCH_B2B_40_EUR
    assert value.recovery_indemnity_currency == "EUR"
    assert value.recovery_indemnity_minor_units == 4_000
    for rate in [Decimal("0"), Decimal("-1"), Decimal("Infinity")]:
        with pytest.raises(InvalidInvoiceSettings):
            replace(value, late_payment_penalty_annual_rate_percent=rate)
    with pytest.raises(InvalidInvoiceSettings):
        replace(
            value,
            late_payment_penalty_annual_rate_percent=cast(Any, 12.5),
        )


def test_exact_percentage_parser_never_accepts_float_or_nonfinite() -> None:
    parsed = parse_exact_percentage("20.000100", field="Rate")
    assert parsed is not None and str(parsed) == "20.000100"
    for value in [20.0, "NaN", "Infinity", "invalid"]:
        with pytest.raises(InvalidInvoiceSettings):
            parse_exact_percentage(value, field="Rate")  # type: ignore[arg-type]
