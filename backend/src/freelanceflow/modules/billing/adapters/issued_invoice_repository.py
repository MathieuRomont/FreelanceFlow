"""PostgreSQL persistence for immutable issued-invoice snapshots."""

from datetime import UTC, date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.billing_profile_repository import (
    BillingProfileRepository,
)
from freelanceflow.modules.billing.adapters.invoice_draft_repository import (
    InvoiceDraftRepository,
)
from freelanceflow.modules.billing.adapters.invoice_settings_repository import (
    InvoiceSettingsRepository,
)
from freelanceflow.modules.billing.adapters.issued_invoice_models import (
    InvoiceNumberCounterRow,
    IssuedInvoiceAllocationRow,
    IssuedInvoiceClientRow,
    IssuedInvoiceLineRow,
    IssuedInvoiceRow,
    IssuedInvoiceSellerRow,
    IssuedInvoiceVatBreakdownRow,
)
from freelanceflow.modules.billing.adapters.models import InvoiceDraftHeadRow
from freelanceflow.modules.billing.application.issued_invoices import (
    InvoiceNumberChronologyError,
    LockedInvoiceDraft,
)
from freelanceflow.modules.billing.domain.billing_profiles import (
    BillingAddress,
    ClientBillingProfile,
    LegalEntityKind,
    WorkspaceBillingProfile,
)
from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceCurrency,
    RoundedMoneyAmount,
)
from freelanceflow.modules.billing.domain.invoice_settings import (
    EarlyPaymentDiscount,
    EarlyPaymentDiscountKind,
    InvoiceOperationCategory,
    PaymentDueRule,
    PaymentTerms,
    RecoveryIndemnityPolicy,
    VatRegime,
    WorkspaceInvoiceSettings,
)
from freelanceflow.modules.billing.domain.issued_invoices import (
    InvoiceLineRoundingPolicy,
    IssuedClientSnapshot,
    IssuedFiscalPaymentSnapshot,
    IssuedInvoice,
    IssuedInvoiceAllocation,
    IssuedInvoiceLine,
    IssuedSellerSnapshot,
    IssuedVatBreakdown,
    LegalInvoiceNumber,
)
from freelanceflow.modules.billing.domain.pricing import ExactMoneyAmount
from freelanceflow.modules.billing.domain.vat import VatRate, VatRoundingPolicy


def _integer(value: Decimal) -> int:
    integer = int(value)
    if Decimal(integer) != value:
        raise ValueError("Persisted monetary integer is not integral")
    return integer


def _address_values(prefix: str, value: BillingAddress | None) -> dict[str, str | None]:
    return {
        f"{prefix}_line1": value.line1 if value else None,
        f"{prefix}_line2": value.line2 if value else None,
        f"{prefix}_postal_code": value.postal_code if value else None,
        f"{prefix}_city": value.city if value else None,
        f"{prefix}_country_code": value.country_code if value else None,
    }


def _address_from_row(row: object, prefix: str) -> BillingAddress | None:
    line1 = getattr(row, f"{prefix}_line1")
    if line1 is None:
        return None
    return BillingAddress(
        line1=line1,
        line2=getattr(row, f"{prefix}_line2"),
        postal_code=getattr(row, f"{prefix}_postal_code"),
        city=getattr(row, f"{prefix}_city"),
        country_code=getattr(row, f"{prefix}_country_code"),
    )


class IssuedInvoiceRepository:
    def __init__(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        drafts: InvoiceDraftRepository | None = None,
        profiles: BillingProfileRepository | None = None,
        settings: InvoiceSettingsRepository | None = None,
    ) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.drafts = drafts
        self.profiles = profiles
        self.settings = settings

    def lock_draft(self, invoice_id: UUID) -> LockedInvoiceDraft | None:
        if self.drafts is None:
            raise RuntimeError("InvoiceDraft repository is unavailable in read-only mode")
        head = self.session.scalar(
            select(InvoiceDraftHeadRow)
            .where(
                InvoiceDraftHeadRow.id == invoice_id,
                InvoiceDraftHeadRow.workspace_id == self.workspace_id,
            )
            .with_for_update()
        )
        if head is None:
            return None
        draft = self.drafts.get_revision(head.id, head.current_revision)
        if draft is None:
            raise RuntimeError("InvoiceDraft head references a missing current revision")
        return LockedInvoiceDraft(draft=draft, issued_invoice_id=head.issued_invoice_id)

    def get_workspace_profile_for_snapshot(self) -> WorkspaceBillingProfile | None:
        if self.profiles is None:
            raise RuntimeError("Billing profiles are unavailable in read-only mode")
        return self.profiles.get_workspace_profile_for_snapshot()

    def get_client_profile_for_snapshot(
        self, client_id: UUID
    ) -> ClientBillingProfile | None:
        if self.profiles is None:
            raise RuntimeError("Billing profiles are unavailable in read-only mode")
        return self.profiles.get_client_profile_for_snapshot(client_id)

    def get_settings_for_snapshot(self) -> WorkspaceInvoiceSettings | None:
        if self.settings is None:
            raise RuntimeError("Invoice settings are unavailable in read-only mode")
        return self.settings.get_for_snapshot()

    def allocate_number(self, issue_date: date) -> LegalInvoiceNumber:
        self.session.execute(
            insert(InvoiceNumberCounterRow)
            .values(
                workspace_id=self.workspace_id,
                series="main",
                last_sequence=0,
                last_issue_date=None,
            )
            .on_conflict_do_nothing(index_elements=["workspace_id", "series"])
        )
        row = self.session.scalar(
            select(InvoiceNumberCounterRow)
            .where(
                InvoiceNumberCounterRow.workspace_id == self.workspace_id,
                InvoiceNumberCounterRow.series == "main",
            )
            .with_for_update()
        )
        if row is None:
            raise RuntimeError("Invoice-number counter could not be locked")
        if row.last_issue_date is not None and issue_date < row.last_issue_date:
            raise InvoiceNumberChronologyError(
                "Invoice issue date cannot precede the last issued invoice date"
            )
        row.last_sequence += 1
        row.last_issue_date = issue_date
        self.session.flush()
        return LegalInvoiceNumber("main", row.last_sequence, str(row.last_sequence))

    def add(self, value: IssuedInvoice) -> None:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        fiscal = value.fiscal_payment
        self.session.add(
            IssuedInvoiceRow(
                id=value.id,
                workspace_id=value.workspace_id,
                source_invoice_id=value.source_invoice_id,
                source_revision=value.source_revision,
                number_series=value.number.series,
                number_sequence=value.number.sequence,
                invoice_number=value.number.value,
                issued_at=value.issued_at,
                billing_timezone=value.billing_timezone,
                issue_date=value.issue_date,
                service_completion_date=value.service_completion_date,
                due_date=value.due_date,
                purchase_order_number=value.purchase_order_number,
                currency=value.currency,
                currency_decimal_places=value.currency_decimal_places,
                line_rounding_policy=value.line_rounding_policy.value,
                vat_rounding_policy=value.vat_breakdowns[0].rounding_policy.value,
                exact_source_ht_numerator=Decimal(value.exact_source_ht_total.numerator),
                exact_source_ht_denominator=Decimal(value.exact_source_ht_total.denominator),
                ht_minor_units=Decimal(value.ht_total.minor_units),
                vat_minor_units=Decimal(value.vat_total.minor_units),
                ttc_minor_units=Decimal(value.ttc_total.minor_units),
                vat_regime=fiscal.vat_regime.value,
                franchise_legal_basis=fiscal.franchise_legal_basis,
                franchise_invoice_mention=fiscal.franchise_invoice_mention,
                default_vat_rate_percent=fiscal.default_vat_rate_percent,
                vat_on_debits=fiscal.vat_on_debits,
                operation_category=fiscal.operation_category.value,
                payment_due_rule=fiscal.payment_terms.due_rule.value,
                payment_net_days=fiscal.payment_terms.net_days,
                early_discount_kind=fiscal.early_payment_discount.kind.value,
                early_discount_rate_percent=fiscal.early_payment_discount.rate_percent,
                early_discount_days_after_issue=(
                    fiscal.early_payment_discount.days_after_issue
                ),
                early_discount_mention=fiscal.early_payment_discount_mention,
                late_payment_penalty_annual_rate_percent=(
                    fiscal.late_payment_penalty_annual_rate_percent
                ),
                late_payment_minimum_annual_rate_percent=(
                    fiscal.late_payment_minimum_annual_rate_percent
                ),
                late_payment_legal_policy=fiscal.late_payment_legal_policy,
                recovery_indemnity_policy=fiscal.recovery_indemnity_policy.value,
                recovery_indemnity_currency=fiscal.recovery_indemnity_currency,
                recovery_indemnity_minor_units=fiscal.recovery_indemnity_minor_units,
            )
        )
        self.session.flush()
        self._add_parties(value)
        self._add_financial_children(value)

    def _add_parties(self, value: IssuedInvoice) -> None:
        seller = value.seller
        self.session.add(
            IssuedInvoiceSellerRow(
                issued_invoice_id=value.id,
                workspace_id=value.workspace_id,
                legal_entity_kind=seller.legal_entity_kind.value,
                legal_name=seller.legal_name,
                trading_name=seller.trading_name,
                siren=seller.siren,
                siret=seller.siret,
                vat_number=seller.vat_number,
                legal_form=seller.legal_form,
                share_capital=seller.share_capital,
                share_capital_currency=seller.share_capital_currency,
                **_address_values("legal", seller.legal_address),
                **_address_values("billing", seller.billing_address),
            )
        )
        client = value.client
        self.session.add(
            IssuedInvoiceClientRow(
                issued_invoice_id=value.id,
                workspace_id=value.workspace_id,
                source_client_id=client.source_client_id,
                legal_name=client.legal_name,
                trading_name=client.trading_name,
                siren=client.siren,
                vat_number=client.vat_number,
                **_address_values("legal", client.legal_address),
                **_address_values("billing", client.billing_address),
            )
        )
        self.session.flush()

    def _add_financial_children(self, value: IssuedInvoice) -> None:
        for breakdown in value.vat_breakdowns:
            self.session.add(
                IssuedInvoiceVatBreakdownRow(
                    issued_invoice_id=value.id,
                    position=breakdown.position,
                    workspace_id=value.workspace_id,
                    exact_source_ht_numerator=Decimal(breakdown.exact_source_ht.numerator),
                    exact_source_ht_denominator=Decimal(
                        breakdown.exact_source_ht.denominator
                    ),
                    ht_base_minor_units=Decimal(breakdown.ht_base.minor_units),
                    vat_rate_percent=(
                        breakdown.vat_rate.percent if breakdown.vat_rate else None
                    ),
                    franchise_legal_basis=breakdown.franchise_legal_basis,
                    franchise_invoice_mention=breakdown.franchise_invoice_mention,
                    exact_vat_numerator=Decimal(breakdown.exact_vat_amount.numerator),
                    exact_vat_denominator=Decimal(breakdown.exact_vat_amount.denominator),
                    vat_minor_units=Decimal(breakdown.vat_amount.minor_units),
                    rounding_policy=breakdown.rounding_policy.value,
                )
            )
        self.session.flush()
        breakdown_by_line = {
            line_position: breakdown.position
            for breakdown in value.vat_breakdowns
            for line_position in breakdown.invoice_line_positions
        }
        for line in value.lines:
            self.session.add(
                IssuedInvoiceLineRow(
                    issued_invoice_id=value.id,
                    position=line.position,
                    workspace_id=value.workspace_id,
                    vat_breakdown_position=breakdown_by_line[line.position],
                    source_invoice_line_id=line.source_invoice_line_id,
                    description=line.description,
                    project_id=line.project_id,
                    project_name=line.project_name,
                    task_id=line.task_id,
                    task_name=line.task_name,
                    rate_agreement_id=line.rate_agreement_id,
                    rate_scope_project_id=line.rate_scope_project_id,
                    rate_valid_from=line.rate_valid_from,
                    rate_valid_until=line.rate_valid_until,
                    hourly_rate=line.hourly_rate,
                    duration_microseconds=line.duration_microseconds,
                    exact_amount_numerator=Decimal(line.exact_amount.numerator),
                    exact_amount_denominator=Decimal(line.exact_amount.denominator),
                    rounded_ht_minor_units=Decimal(line.rounded_ht.minor_units),
                )
            )
        self.session.flush()
        for line in value.lines:
            for allocation in line.allocations:
                self.session.add(
                    IssuedInvoiceAllocationRow(
                        issued_invoice_id=value.id,
                        line_position=line.position,
                        position=allocation.position,
                        workspace_id=value.workspace_id,
                        source_time_entry_id=allocation.source_time_entry_id,
                        source_start=allocation.source_start.astimezone(UTC),
                        source_end=allocation.source_end.astimezone(UTC),
                        source_billable=allocation.source_billable,
                        segment_start=allocation.segment_start.astimezone(UTC),
                        segment_end=allocation.segment_end.astimezone(UTC),
                        business_date=allocation.business_date,
                        duration_microseconds=allocation.duration_microseconds,
                        exact_amount_numerator=Decimal(allocation.exact_amount.numerator),
                        exact_amount_denominator=Decimal(allocation.exact_amount.denominator),
                    )
                )
        self.session.flush()

    def freeze_draft(self, value: IssuedInvoice) -> None:
        head = self.session.scalar(
            select(InvoiceDraftHeadRow)
            .where(
                InvoiceDraftHeadRow.id == value.source_invoice_id,
                InvoiceDraftHeadRow.workspace_id == self.workspace_id,
            )
            .with_for_update()
        )
        if (
            head is None
            or head.current_revision != value.source_revision
            or head.issued_invoice_id is not None
        ):
            raise ValueError("InvoiceDraft head cannot be frozen for this issuance")
        head.issued_invoice_id = value.id
        head.issued_revision = value.source_revision
        self.session.flush()

    def _restore(self, row: IssuedInvoiceRow) -> IssuedInvoice:
        currency = InvoiceCurrency(row.currency, row.currency_decimal_places)
        seller_row = self.session.get(IssuedInvoiceSellerRow, row.id)
        client_row = self.session.get(IssuedInvoiceClientRow, row.id)
        if seller_row is None or client_row is None:
            raise ValueError("Issued invoice party snapshots are incomplete")
        seller_legal = _address_from_row(seller_row, "legal")
        client_legal = _address_from_row(client_row, "legal")
        assert seller_legal is not None and client_legal is not None
        seller = IssuedSellerSnapshot(
            legal_entity_kind=LegalEntityKind(seller_row.legal_entity_kind),
            legal_name=seller_row.legal_name,
            trading_name=seller_row.trading_name,
            siren=seller_row.siren,
            siret=seller_row.siret,
            vat_number=seller_row.vat_number,
            legal_address=seller_legal,
            billing_address=_address_from_row(seller_row, "billing"),
            legal_form=seller_row.legal_form,
            share_capital=seller_row.share_capital,
            share_capital_currency=seller_row.share_capital_currency,
        )
        client = IssuedClientSnapshot(
            source_client_id=client_row.source_client_id,
            legal_name=client_row.legal_name,
            trading_name=client_row.trading_name,
            siren=client_row.siren,
            vat_number=client_row.vat_number,
            legal_address=client_legal,
            billing_address=_address_from_row(client_row, "billing"),
        )
        fiscal = IssuedFiscalPaymentSnapshot(
            vat_regime=VatRegime(row.vat_regime),
            franchise_legal_basis=row.franchise_legal_basis,
            franchise_invoice_mention=row.franchise_invoice_mention,
            default_vat_rate_percent=row.default_vat_rate_percent,
            vat_on_debits=row.vat_on_debits,
            operation_category=InvoiceOperationCategory(row.operation_category),
            payment_terms=PaymentTerms(
                PaymentDueRule(row.payment_due_rule), row.payment_net_days
            ),
            early_payment_discount=EarlyPaymentDiscount(
                EarlyPaymentDiscountKind(row.early_discount_kind),
                row.early_discount_rate_percent,
                row.early_discount_days_after_issue,
            ),
            early_payment_discount_mention=row.early_discount_mention,
            late_payment_penalty_annual_rate_percent=(
                row.late_payment_penalty_annual_rate_percent
            ),
            late_payment_minimum_annual_rate_percent=(
                row.late_payment_minimum_annual_rate_percent
            ),
            late_payment_legal_policy=row.late_payment_legal_policy,
            recovery_indemnity_policy=RecoveryIndemnityPolicy(
                row.recovery_indemnity_policy
            ),
            recovery_indemnity_currency=row.recovery_indemnity_currency,
            recovery_indemnity_minor_units=row.recovery_indemnity_minor_units,
        )
        breakdown_rows = tuple(
            self.session.scalars(
                select(IssuedInvoiceVatBreakdownRow)
                .where(IssuedInvoiceVatBreakdownRow.issued_invoice_id == row.id)
                .order_by(IssuedInvoiceVatBreakdownRow.position)
            )
        )
        line_rows = tuple(
            self.session.scalars(
                select(IssuedInvoiceLineRow)
                .where(IssuedInvoiceLineRow.issued_invoice_id == row.id)
                .order_by(IssuedInvoiceLineRow.position)
            )
        )
        lines = tuple(self._restore_line(line_row, currency) for line_row in line_rows)
        line_positions_by_breakdown: dict[int, list[int]] = {}
        for line_row in line_rows:
            line_positions_by_breakdown.setdefault(
                line_row.vat_breakdown_position, []
            ).append(line_row.position)
        breakdowns = tuple(
            IssuedVatBreakdown(
                position=item.position,
                invoice_line_positions=tuple(
                    line_positions_by_breakdown.get(item.position, [])
                ),
                exact_source_ht=ExactMoneyAmount(
                    _integer(item.exact_source_ht_numerator),
                    _integer(item.exact_source_ht_denominator),
                ),
                ht_base=RoundedMoneyAmount(
                    currency, _integer(item.ht_base_minor_units)
                ),
                vat_rate=(
                    VatRate(item.vat_rate_percent)
                    if item.vat_rate_percent is not None
                    else None
                ),
                franchise_legal_basis=item.franchise_legal_basis,
                franchise_invoice_mention=item.franchise_invoice_mention,
                exact_vat_amount=ExactMoneyAmount(
                    _integer(item.exact_vat_numerator),
                    _integer(item.exact_vat_denominator),
                ),
                vat_amount=RoundedMoneyAmount(
                    currency, _integer(item.vat_minor_units)
                ),
                rounding_policy=VatRoundingPolicy(item.rounding_policy),
            )
            for item in breakdown_rows
        )
        return IssuedInvoice(
            id=row.id,
            workspace_id=row.workspace_id,
            source_invoice_id=row.source_invoice_id,
            source_revision=row.source_revision,
            number=LegalInvoiceNumber(
                row.number_series, row.number_sequence, row.invoice_number
            ),
            issued_at=row.issued_at.astimezone(UTC),
            billing_timezone=row.billing_timezone,
            issue_date=row.issue_date,
            service_completion_date=row.service_completion_date,
            due_date=row.due_date,
            purchase_order_number=row.purchase_order_number,
            currency=row.currency,
            currency_decimal_places=row.currency_decimal_places,
            line_rounding_policy=InvoiceLineRoundingPolicy(row.line_rounding_policy),
            seller=seller,
            client=client,
            fiscal_payment=fiscal,
            lines=lines,
            vat_breakdowns=breakdowns,
            exact_source_ht_total=ExactMoneyAmount(
                _integer(row.exact_source_ht_numerator),
                _integer(row.exact_source_ht_denominator),
            ),
            ht_total=RoundedMoneyAmount(currency, _integer(row.ht_minor_units)),
            vat_total=RoundedMoneyAmount(currency, _integer(row.vat_minor_units)),
            ttc_total=RoundedMoneyAmount(currency, _integer(row.ttc_minor_units)),
        )

    def _restore_line(
        self, row: IssuedInvoiceLineRow, currency: InvoiceCurrency
    ) -> IssuedInvoiceLine:
        allocation_rows = self.session.scalars(
            select(IssuedInvoiceAllocationRow)
            .where(
                IssuedInvoiceAllocationRow.issued_invoice_id == row.issued_invoice_id,
                IssuedInvoiceAllocationRow.line_position == row.position,
            )
            .order_by(IssuedInvoiceAllocationRow.position)
        )
        allocations = tuple(
            IssuedInvoiceAllocation(
                position=item.position,
                source_time_entry_id=item.source_time_entry_id,
                source_start=item.source_start.astimezone(UTC),
                source_end=item.source_end.astimezone(UTC),
                source_billable=item.source_billable,
                segment_start=item.segment_start.astimezone(UTC),
                segment_end=item.segment_end.astimezone(UTC),
                business_date=item.business_date,
                duration_microseconds=item.duration_microseconds,
                exact_amount=ExactMoneyAmount(
                    _integer(item.exact_amount_numerator),
                    _integer(item.exact_amount_denominator),
                ),
            )
            for item in allocation_rows
        )
        return IssuedInvoiceLine(
            position=row.position,
            source_invoice_line_id=row.source_invoice_line_id,
            description=row.description,
            project_id=row.project_id,
            project_name=row.project_name,
            task_id=row.task_id,
            task_name=row.task_name,
            rate_agreement_id=row.rate_agreement_id,
            rate_scope_project_id=row.rate_scope_project_id,
            rate_valid_from=row.rate_valid_from,
            rate_valid_until=row.rate_valid_until,
            hourly_rate=row.hourly_rate,
            duration_microseconds=row.duration_microseconds,
            exact_amount=ExactMoneyAmount(
                _integer(row.exact_amount_numerator),
                _integer(row.exact_amount_denominator),
            ),
            rounded_ht=RoundedMoneyAmount(
                currency, _integer(row.rounded_ht_minor_units)
            ),
            allocations=allocations,
        )

    def get(self, issued_invoice_id: UUID) -> IssuedInvoice | None:
        row = self.session.scalar(
            select(IssuedInvoiceRow).where(
                IssuedInvoiceRow.id == issued_invoice_id,
                IssuedInvoiceRow.workspace_id == self.workspace_id,
            )
        )
        return self._restore(row) if row is not None else None

    def list(self) -> list[IssuedInvoice]:
        rows = self.session.scalars(
            select(IssuedInvoiceRow)
            .where(IssuedInvoiceRow.workspace_id == self.workspace_id)
            .order_by(IssuedInvoiceRow.number_sequence)
        )
        return [self._restore(row) for row in rows]
