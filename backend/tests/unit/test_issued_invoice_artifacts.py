import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from pypdf import PdfReader

from freelanceflow.modules.billing.adapters.issued_invoice_pdf_renderer import (
    ISSUED_INVOICE_PDF_RENDERER_VERSION,
    UnsupportedInvoicePdfCharacterError,
    render_issued_invoice_pdf,
)
from freelanceflow.modules.billing.domain.billing_profiles import (
    BillingAddress,
    LegalEntityKind,
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
)
from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    InvalidIssuedInvoiceArtifactError,
    IssuedInvoiceArtifact,
    IssuedInvoiceArtifactMetadata,
    IssuedInvoiceRepresentation,
    freeze_issued_invoice_artifact,
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

WORKSPACE_ID = UUID(int=1)
ISSUED_INVOICE_ID = UUID(int=2)
CREATED_AT = datetime(2026, 9, 16, 9, 30, tzinfo=UTC)
CURRENCY = InvoiceCurrency("EUR", 2)


def _invoice(
    *, franchise: bool = False, legal_name: str = "Élodie & Associés SAS"
) -> IssuedInvoice:
    allocation = IssuedInvoiceAllocation(
        position=0,
        source_time_entry_id=UUID(int=30),
        source_start=datetime(2026, 9, 1, 9, tzinfo=UTC),
        source_end=datetime(2026, 9, 1, 10, tzinfo=UTC),
        source_billable=True,
        segment_start=datetime(2026, 9, 1, 9, tzinfo=UTC),
        segment_end=datetime(2026, 9, 1, 10, tzinfo=UTC),
        business_date=date(2026, 9, 1),
        duration_microseconds=3_600_000_000,
        exact_amount=ExactMoneyAmount(100, 1),
    )
    line = IssuedInvoiceLine(
        position=0,
        source_invoice_line_id=UUID(int=31),
        description="Conseil en stratégie — phase 1",
        project_id=UUID(int=32),
        project_name="Déploiement européen",
        task_id=UUID(int=33),
        task_name="Étude & synthèse",
        rate_agreement_id=UUID(int=34),
        rate_scope_project_id=UUID(int=32),
        rate_valid_from=date(2026, 1, 1),
        rate_valid_until=None,
        hourly_rate=Decimal("100.00"),
        duration_microseconds=3_600_000_000,
        exact_amount=ExactMoneyAmount(100, 1),
        rounded_ht=RoundedMoneyAmount(CURRENCY, 10_000),
        allocations=(allocation,),
    )
    vat_amount = 0 if franchise else 2_000
    breakdown = IssuedVatBreakdown(
        position=0,
        invoice_line_positions=(0,),
        exact_source_ht=ExactMoneyAmount(100, 1),
        ht_base=RoundedMoneyAmount(CURRENCY, 10_000),
        vat_rate=None if franchise else VatRate(Decimal("20.000")),
        franchise_legal_basis="cgi_article_293_b" if franchise else None,
        franchise_invoice_mention=(
            "TVA non applicable, art. 293 B du CGI" if franchise else None
        ),
        exact_vat_amount=ExactMoneyAmount(vat_amount // 100, 1),
        vat_amount=RoundedMoneyAmount(CURRENCY, vat_amount),
        rounding_policy=VatRoundingPolicy.PER_RATE_SUBTOTAL_HALF_UP,
    )
    address = BillingAddress(
        "10 rue de l'Église", "Paris", "FR", "75001", "Bâtiment A"
    )
    fiscal = IssuedFiscalPaymentSnapshot(
        vat_regime=(
            VatRegime.FRANCHISE_EN_BASE if franchise else VatRegime.TAXABLE
        ),
        franchise_legal_basis="cgi_article_293_b" if franchise else None,
        franchise_invoice_mention=(
            "TVA non applicable, art. 293 B du CGI" if franchise else None
        ),
        default_vat_rate_percent=None if franchise else Decimal("20.000"),
        vat_on_debits=not franchise,
        operation_category=InvoiceOperationCategory.SERVICES,
        payment_terms=PaymentTerms(PaymentDueRule.NET_DAYS_AFTER_ISSUE, 30),
        early_payment_discount=EarlyPaymentDiscount(EarlyPaymentDiscountKind.NONE),
        early_payment_discount_mention="Escompte pour paiement anticipé : néant",
        late_payment_penalty_annual_rate_percent=Decimal("8.25"),
        late_payment_minimum_annual_rate_percent=Decimal("8.25"),
        late_payment_legal_policy="fr_l441_10_three_times_legal_interest_2026_h2",
        recovery_indemnity_policy=RecoveryIndemnityPolicy.FRENCH_B2B_40_EUR,
        recovery_indemnity_currency="EUR",
        recovery_indemnity_minor_units=4_000,
    )
    return IssuedInvoice(
        id=ISSUED_INVOICE_ID,
        workspace_id=WORKSPACE_ID,
        source_invoice_id=UUID(int=3),
        source_revision=1,
        number=LegalInvoiceNumber("main", 42, "42"),
        issued_at=datetime(2026, 9, 16, 0, 30, 0, 123456, tzinfo=UTC),
        billing_timezone="Europe/Paris",
        issue_date=date(2026, 9, 16),
        service_completion_date=date(2026, 9, 15),
        due_date=date(2026, 10, 16),
        purchase_order_number="BC-ÉTÉ-42",
        currency="EUR",
        currency_decimal_places=2,
        line_rounding_policy=InvoiceLineRoundingPolicy.PER_LINE_HALF_UP,
        seller=IssuedSellerSnapshot(
            legal_entity_kind=LegalEntityKind.COMPANY,
            legal_name=legal_name,
            trading_name="Atelier Numérique",
            siren="552100554",
            siret="55210055400013",
            vat_number=None if franchise else "FR96552100554",
            legal_address=address,
            billing_address=None,
            legal_form="SAS",
            share_capital=Decimal("1000.00"),
            share_capital_currency="EUR",
        ),
        client=IssuedClientSnapshot(
            source_client_id=UUID(int=4),
            legal_name="Société Générale d'Essais",
            trading_name=None,
            siren="130025265",
            vat_number="FR07130025265",
            legal_address=address,
            billing_address=None,
        ),
        fiscal_payment=fiscal,
        lines=(line,),
        vat_breakdowns=(breakdown,),
        exact_source_ht_total=ExactMoneyAmount(100, 1),
        ht_total=RoundedMoneyAmount(CURRENCY, 10_000),
        vat_total=RoundedMoneyAmount(CURRENCY, vat_amount),
        ttc_total=RoundedMoneyAmount(CURRENCY, 10_000 + vat_amount),
    )


def _two_line_invoice() -> IssuedInvoice:
    invoice = _invoice()
    first = invoice.lines[0]
    second_allocation = replace(
        first.allocations[0],
        position=0,
        source_time_entry_id=UUID(int=40),
    )
    second = replace(
        first,
        position=1,
        source_invoice_line_id=UUID(int=41),
        description="Formation avancée",
        allocations=(second_allocation,),
    )
    breakdown = replace(
        invoice.vat_breakdowns[0],
        invoice_line_positions=(0, 1),
        exact_source_ht=ExactMoneyAmount(200, 1),
        ht_base=RoundedMoneyAmount(CURRENCY, 20_000),
        exact_vat_amount=ExactMoneyAmount(40, 1),
        vat_amount=RoundedMoneyAmount(CURRENCY, 4_000),
    )
    return replace(
        invoice,
        lines=(first, second),
        vat_breakdowns=(breakdown,),
        exact_source_ht_total=ExactMoneyAmount(200, 1),
        ht_total=RoundedMoneyAmount(CURRENCY, 20_000),
        vat_total=RoundedMoneyAmount(CURRENCY, 4_000),
        ttc_total=RoundedMoneyAmount(CURRENCY, 24_000),
    )


@pytest.mark.parametrize("franchise", [False, True])
def test_pdf_rendering_is_byte_deterministic_with_frozen_metadata(
    monkeypatch: pytest.MonkeyPatch, franchise: bool
) -> None:
    invoice = _invoice(franchise=franchise)
    monkeypatch.setenv("TZ", "Pacific/Honolulu")
    time.tzset()
    first = render_issued_invoice_pdf(invoice)
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    second = render_issued_invoice_pdf(invoice)

    assert first == second
    assert sha256(first).digest() == sha256(second).digest()
    assert first.startswith(b"%PDF-")
    assert b"D:20000101000000+00'00'" in first
    assert ISSUED_INVOICE_PDF_RENDERER_VERSION.encode() in first


def test_renderer_rejects_unsupported_glyph_instead_of_corrupting_name() -> None:
    with pytest.raises(UnsupportedInvoicePdfCharacterError, match=r"U\+1F9FE"):
        render_issued_invoice_pdf(_invoice(legal_name="Invoice 🧾 Company"))


@pytest.mark.parametrize(
    ("invoice", "expected", "unexpected"),
    [
        (
            _two_line_invoice(),
            ("Élodie & Associés SAS", "Formation avancée", "20.000 %", "240,00 EUR"),
            ("TVA non applicable",),
        ),
        (
            _invoice(franchise=True),
            ("TVA non applicable, art. 293 B du CGI", "100,00 EUR"),
            ("20.000 %",),
        ),
    ],
)
def test_pdf_contains_snapshotted_legal_financial_and_payment_content(
    invoice: IssuedInvoice,
    expected: tuple[str, ...],
    unexpected: tuple[str, ...],
) -> None:
    reader = PdfReader(BytesIO(render_issued_invoice_pdf(invoice)))
    extracted = "\n".join(page.extract_text() for page in reader.pages)

    assert "FACTURE" in extracted
    assert "Date de réalisation" in extracted
    assert "BC-ÉTÉ-42" in extracted
    assert "Escompte pour paiement anticipé : néant" in extracted
    assert "Indemnité forfaitaire pour frais de recouvrement" in extracted
    for value in expected:
        assert value in extracted
    for value in unexpected:
        assert value not in extracted


def test_issued_artifact_derives_and_validates_integrity() -> None:
    content = render_issued_invoice_pdf(_invoice())
    artifact = freeze_issued_invoice_artifact(
        artifact_id=UUID(int=50),
        workspace_id=WORKSPACE_ID,
        issued_invoice_id=ISSUED_INVOICE_ID,
        representation=IssuedInvoiceRepresentation.PDF,
        renderer_version=ISSUED_INVOICE_PDF_RENDERER_VERSION,
        media_type="application/pdf",
        content=content,
        created_at=CREATED_AT,
    )

    assert artifact.metadata.sha256 == sha256(content).hexdigest()
    assert artifact.metadata.byte_size == len(content)
    with pytest.raises(InvalidIssuedInvoiceArtifactError, match="SHA-256"):
        IssuedInvoiceArtifact(
            metadata=replace(artifact.metadata, sha256="0" * 64),
            content=content,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"renderer_version": " "},
        {"media_type": ""},
        {"byte_size": 0},
        {"sha256": "A" * 64},
        {"created_at": datetime(2026, 9, 16)},
        {"created_at": datetime(2026, 9, 16, tzinfo=timezone(timedelta(hours=2)))},
    ],
)
def test_issued_artifact_metadata_rejects_invalid_values(
    change: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "id": UUID(int=50),
        "workspace_id": WORKSPACE_ID,
        "issued_invoice_id": ISSUED_INVOICE_ID,
        "representation": IssuedInvoiceRepresentation.PDF,
        "renderer_version": ISSUED_INVOICE_PDF_RENDERER_VERSION,
        "media_type": "application/pdf",
        "sha256": "a" * 64,
        "byte_size": 1,
        "created_at": CREATED_AT,
    }
    with pytest.raises(InvalidIssuedInvoiceArtifactError):
        IssuedInvoiceArtifactMetadata(**(values | change))  # type: ignore[arg-type]
