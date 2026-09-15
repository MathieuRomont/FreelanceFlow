"""Pure deterministic VAT calculation over immutable invoice-draft lines."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceCurrency,
    InvoiceDraft,
    InvoiceLine,
    RoundedMoneyAmount,
    round_exact_money_half_up,
    sum_exact_money,
)
from freelanceflow.modules.billing.domain.invoice_settings import (
    FiscalSettings,
    FranchiseLegalBasis,
    VatRegime,
    WorkspaceInvoiceSettings,
    canonical_franchise_invoice_mention,
)
from freelanceflow.modules.billing.domain.pricing import ExactMoneyAmount


class InvoiceTaxError(ValueError):
    """Base error for deterministic invoice-tax calculation failures."""


class InvalidVatRateError(InvoiceTaxError):
    """A VAT rate is not an exact supported percentage."""


class IncompatibleInvoiceTaxContextError(InvoiceTaxError):
    """Invoice, settings, or line-rate inputs do not describe one tax context."""


class UnsupportedVatTreatmentError(InvoiceTaxError):
    """The requested VAT treatment has no confirmed calculation policy."""


class VatRoundingPolicy(StrEnum):
    """Explicit VAT rounding policies supported by the France-first MVP."""

    PER_RATE_SUBTOTAL_HALF_UP = "per_rate_subtotal_half_up"


@dataclass(frozen=True)
class VatRate:
    """An exact VAT percentage; semantic exemption regimes use no zero-rate stand-in."""

    percent: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.percent, Decimal) or not self.percent.is_finite():
            raise InvalidVatRateError("VAT rate must be a finite Decimal")
        if self.percent < 0 or self.percent > 100:
            raise InvalidVatRateError("VAT rate must be between 0 and 100 percent")


@dataclass(frozen=True)
class InvoiceLineVatRate:
    """The explicit VAT rate applicable to one immutable invoice line."""

    invoice_line_id: UUID
    vat_rate: VatRate

    def __post_init__(self) -> None:
        if not isinstance(self.invoice_line_id, UUID):
            raise IncompatibleInvoiceTaxContextError("Invoice line ID must be a UUID")
        if not isinstance(self.vat_rate, VatRate):
            raise InvalidVatRateError("Invoice line VAT rate must be a VatRate")


@dataclass(frozen=True)
class InvoiceVatBreakdown:
    """One auditable VAT-category subtotal and its single rounded tax amount."""

    vat_regime: VatRegime
    invoice_line_ids: tuple[UUID, ...]
    exact_source_ht: ExactMoneyAmount
    ht_base: RoundedMoneyAmount
    vat_rate: VatRate | None
    franchise_legal_basis: FranchiseLegalBasis | None
    franchise_invoice_mention: str | None
    exact_vat_amount: ExactMoneyAmount
    vat_amount: RoundedMoneyAmount
    rounding_policy: VatRoundingPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.vat_regime, VatRegime):
            raise UnsupportedVatTreatmentError("VAT regime is unsupported")
        if type(self.invoice_line_ids) is not tuple or not self.invoice_line_ids:
            raise IncompatibleInvoiceTaxContextError("A VAT breakdown requires invoice lines")
        if any(not isinstance(line_id, UUID) for line_id in self.invoice_line_ids):
            raise IncompatibleInvoiceTaxContextError("VAT breakdown line IDs are invalid")
        if len(set(self.invoice_line_ids)) != len(self.invoice_line_ids):
            raise IncompatibleInvoiceTaxContextError(
                "A VAT breakdown cannot contain a line more than once"
            )
        if not isinstance(self.exact_source_ht, ExactMoneyAmount):
            raise IncompatibleInvoiceTaxContextError("Exact source HT is invalid")
        if not isinstance(self.ht_base, RoundedMoneyAmount):
            raise IncompatibleInvoiceTaxContextError("Rounded HT base is invalid")
        if not isinstance(self.exact_vat_amount, ExactMoneyAmount):
            raise IncompatibleInvoiceTaxContextError("Exact VAT amount is invalid")
        if not isinstance(self.vat_amount, RoundedMoneyAmount):
            raise IncompatibleInvoiceTaxContextError("Rounded VAT amount is invalid")
        if self.vat_amount.currency != self.ht_base.currency:
            raise IncompatibleInvoiceTaxContextError("VAT base and amount must use one currency")
        if self.rounding_policy is not VatRoundingPolicy.PER_RATE_SUBTOTAL_HALF_UP:
            raise UnsupportedVatTreatmentError("VAT rounding policy is unsupported")

        if self.vat_regime is VatRegime.FRANCHISE_EN_BASE:
            if self.vat_rate is not None:
                raise IncompatibleInvoiceTaxContextError(
                    "Franchise en base is not an ordinary zero VAT rate"
                )
            if not isinstance(self.franchise_legal_basis, FranchiseLegalBasis):
                raise IncompatibleInvoiceTaxContextError(
                    "Franchise en base requires its legal treatment"
                )
            if self.franchise_invoice_mention != canonical_franchise_invoice_mention(
                self.franchise_legal_basis
            ):
                raise IncompatibleInvoiceTaxContextError(
                    "Franchise en base requires its canonical invoice mention"
                )
            if self.exact_vat_amount != ExactMoneyAmount(0, 1):
                raise IncompatibleInvoiceTaxContextError(
                    "Franchise en base VAT must be exactly zero"
                )
            if self.vat_amount.minor_units != 0:
                raise IncompatibleInvoiceTaxContextError(
                    "Franchise en base rounded VAT must be zero"
                )
            return

        if self.vat_regime is not VatRegime.TAXABLE:
            raise UnsupportedVatTreatmentError("VAT regime is unsupported")
        if not isinstance(self.vat_rate, VatRate):
            raise IncompatibleInvoiceTaxContextError(
                "A taxable VAT breakdown requires an exact rate"
            )
        if self.franchise_legal_basis is not None or self.franchise_invoice_mention is not None:
            raise IncompatibleInvoiceTaxContextError(
                "A taxable VAT breakdown cannot carry franchise treatment"
            )
        expected_exact = _exact_vat_from_rounded_base(self.ht_base, self.vat_rate)
        expected_rounded = round_exact_money_half_up(expected_exact, self.ht_base.currency)
        if self.exact_vat_amount != expected_exact or self.vat_amount != expected_rounded:
            raise IncompatibleInvoiceTaxContextError(
                "Taxable VAT breakdown derived amounts are inconsistent"
            )


@dataclass(frozen=True)
class InvoiceTaxCalculation:
    """An immutable, reconcilable VAT result for one exact InvoiceDraft revision."""

    invoice_id: UUID
    invoice_revision: int
    workspace_id: UUID
    client_id: UUID
    fiscal_settings: FiscalSettings
    currency: InvoiceCurrency
    invoice_line_ids: tuple[UUID, ...]
    exact_source_ht_total: ExactMoneyAmount
    ht_total: RoundedMoneyAmount
    vat_breakdowns: tuple[InvoiceVatBreakdown, ...]
    vat_total: RoundedMoneyAmount
    ttc_total: RoundedMoneyAmount
    rounding_policy: VatRoundingPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.invoice_id, UUID):
            raise IncompatibleInvoiceTaxContextError("Invoice ID must be a UUID")
        if type(self.invoice_revision) is not int or self.invoice_revision < 1:
            raise IncompatibleInvoiceTaxContextError("Invoice revision must be a positive integer")
        if not isinstance(self.workspace_id, UUID) or not isinstance(self.client_id, UUID):
            raise IncompatibleInvoiceTaxContextError("Invoice ownership IDs are invalid")
        if not isinstance(self.fiscal_settings, FiscalSettings):
            raise UnsupportedVatTreatmentError("Fiscal settings are unsupported")
        if not isinstance(self.currency, InvoiceCurrency):
            raise IncompatibleInvoiceTaxContextError("Invoice currency is invalid")
        if type(self.invoice_line_ids) is not tuple or not self.invoice_line_ids:
            raise IncompatibleInvoiceTaxContextError("Invoice line identity is invalid")
        if len(set(self.invoice_line_ids)) != len(self.invoice_line_ids):
            raise IncompatibleInvoiceTaxContextError("Invoice line IDs must be unique")
        if not isinstance(self.exact_source_ht_total, ExactMoneyAmount):
            raise IncompatibleInvoiceTaxContextError("Exact source HT total is invalid")
        if not isinstance(self.ht_total, RoundedMoneyAmount):
            raise IncompatibleInvoiceTaxContextError("Rounded HT total is invalid")
        if type(self.vat_breakdowns) is not tuple or not self.vat_breakdowns:
            raise IncompatibleInvoiceTaxContextError("VAT breakdowns are invalid")
        if any(not isinstance(breakdown, InvoiceVatBreakdown) for breakdown in self.vat_breakdowns):
            raise IncompatibleInvoiceTaxContextError("VAT breakdowns are invalid")
        if not isinstance(self.vat_total, RoundedMoneyAmount) or not isinstance(
            self.ttc_total, RoundedMoneyAmount
        ):
            raise IncompatibleInvoiceTaxContextError("Rounded tax totals are invalid")
        if self.rounding_policy is not VatRoundingPolicy.PER_RATE_SUBTOTAL_HALF_UP:
            raise UnsupportedVatTreatmentError("VAT rounding policy is unsupported")

        breakdown_line_ids = tuple(
            line_id for breakdown in self.vat_breakdowns for line_id in breakdown.invoice_line_ids
        )
        if len(set(breakdown_line_ids)) != len(breakdown_line_ids) or set(
            breakdown_line_ids
        ) != set(self.invoice_line_ids):
            raise IncompatibleInvoiceTaxContextError(
                "Every invoice line must occur in exactly one VAT breakdown"
            )
        if any(
            breakdown.vat_regime is not self.fiscal_settings.vat_regime
            for breakdown in self.vat_breakdowns
        ):
            raise IncompatibleInvoiceTaxContextError(
                "VAT breakdown regime must match fiscal settings"
            )
        if self.fiscal_settings.vat_regime is VatRegime.FRANCHISE_EN_BASE:
            breakdown = self.vat_breakdowns[0]
            if (
                len(self.vat_breakdowns) != 1
                or breakdown.franchise_legal_basis is not self.fiscal_settings.franchise_legal_basis
                or breakdown.franchise_invoice_mention
                != self.fiscal_settings.franchise_invoice_mention
            ):
                raise IncompatibleInvoiceTaxContextError(
                    "Franchise breakdown must preserve the configured legal treatment"
                )
        money_values = (
            self.ht_total,
            self.vat_total,
            self.ttc_total,
            *(breakdown.ht_base for breakdown in self.vat_breakdowns),
            *(breakdown.vat_amount for breakdown in self.vat_breakdowns),
        )
        if any(value.currency != self.currency for value in money_values):
            raise IncompatibleInvoiceTaxContextError(
                "VAT calculation requires exactly one currency"
            )
        expected_exact_ht = sum_exact_money(
            tuple(breakdown.exact_source_ht for breakdown in self.vat_breakdowns)
        )
        expected_ht = sum(breakdown.ht_base.minor_units for breakdown in self.vat_breakdowns)
        expected_vat = sum(breakdown.vat_amount.minor_units for breakdown in self.vat_breakdowns)
        if (
            self.exact_source_ht_total != expected_exact_ht
            or self.ht_total.minor_units != expected_ht
            or self.vat_total.minor_units != expected_vat
            or self.ttc_total.minor_units != expected_ht + expected_vat
        ):
            raise IncompatibleInvoiceTaxContextError("HT, VAT, and TTC totals do not reconcile")

    @property
    def vat_regime(self) -> VatRegime:
        return self.fiscal_settings.vat_regime


def _exact_vat_from_rounded_base(
    ht_base: RoundedMoneyAmount, vat_rate: VatRate
) -> ExactMoneyAmount:
    rate_numerator, rate_denominator = vat_rate.percent.as_integer_ratio()
    return ExactMoneyAmount(
        numerator=ht_base.minor_units * rate_numerator,
        denominator=(10**ht_base.currency.decimal_places * rate_denominator * 100),
    )


def _build_breakdown(
    *,
    fiscal: FiscalSettings,
    lines: tuple[InvoiceLine, ...],
    vat_rate: VatRate | None,
) -> InvoiceVatBreakdown:
    currency = lines[0].currency
    exact_source_ht = sum_exact_money(tuple(line.exact_amount for line in lines))
    ht_base = RoundedMoneyAmount(
        currency=currency,
        minor_units=sum(line.rounded_amount.minor_units for line in lines),
    )
    if fiscal.vat_regime is VatRegime.FRANCHISE_EN_BASE:
        exact_vat = ExactMoneyAmount(0, 1)
        vat_amount = RoundedMoneyAmount(currency=currency, minor_units=0)
    elif fiscal.vat_regime is VatRegime.TAXABLE and vat_rate is not None:
        exact_vat = _exact_vat_from_rounded_base(ht_base, vat_rate)
        vat_amount = round_exact_money_half_up(exact_vat, currency)
    else:
        raise UnsupportedVatTreatmentError("VAT treatment is unsupported")
    return InvoiceVatBreakdown(
        vat_regime=fiscal.vat_regime,
        invoice_line_ids=tuple(line.id for line in lines),
        exact_source_ht=exact_source_ht,
        ht_base=ht_base,
        vat_rate=vat_rate,
        franchise_legal_basis=fiscal.franchise_legal_basis,
        franchise_invoice_mention=fiscal.franchise_invoice_mention,
        exact_vat_amount=exact_vat,
        vat_amount=vat_amount,
        rounding_policy=VatRoundingPolicy.PER_RATE_SUBTOTAL_HALF_UP,
    )


def _validate_invoice_context(invoice: InvoiceDraft, settings: WorkspaceInvoiceSettings) -> None:
    if invoice.workspace_id != settings.workspace_id:
        raise IncompatibleInvoiceTaxContextError(
            "Invoice and fiscal settings must belong to the same workspace"
        )
    if any(line.currency != invoice.currency for line in invoice.lines):
        raise IncompatibleInvoiceTaxContextError(
            "VAT calculation requires exactly one invoice currency"
        )
    if any(
        line.workspace_id != invoice.workspace_id or line.client_id != invoice.client_id
        for line in invoice.lines
    ):
        raise IncompatibleInvoiceTaxContextError("Invoice line ownership must match the invoice")


def _taxable_groups(
    invoice: InvoiceDraft,
    fiscal: FiscalSettings,
    assignments: tuple[InvoiceLineVatRate, ...] | None,
) -> tuple[tuple[VatRate, tuple[InvoiceLine, ...]], ...]:
    if assignments is None:
        default_rate = fiscal.default_vat_rate_percent
        if default_rate is None:
            raise UnsupportedVatTreatmentError("Taxable fiscal settings require a default VAT rate")
        rate = VatRate(default_rate)
        return ((rate, invoice.lines),)
    if type(assignments) is not tuple or any(
        not isinstance(assignment, InvoiceLineVatRate) for assignment in assignments
    ):
        raise IncompatibleInvoiceTaxContextError(
            "Explicit VAT assignments must be InvoiceLineVatRates"
        )
    assignment_ids = tuple(assignment.invoice_line_id for assignment in assignments)
    invoice_ids = tuple(line.id for line in invoice.lines)
    if len(set(assignment_ids)) != len(assignment_ids):
        raise IncompatibleInvoiceTaxContextError(
            "An invoice line cannot have more than one VAT assignment"
        )
    if set(assignment_ids) != set(invoice_ids):
        raise IncompatibleInvoiceTaxContextError(
            "Explicit VAT assignments must cover every invoice line exactly once"
        )
    rates_by_line = {assignment.invoice_line_id: assignment.vat_rate for assignment in assignments}
    grouped: dict[VatRate, list[InvoiceLine]] = {}
    for line in invoice.lines:
        rate = rates_by_line[line.id]
        grouped.setdefault(rate, []).append(line)
    return tuple(
        (rate, tuple(grouped[rate])) for rate in sorted(grouped, key=lambda value: value.percent)
    )


def calculate_invoice_vat(
    invoice: InvoiceDraft,
    settings: WorkspaceInvoiceSettings,
    *,
    line_vat_rates: tuple[InvoiceLineVatRate, ...] | None = None,
) -> InvoiceTaxCalculation:
    """Calculate auditable France-first VAT without persistence or ambient rounding."""
    if not isinstance(invoice, InvoiceDraft):
        raise IncompatibleInvoiceTaxContextError("VAT calculation requires an InvoiceDraft")
    if not isinstance(settings, WorkspaceInvoiceSettings):
        raise UnsupportedVatTreatmentError("VAT calculation requires WorkspaceInvoiceSettings")
    _validate_invoice_context(invoice, settings)
    fiscal = settings.fiscal
    breakdowns: tuple[InvoiceVatBreakdown, ...]
    if fiscal.vat_regime is VatRegime.FRANCHISE_EN_BASE:
        if line_vat_rates is not None:
            raise IncompatibleInvoiceTaxContextError(
                "Franchise en base does not accept ordinary VAT-rate assignments"
            )
        breakdowns = (_build_breakdown(fiscal=fiscal, lines=invoice.lines, vat_rate=None),)
    elif fiscal.vat_regime is VatRegime.TAXABLE:
        groups = _taxable_groups(invoice, fiscal, line_vat_rates)
        breakdowns = tuple(
            _build_breakdown(fiscal=fiscal, lines=lines, vat_rate=rate) for rate, lines in groups
        )
    else:
        raise UnsupportedVatTreatmentError("VAT regime is unsupported")

    vat_total_minor_units = sum(breakdown.vat_amount.minor_units for breakdown in breakdowns)
    return InvoiceTaxCalculation(
        invoice_id=invoice.id,
        invoice_revision=invoice.revision,
        workspace_id=invoice.workspace_id,
        client_id=invoice.client_id,
        fiscal_settings=fiscal,
        currency=invoice.currency,
        invoice_line_ids=tuple(line.id for line in invoice.lines),
        exact_source_ht_total=invoice.exact_subtotal,
        ht_total=invoice.subtotal,
        vat_breakdowns=breakdowns,
        vat_total=RoundedMoneyAmount(
            currency=invoice.currency,
            minor_units=vat_total_minor_units,
        ),
        ttc_total=RoundedMoneyAmount(
            currency=invoice.currency,
            minor_units=invoice.subtotal.minor_units + vat_total_minor_units,
        ),
        rounding_policy=VatRoundingPolicy.PER_RATE_SUBTOTAL_HALF_UP,
    )
