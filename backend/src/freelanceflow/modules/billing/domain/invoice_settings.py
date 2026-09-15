"""Mutable France-first fiscal and payment defaults for future invoice issuance."""

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from enum import StrEnum
from uuid import UUID


class InvalidInvoiceSettings(ValueError):
    """Invoice defaults are incomplete, inconsistent, or locally invalid."""


class VatRegime(StrEnum):
    FRANCHISE_EN_BASE = "franchise_en_base"
    TAXABLE = "taxable"


class FranchiseLegalBasis(StrEnum):
    CGI_ARTICLE_293_B = "cgi_293_b"
    CGI_ARTICLE_293_B_BIS = "cgi_293_b_bis"
    EU_DIRECTIVE_2006_112_ARTICLE_284 = "eu_directive_2006_112_article_284"


class InvoiceOperationCategory(StrEnum):
    SERVICES = "services"


class PaymentDueRule(StrEnum):
    DUE_ON_ISSUE = "due_on_issue"
    NET_DAYS_AFTER_ISSUE = "net_days_after_issue"
    INVOICE_MONTH_END_PLUS_45_DAYS = "invoice_month_end_plus_45_days"
    END_OF_MONTH_AFTER_45_DAYS = "end_of_month_after_45_days"


class EarlyPaymentDiscountKind(StrEnum):
    NONE = "none"
    PERCENTAGE_WITHIN_DAYS = "percentage_within_days"


class RecoveryIndemnityPolicy(StrEnum):
    FRENCH_B2B_40_EUR = "french_b2b_40_eur"


_FRANCHISE_MENTIONS = {
    FranchiseLegalBasis.CGI_ARTICLE_293_B: ("TVA non applicable, article 293 B du CGI"),
    FranchiseLegalBasis.CGI_ARTICLE_293_B_BIS: ("TVA non applicable, article 293 B bis du CGI"),
    FranchiseLegalBasis.EU_DIRECTIVE_2006_112_ARTICLE_284: (
        "TVA non applicable, article 284 de la directive 2006/112/CE"
    ),
}


def canonical_franchise_invoice_mention(basis: FranchiseLegalBasis) -> str:
    """Return current canonical wording for later issuance snapshotting."""
    if not isinstance(basis, FranchiseLegalBasis):
        raise InvalidInvoiceSettings("Franchise legal basis is invalid")
    return _FRANCHISE_MENTIONS[basis]


def parse_exact_percentage(value: str | None, *, field: str) -> Decimal | None:
    """Parse percentage text exactly, rejecting float and Decimal context rounding."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInvoiceSettings(f"{field} must be exact decimal text")
    try:
        parsed = Decimal(value)
    except DecimalException as error:
        raise InvalidInvoiceSettings(f"{field} must be exact decimal text") from error
    if not parsed.is_finite():
        raise InvalidInvoiceSettings(f"{field} must be finite")
    return parsed


def _validate_percentage(
    value: Decimal | None,
    *,
    field: str,
    required: bool,
    allow_zero: bool,
    maximum: Decimal | None,
) -> None:
    if value is None:
        if required:
            raise InvalidInvoiceSettings(f"{field} is required")
        return
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidInvoiceSettings(f"{field} must be a finite Decimal")
    if value < 0 or (not allow_zero and value == 0):
        qualifier = "positive" if not allow_zero else "nonnegative"
        raise InvalidInvoiceSettings(f"{field} must be {qualifier}")
    if maximum is not None and value > maximum:
        raise InvalidInvoiceSettings(f"{field} must not exceed {maximum}")


@dataclass(frozen=True)
class FiscalSettings:
    vat_regime: VatRegime
    franchise_legal_basis: FranchiseLegalBasis | None
    default_vat_rate_percent: Decimal | None
    vat_on_debits: bool

    def __post_init__(self) -> None:
        if not isinstance(self.vat_regime, VatRegime):
            raise InvalidInvoiceSettings("VAT regime is invalid")
        if type(self.vat_on_debits) is not bool:
            raise InvalidInvoiceSettings("VAT-on-debits choice must be boolean")
        if self.vat_regime is VatRegime.FRANCHISE_EN_BASE:
            if not isinstance(self.franchise_legal_basis, FranchiseLegalBasis):
                raise InvalidInvoiceSettings("Franchise en base requires an explicit legal basis")
            if self.default_vat_rate_percent is not None:
                raise InvalidInvoiceSettings("Franchise en base must not define a VAT rate")
            if self.vat_on_debits:
                raise InvalidInvoiceSettings("Franchise en base cannot select VAT on debits")
            return

        if self.franchise_legal_basis is not None:
            raise InvalidInvoiceSettings(
                "A taxable VAT regime must not define a franchise legal basis"
            )
        _validate_percentage(
            self.default_vat_rate_percent,
            field="Default VAT rate",
            required=True,
            allow_zero=True,
            maximum=Decimal(100),
        )

    @property
    def franchise_invoice_mention(self) -> str | None:
        if self.franchise_legal_basis is None:
            return None
        return canonical_franchise_invoice_mention(self.franchise_legal_basis)


@dataclass(frozen=True)
class PaymentTerms:
    due_rule: PaymentDueRule
    net_days: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.due_rule, PaymentDueRule):
            raise InvalidInvoiceSettings("Payment due rule is invalid")
        if self.due_rule is PaymentDueRule.NET_DAYS_AFTER_ISSUE:
            if type(self.net_days) is not int or not 1 <= self.net_days <= 60:
                raise InvalidInvoiceSettings(
                    "Net payment terms require 1 to 60 calendar days after issue"
                )
        elif self.net_days is not None:
            raise InvalidInvoiceSettings(
                "Payment due days apply only to net-days-after-issue terms"
            )


@dataclass(frozen=True)
class EarlyPaymentDiscount:
    kind: EarlyPaymentDiscountKind
    rate_percent: Decimal | None = None
    days_after_issue: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EarlyPaymentDiscountKind):
            raise InvalidInvoiceSettings("Early-payment discount kind is invalid")
        if self.kind is EarlyPaymentDiscountKind.NONE:
            if self.rate_percent is not None or self.days_after_issue is not None:
                raise InvalidInvoiceSettings(
                    "No early-payment discount must not define a rate or period"
                )
            return
        _validate_percentage(
            self.rate_percent,
            field="Early-payment discount rate",
            required=True,
            allow_zero=False,
            maximum=Decimal(100),
        )
        if type(self.days_after_issue) is not int or self.days_after_issue < 1:
            raise InvalidInvoiceSettings(
                "Early-payment discount requires a positive number of calendar days after issue"
            )


@dataclass(frozen=True)
class WorkspaceInvoiceSettings:
    workspace_id: UUID
    fiscal: FiscalSettings
    payment_terms: PaymentTerms
    early_payment_discount: EarlyPaymentDiscount
    late_payment_penalty_annual_rate_percent: Decimal
    recovery_indemnity_policy: RecoveryIndemnityPolicy
    operation_category: InvoiceOperationCategory

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, UUID):
            raise InvalidInvoiceSettings("Workspace ID must be a UUID")
        if not isinstance(self.fiscal, FiscalSettings):
            raise InvalidInvoiceSettings("Fiscal settings are invalid")
        if not isinstance(self.payment_terms, PaymentTerms):
            raise InvalidInvoiceSettings("Payment terms are invalid")
        if not isinstance(self.early_payment_discount, EarlyPaymentDiscount):
            raise InvalidInvoiceSettings("Early-payment discount settings are invalid")
        _validate_percentage(
            self.late_payment_penalty_annual_rate_percent,
            field="Late-payment penalty annual rate",
            required=True,
            allow_zero=False,
            maximum=None,
        )
        if self.recovery_indemnity_policy is not RecoveryIndemnityPolicy.FRENCH_B2B_40_EUR:
            raise InvalidInvoiceSettings("Recovery indemnity policy is invalid")
        if self.operation_category is not InvoiceOperationCategory.SERVICES:
            raise InvalidInvoiceSettings("Only service invoice operations are supported")

    @property
    def recovery_indemnity_currency(self) -> str:
        return "EUR"

    @property
    def recovery_indemnity_minor_units(self) -> int:
        return 4_000
