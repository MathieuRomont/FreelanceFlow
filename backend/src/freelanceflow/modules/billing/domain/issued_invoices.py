"""Immutable legal invoice issuance from trusted deterministic billing snapshots."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from freelanceflow.modules.billing.domain.billing_profiles import (
    BillingAddress,
    ClientBillingProfile,
    LegalEntityKind,
    WorkspaceBillingProfile,
)
from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceDraft,
    InvoiceLine,
    RoundedMoneyAmount,
    sum_exact_money,
)
from freelanceflow.modules.billing.domain.invoice_settings import (
    EarlyPaymentDiscount,
    EarlyPaymentDiscountKind,
    InvoiceOperationCategory,
    PaymentTerms,
    RecoveryIndemnityPolicy,
    VatRegime,
    WorkspaceInvoiceSettings,
)
from freelanceflow.modules.billing.domain.pricing import ExactMoneyAmount
from freelanceflow.modules.billing.domain.vat import (
    InvoiceTaxCalculation,
    VatRate,
    VatRoundingPolicy,
)


class InvoiceIssuanceError(ValueError):
    """Base error for invalid immutable invoice issuance."""


class InvalidInvoiceIssuanceError(InvoiceIssuanceError):
    """Issuance inputs or reconstructed snapshot data are inconsistent."""


class IncompleteLegalInvoiceError(InvoiceIssuanceError):
    """Required legal data for the scoped invoice is unavailable."""


class UnsupportedLegalPolicyDateError(InvoiceIssuanceError):
    """Effective legal policy data is unavailable for the issue date."""


class InvoiceLineRoundingPolicy(StrEnum):
    """Explicit invoice-line monetary policy captured at issuance."""

    PER_LINE_HALF_UP = "per_line_half_up"


@dataclass(frozen=True)
class LegalInvoiceNumber:
    """Internal series/sequence facts and the immutable rendered legal number."""

    series: str
    sequence: int
    value: str

    def __post_init__(self) -> None:
        if self.series != "main":
            raise InvalidInvoiceIssuanceError("Only the main invoice-number series is supported")
        if type(self.sequence) is not int or self.sequence < 1:
            raise InvalidInvoiceIssuanceError("Invoice-number sequence must be positive")
        if self.value != str(self.sequence):
            raise InvalidInvoiceIssuanceError(
                "Main-series invoice number must be the canonical decimal sequence"
            )


@dataclass(frozen=True)
class InvoiceLineDescription:
    invoice_line_id: UUID
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.invoice_line_id, UUID):
            raise InvalidInvoiceIssuanceError("Invoice line description ID must be a UUID")
        if not isinstance(self.description, str) or not self.description.strip():
            raise IncompleteLegalInvoiceError("Every issued line requires a precise description")


@dataclass(frozen=True)
class IssuedSellerSnapshot:
    legal_entity_kind: LegalEntityKind
    legal_name: str
    trading_name: str | None
    siren: str
    siret: str
    vat_number: str | None
    legal_address: BillingAddress
    billing_address: BillingAddress | None
    legal_form: str | None
    share_capital: Decimal | None
    share_capital_currency: str | None


@dataclass(frozen=True)
class IssuedClientSnapshot:
    source_client_id: UUID
    legal_name: str
    trading_name: str | None
    siren: str
    vat_number: str | None
    legal_address: BillingAddress
    billing_address: BillingAddress | None


@dataclass(frozen=True)
class IssuedFiscalPaymentSnapshot:
    vat_regime: VatRegime
    franchise_legal_basis: str | None
    franchise_invoice_mention: str | None
    default_vat_rate_percent: Decimal | None
    vat_on_debits: bool
    operation_category: InvoiceOperationCategory
    payment_terms: PaymentTerms
    early_payment_discount: EarlyPaymentDiscount
    early_payment_discount_mention: str
    late_payment_penalty_annual_rate_percent: Decimal
    late_payment_minimum_annual_rate_percent: Decimal
    late_payment_legal_policy: str
    recovery_indemnity_policy: RecoveryIndemnityPolicy
    recovery_indemnity_currency: str
    recovery_indemnity_minor_units: int


@dataclass(frozen=True)
class IssuedInvoiceAllocation:
    position: int
    source_time_entry_id: UUID
    source_start: datetime
    source_end: datetime
    source_billable: bool
    segment_start: datetime
    segment_end: datetime
    business_date: date
    duration_microseconds: int
    exact_amount: ExactMoneyAmount


@dataclass(frozen=True)
class IssuedInvoiceLine:
    position: int
    source_invoice_line_id: UUID
    description: str
    project_id: UUID
    project_name: str
    task_id: UUID | None
    task_name: str | None
    rate_agreement_id: UUID
    rate_scope_project_id: UUID | None
    rate_valid_from: date
    rate_valid_until: date | None
    hourly_rate: Decimal
    duration_microseconds: int
    exact_amount: ExactMoneyAmount
    rounded_ht: RoundedMoneyAmount
    allocations: tuple[IssuedInvoiceAllocation, ...]


@dataclass(frozen=True)
class IssuedVatBreakdown:
    position: int
    invoice_line_positions: tuple[int, ...]
    exact_source_ht: ExactMoneyAmount
    ht_base: RoundedMoneyAmount
    vat_rate: VatRate | None
    franchise_legal_basis: str | None
    franchise_invoice_mention: str | None
    exact_vat_amount: ExactMoneyAmount
    vat_amount: RoundedMoneyAmount
    rounding_policy: VatRoundingPolicy


@dataclass(frozen=True)
class IssuedInvoice:
    """Complete immutable legal and financial history for one draft revision."""

    id: UUID
    workspace_id: UUID
    source_invoice_id: UUID
    source_revision: int
    number: LegalInvoiceNumber
    issued_at: datetime
    billing_timezone: str
    issue_date: date
    service_completion_date: date
    due_date: date
    purchase_order_number: str | None
    currency: str
    currency_decimal_places: int
    line_rounding_policy: InvoiceLineRoundingPolicy
    seller: IssuedSellerSnapshot
    client: IssuedClientSnapshot
    fiscal_payment: IssuedFiscalPaymentSnapshot
    lines: tuple[IssuedInvoiceLine, ...]
    vat_breakdowns: tuple[IssuedVatBreakdown, ...]
    exact_source_ht_total: ExactMoneyAmount
    ht_total: RoundedMoneyAmount
    vat_total: RoundedMoneyAmount
    ttc_total: RoundedMoneyAmount

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (self.id, self.workspace_id, self.source_invoice_id)
        ):
            raise InvalidInvoiceIssuanceError("Issued invoice identity values must be UUIDs")
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise InvalidInvoiceIssuanceError("Source revision must be positive")
        if self.issued_at.utcoffset() != timedelta(0):
            raise InvalidInvoiceIssuanceError("Issued timestamp must be UTC")
        if self.service_completion_date > self.issue_date:
            raise IncompleteLegalInvoiceError(
                "Service completion date cannot be after invoice issue date"
            )
        if self.purchase_order_number is not None and not self.purchase_order_number.strip():
            raise InvalidInvoiceIssuanceError("Purchase-order number must be nonblank")
        if not self.lines or tuple(line.position for line in self.lines) != tuple(
            range(len(self.lines))
        ):
            raise InvalidInvoiceIssuanceError("Issued invoice line order is inconsistent")
        for line in self.lines:
            if not line.description.strip() or not line.allocations:
                raise InvalidInvoiceIssuanceError(
                    "Issued invoice lines require descriptions and allocations"
                )
            if tuple(item.position for item in line.allocations) != tuple(
                range(len(line.allocations))
            ):
                raise InvalidInvoiceIssuanceError(
                    "Issued invoice allocation order is inconsistent"
                )
            if any(not item.source_billable for item in line.allocations):
                raise InvalidInvoiceIssuanceError(
                    "Issued invoice allocations must retain billable sources"
                )
            if line.duration_microseconds != sum(
                item.duration_microseconds for item in line.allocations
            ) or line.exact_amount != sum_exact_money(
                tuple(item.exact_amount for item in line.allocations)
            ):
                raise InvalidInvoiceIssuanceError(
                    "Issued invoice line allocation amounts do not reconcile"
                )
        if not self.vat_breakdowns or tuple(
            item.position for item in self.vat_breakdowns
        ) != tuple(range(len(self.vat_breakdowns))):
            raise InvalidInvoiceIssuanceError("VAT breakdown order is inconsistent")
        currency_values = (
            self.ht_total,
            self.vat_total,
            self.ttc_total,
            *(line.rounded_ht for line in self.lines),
            *(item.ht_base for item in self.vat_breakdowns),
            *(item.vat_amount for item in self.vat_breakdowns),
        )
        if any(
            value.currency.code != self.currency
            or value.currency.decimal_places != self.currency_decimal_places
            for value in currency_values
        ):
            raise InvalidInvoiceIssuanceError("Issued invoice currency is inconsistent")
        if self.ht_total.minor_units != sum(
            line.rounded_ht.minor_units for line in self.lines
        ):
            raise InvalidInvoiceIssuanceError("Issued line HT amounts do not reconcile")
        if self.vat_total.minor_units != sum(
            item.vat_amount.minor_units for item in self.vat_breakdowns
        ):
            raise InvalidInvoiceIssuanceError("Issued VAT amounts do not reconcile")
        if self.ttc_total.minor_units != (
            self.ht_total.minor_units + self.vat_total.minor_units
        ):
            raise InvalidInvoiceIssuanceError("Issued HT, VAT, and TTC do not reconcile")
        if self.exact_source_ht_total != sum_exact_money(
            tuple(line.exact_amount for line in self.lines)
        ):
            raise InvalidInvoiceIssuanceError(
                "Issued exact source HT does not reconcile with lines"
            )
        positions = tuple(
            position
            for breakdown in self.vat_breakdowns
            for position in breakdown.invoice_line_positions
        )
        if len(set(positions)) != len(self.lines) or set(positions) != set(range(len(self.lines))):
            raise InvalidInvoiceIssuanceError(
                "Every issued invoice line must belong to exactly one VAT breakdown"
            )
        for breakdown in self.vat_breakdowns:
            if breakdown.exact_source_ht != sum_exact_money(
                tuple(
                    self.lines[position].exact_amount
                    for position in breakdown.invoice_line_positions
                )
            ):
                raise InvalidInvoiceIssuanceError(
                    "Issued VAT source HT does not reconcile with its lines"
                )


def minimum_french_b2b_late_penalty_rate(issue_date: date) -> tuple[Decimal, str]:
    """Return the exact statutory floor from effective official 2026 legal rates."""
    if date(2026, 1, 1) <= issue_date <= date(2026, 6, 30):
        return Decimal("7.86"), "fr_l441_10_three_times_legal_interest_2026_h1"
    if date(2026, 7, 1) <= issue_date <= date(2026, 12, 31):
        return Decimal("8.25"), "fr_l441_10_three_times_legal_interest_2026_h2"
    raise UnsupportedLegalPolicyDateError(
        "French B2B late-penalty minimum is not configured for this issue date"
    )


def _seller_snapshot(profile: WorkspaceBillingProfile) -> IssuedSellerSnapshot:
    return IssuedSellerSnapshot(
        legal_entity_kind=profile.legal_entity_kind,
        legal_name=profile.legal_name,
        trading_name=profile.trading_name,
        siren=profile.siren,
        siret=profile.siret,
        vat_number=profile.vat_number,
        legal_address=profile.legal_address,
        billing_address=profile.billing_address,
        legal_form=profile.legal_form,
        share_capital=profile.share_capital,
        share_capital_currency=profile.share_capital_currency,
    )


def _client_snapshot(profile: ClientBillingProfile) -> IssuedClientSnapshot:
    if profile.legal_address.country_code != "FR" or profile.siren is None:
        raise IncompleteLegalInvoiceError(
            "Only French B2B clients with a SIREN are supported for issuance"
        )
    return IssuedClientSnapshot(
        source_client_id=profile.client_id,
        legal_name=profile.legal_name,
        trading_name=profile.trading_name,
        siren=profile.siren,
        vat_number=profile.vat_number,
        legal_address=profile.legal_address,
        billing_address=profile.billing_address,
    )


def _fiscal_payment_snapshot(
    settings: WorkspaceInvoiceSettings, issue_date: date
) -> IssuedFiscalPaymentSnapshot:
    minimum_rate, legal_policy = minimum_french_b2b_late_penalty_rate(issue_date)
    configured_rate = settings.late_payment_penalty_annual_rate_percent
    if configured_rate < minimum_rate:
        raise IncompleteLegalInvoiceError(
            f"Late-payment penalty rate must be at least {minimum_rate}% on {issue_date}"
        )
    fiscal = settings.fiscal
    if fiscal.vat_regime is VatRegime.TAXABLE:
        rate = fiscal.default_vat_rate_percent
        if rate is None or rate <= 0:
            raise IncompleteLegalInvoiceError(
                "Taxable domestic service issuance requires a positive VAT rate"
            )
    return IssuedFiscalPaymentSnapshot(
        vat_regime=fiscal.vat_regime,
        franchise_legal_basis=(
            fiscal.franchise_legal_basis.value if fiscal.franchise_legal_basis else None
        ),
        franchise_invoice_mention=fiscal.franchise_invoice_mention,
        default_vat_rate_percent=fiscal.default_vat_rate_percent,
        vat_on_debits=fiscal.vat_on_debits,
        operation_category=settings.operation_category,
        payment_terms=settings.payment_terms,
        early_payment_discount=settings.early_payment_discount,
        early_payment_discount_mention=_early_payment_discount_mention(
            settings.early_payment_discount
        ),
        late_payment_penalty_annual_rate_percent=configured_rate,
        late_payment_minimum_annual_rate_percent=minimum_rate,
        late_payment_legal_policy=legal_policy,
        recovery_indemnity_policy=settings.recovery_indemnity_policy,
        recovery_indemnity_currency=settings.recovery_indemnity_currency,
        recovery_indemnity_minor_units=settings.recovery_indemnity_minor_units,
    )


def _early_payment_discount_mention(value: EarlyPaymentDiscount) -> str:
    if value.kind is EarlyPaymentDiscountKind.NONE:
        return "Escompte pour paiement anticipé : néant"
    assert value.rate_percent is not None and value.days_after_issue is not None
    return (
        f"Escompte de {value.rate_percent}% pour paiement dans les "
        f"{value.days_after_issue} jours suivant la date d'émission"
    )


def _issued_line(
    line: InvoiceLine, position: int, description: str
) -> IssuedInvoiceLine:
    first = line.allocations[0].priced_segment
    source = first.segment.source_time_entry
    project = source.project
    assert project is not None
    task = source.task
    rate = first.applied_rate.agreement
    allocations = tuple(
        IssuedInvoiceAllocation(
            position=allocation_position,
            source_time_entry_id=allocation.source_time_entry_id,
            source_start=allocation.priced_segment.segment.source_time_entry.start.astimezone(
                UTC
            ),
            source_end=allocation.priced_segment.segment.source_time_entry.end.astimezone(
                UTC
            ),
            source_billable=allocation.priced_segment.segment.source_time_entry.billable,
            segment_start=allocation.start.astimezone(UTC),
            segment_end=allocation.end.astimezone(UTC),
            business_date=allocation.priced_segment.segment.business_date,
            duration_microseconds=allocation.duration_microseconds,
            exact_amount=allocation.exact_amount,
        )
        for allocation_position, allocation in enumerate(line.allocations)
    )
    return IssuedInvoiceLine(
        position=position,
        source_invoice_line_id=line.id,
        description=description,
        project_id=line.project_id,
        project_name=project.name,
        task_id=line.task_id,
        task_name=task.name if task else None,
        rate_agreement_id=line.applied_rate_agreement_id,
        rate_scope_project_id=rate.project.id if rate.project else None,
        rate_valid_from=rate.valid_from,
        rate_valid_until=rate.valid_until,
        hourly_rate=line.hourly_rate,
        duration_microseconds=line.duration_microseconds,
        exact_amount=line.exact_amount,
        rounded_ht=line.rounded_amount,
        allocations=allocations,
    )


def issue_invoice(
    *,
    issued_invoice_id: UUID,
    number: LegalInvoiceNumber,
    draft: InvoiceDraft,
    seller_profile: WorkspaceBillingProfile,
    client_profile: ClientBillingProfile,
    settings: WorkspaceInvoiceSettings,
    tax: InvoiceTaxCalculation,
    issued_at: datetime,
    issue_date: date,
    service_completion_date: date,
    due_date: date,
    line_descriptions: tuple[InvoiceLineDescription, ...],
    purchase_order_number: str | None,
) -> IssuedInvoice:
    """Freeze one current draft plus trusted configuration into legal history."""
    if not isinstance(issued_invoice_id, UUID):
        raise InvalidInvoiceIssuanceError("Issued invoice ID must be a UUID")
    if issued_at.tzinfo is None or issued_at.utcoffset() != timedelta(0):
        raise InvalidInvoiceIssuanceError("Issued timestamp must be UTC")
    if (
        seller_profile.workspace_id != draft.workspace_id
        or client_profile.workspace_id != draft.workspace_id
        or client_profile.client_id != draft.client_id
        or settings.workspace_id != draft.workspace_id
        or tax.invoice_id != draft.id
        or tax.invoice_revision != draft.revision
        or tax.workspace_id != draft.workspace_id
        or tax.client_id != draft.client_id
    ):
        raise InvalidInvoiceIssuanceError("Issuance ownership or source context is inconsistent")
    if settings.billing_timezone is None:
        raise IncompleteLegalInvoiceError("Workspace billing timezone is required for issuance")
    if tax.fiscal_settings != settings.fiscal:
        raise InvalidInvoiceIssuanceError("Tax result must use the snapshotted fiscal settings")
    if settings.fiscal.vat_regime is VatRegime.TAXABLE and seller_profile.vat_number is None:
        raise IncompleteLegalInvoiceError("A taxable seller requires a VAT identification number")
    if type(line_descriptions) is not tuple or any(
        not isinstance(value, InvoiceLineDescription) for value in line_descriptions
    ):
        raise InvalidInvoiceIssuanceError("Line descriptions are invalid")
    description_ids = tuple(value.invoice_line_id for value in line_descriptions)
    expected_ids = tuple(line.id for line in draft.lines)
    if len(set(description_ids)) != len(description_ids) or set(description_ids) != set(
        expected_ids
    ):
        raise IncompleteLegalInvoiceError(
            "Issuance requires exactly one description for every draft line"
        )
    descriptions = {value.invoice_line_id: value.description for value in line_descriptions}
    lines = tuple(
        _issued_line(line, position, descriptions[line.id])
        for position, line in enumerate(draft.lines)
    )
    line_positions = {line.source_invoice_line_id: line.position for line in lines}
    breakdowns = tuple(
        IssuedVatBreakdown(
            position=position,
            invoice_line_positions=tuple(
                line_positions[line_id] for line_id in breakdown.invoice_line_ids
            ),
            exact_source_ht=breakdown.exact_source_ht,
            ht_base=breakdown.ht_base,
            vat_rate=breakdown.vat_rate,
            franchise_legal_basis=(
                breakdown.franchise_legal_basis.value
                if breakdown.franchise_legal_basis
                else None
            ),
            franchise_invoice_mention=breakdown.franchise_invoice_mention,
            exact_vat_amount=breakdown.exact_vat_amount,
            vat_amount=breakdown.vat_amount,
            rounding_policy=breakdown.rounding_policy,
        )
        for position, breakdown in enumerate(tax.vat_breakdowns)
    )
    return IssuedInvoice(
        id=issued_invoice_id,
        workspace_id=draft.workspace_id,
        source_invoice_id=draft.id,
        source_revision=draft.revision,
        number=number,
        issued_at=issued_at,
        billing_timezone=settings.billing_timezone.name,
        issue_date=issue_date,
        service_completion_date=service_completion_date,
        due_date=due_date,
        purchase_order_number=purchase_order_number,
        currency=draft.currency.code,
        currency_decimal_places=draft.currency.decimal_places,
        line_rounding_policy=InvoiceLineRoundingPolicy.PER_LINE_HALF_UP,
        seller=_seller_snapshot(seller_profile),
        client=_client_snapshot(client_profile),
        fiscal_payment=_fiscal_payment_snapshot(settings, issue_date),
        lines=lines,
        vat_breakdowns=breakdowns,
        exact_source_ht_total=tax.exact_source_ht_total,
        ht_total=tax.ht_total,
        vat_total=tax.vat_total,
        ttc_total=tax.ttc_total,
    )
