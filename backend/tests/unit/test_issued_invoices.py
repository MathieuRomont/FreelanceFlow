from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, getcontext
from typing import Any, cast
from uuid import UUID

import pytest

from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.billing.domain.billing_profiles import (
    BillingAddress,
    ClientBillingProfile,
    LegalEntityKind,
    WorkspaceBillingProfile,
)
from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceDraft,
    InvoiceLineInput,
    build_invoice_draft,
)
from freelanceflow.modules.billing.domain.invoice_settings import (
    BillingTimezone,
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
from freelanceflow.modules.billing.domain.issued_invoices import (
    IncompleteLegalInvoiceError,
    InvoiceLineDescription,
    IssuedInvoice,
    LegalInvoiceNumber,
    UnsupportedLegalPolicyDateError,
    issue_invoice,
    minimum_french_b2b_late_penalty_rate,
)
from freelanceflow.modules.billing.domain.pricing import (
    PreparedBillingSegment,
    RateAgreementReference,
    price_prepared_segment,
)
from freelanceflow.modules.billing.domain.vat import calculate_invoice_vat
from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.domain import TimeEntry

WORKSPACE_ID = UUID(int=1)
CLIENT = Client(UUID(int=2), WORKSPACE_ID, "Mutable display name")
PROJECT = Project(UUID(int=3), CLIENT, "Project snapshot")
TASK = Task(UUID(int=4), PROJECT, "Task snapshot")
ISSUED_AT = datetime(2026, 9, 15, 12, 30, 0, 123456, tzinfo=UTC)
ADDRESS = BillingAddress("1 rue de Paris", "Paris", "FR", "75001")


def _draft() -> InvoiceDraft:
    entry = TimeEntry(
        UUID(int=10),
        WORKSPACE_ID,
        datetime(2026, 9, 1, 9, tzinfo=UTC),
        datetime(2026, 9, 1, 9, 20, 0, 1, tzinfo=UTC),
        True,
        CLIENT,
        PROJECT,
        TASK,
    )
    rate = RateAgreementReference(
        UUID(int=11),
        RateAgreement(
            client=CLIENT,
            project=PROJECT,
            hourly_amount=Decimal("100.123400"),
            currency="EUR",
            valid_from=date(2026, 1, 1),
        ),
    )
    priced = price_prepared_segment(
        PreparedBillingSegment.for_complete_entry(entry, business_date=date(2026, 9, 1)),
        (rate,),
    )
    return build_invoice_draft(
        draft_id=UUID(int=12),
        revision=2,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT.id,
        line_inputs=(InvoiceLineInput(UUID(int=13), (priced,)),),
    )


def _seller(*, vat_number: str | None = "FR96552100554") -> WorkspaceBillingProfile:
    return WorkspaceBillingProfile(
        workspace_id=WORKSPACE_ID,
        legal_entity_kind=LegalEntityKind.COMPANY,
        legal_name="Seller SAS",
        siren="552100554",
        siret="55210055400013",
        vat_number=vat_number,
        legal_address=ADDRESS,
        legal_form="SAS",
        share_capital=Decimal("1000.00"),
        share_capital_currency="EUR",
    )


def _buyer(*, country: str = "FR") -> ClientBillingProfile:
    address = ADDRESS if country == "FR" else BillingAddress("1 Main St", "London", country)
    return ClientBillingProfile(
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT.id,
        legal_name="Buyer SAS",
        legal_address=address,
        siren="552100554" if country == "FR" else None,
    )


def _settings(*, late_rate: str = "8.25") -> WorkspaceInvoiceSettings:
    return WorkspaceInvoiceSettings(
        workspace_id=WORKSPACE_ID,
        fiscal=FiscalSettings(VatRegime.TAXABLE, None, Decimal("20.000"), True),
        payment_terms=PaymentTerms(PaymentDueRule.NET_DAYS_AFTER_ISSUE, 30),
        early_payment_discount=EarlyPaymentDiscount(EarlyPaymentDiscountKind.NONE),
        late_payment_penalty_annual_rate_percent=Decimal(late_rate),
        recovery_indemnity_policy=RecoveryIndemnityPolicy.FRENCH_B2B_40_EUR,
        operation_category=InvoiceOperationCategory.SERVICES,
        billing_timezone=BillingTimezone("Europe/Paris"),
    )


def _issue(**changes: Any) -> IssuedInvoice:
    draft = _draft()
    settings = _settings()
    values = {
        "issued_invoice_id": UUID(int=20),
        "number": LegalInvoiceNumber("main", 7, "7"),
        "draft": draft,
        "seller_profile": _seller(),
        "client_profile": _buyer(),
        "settings": settings,
        "tax": calculate_invoice_vat(draft, settings),
        "issued_at": ISSUED_AT,
        "issue_date": date(2026, 9, 15),
        "service_completion_date": date(2026, 9, 14),
        "due_date": date(2026, 10, 15),
        "line_descriptions": (
            InvoiceLineDescription(draft.lines[0].id, "Twenty minutes of consulting"),
        ),
        "purchase_order_number": "PO-42",
    }
    values.update(changes)
    issuer = cast(Callable[..., IssuedInvoice], issue_invoice)
    return issuer(**values)


def test_issuance_snapshots_exact_legal_financial_and_source_values() -> None:
    issued = _issue()

    assert issued.number.value == "7"
    assert issued.issued_at.microsecond == 123456
    assert issued.seller.legal_name == "Seller SAS"
    assert issued.client.legal_name == "Buyer SAS"
    assert issued.lines[0].description == "Twenty minutes of consulting"
    assert issued.lines[0].project_name == "Project snapshot"
    assert issued.lines[0].task_name == "Task snapshot"
    assert issued.lines[0].allocations[0].source_time_entry_id == UUID(int=10)
    assert issued.lines[0].exact_amount == _draft().lines[0].exact_amount
    assert issued.exact_source_ht_total == _draft().exact_subtotal
    assert issued.ht_total.minor_units + issued.vat_total.minor_units == (
        issued.ttc_total.minor_units
    )
    assert issued.fiscal_payment.late_payment_minimum_annual_rate_percent == Decimal(
        "8.25"
    )
    assert issued.fiscal_payment.early_payment_discount_mention == (
        "Escompte pour paiement anticipé : néant"
    )


def test_issuance_is_independent_from_decimal_context() -> None:
    original = getcontext().copy()
    try:
        getcontext().prec = 2
        first = _issue()
        getcontext().prec = 50
        second = _issue()
    finally:
        getcontext().prec = original.prec
        getcontext().rounding = original.rounding
    assert first == second


def test_issuance_requires_complete_descriptions_domestic_identity_and_dates() -> None:
    with pytest.raises(IncompleteLegalInvoiceError, match="description"):
        _issue(line_descriptions=())
    with pytest.raises(IncompleteLegalInvoiceError, match="French B2B"):
        _issue(client_profile=_buyer(country="GB"))
    with pytest.raises(IncompleteLegalInvoiceError, match="after"):
        _issue(service_completion_date=date(2026, 9, 16))
    with pytest.raises(IncompleteLegalInvoiceError, match="VAT identification"):
        _issue(seller_profile=_seller(vat_number=None))


def test_franchise_is_not_represented_as_zero_rate() -> None:
    draft = _draft()
    settings = replace(
        _settings(),
        fiscal=FiscalSettings(
            VatRegime.FRANCHISE_EN_BASE,
            FranchiseLegalBasis.CGI_ARTICLE_293_B,
            None,
            False,
        ),
    )
    issued = _issue(
        settings=settings,
        tax=calculate_invoice_vat(draft, settings),
        seller_profile=_seller(vat_number=None),
    )
    assert issued.fiscal_payment.vat_regime is VatRegime.FRANCHISE_EN_BASE
    assert issued.vat_breakdowns[0].vat_rate is None
    assert issued.vat_breakdowns[0].franchise_invoice_mention is not None


def test_effective_late_penalty_floor_is_explicit_and_date_bounded() -> None:
    assert minimum_french_b2b_late_penalty_rate(date(2026, 6, 30))[0] == Decimal(
        "7.86"
    )
    assert minimum_french_b2b_late_penalty_rate(date(2026, 7, 1))[0] == Decimal(
        "8.25"
    )
    with pytest.raises(UnsupportedLegalPolicyDateError):
        minimum_french_b2b_late_penalty_rate(date(2027, 1, 1))
    with pytest.raises(IncompleteLegalInvoiceError, match="at least 8.25"):
        _issue(settings=_settings(late_rate="8.24"))
