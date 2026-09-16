"""Deterministic PDF representation of an immutable IssuedInvoice snapshot."""

from collections.abc import Callable, Iterable
from io import BytesIO
from typing import Any, cast
from xml.sax.saxutils import escape

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.enums import TA_RIGHT  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import (  # type: ignore[import-untyped]
    ParagraphStyle,
    getSampleStyleSheet,
)
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from freelanceflow.modules.billing.domain.billing_profiles import BillingAddress
from freelanceflow.modules.billing.domain.invoice_settings import (
    PaymentDueRule,
    VatRegime,
)
from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    IssuedInvoiceArtifactError,
    IssuedInvoiceRepresentation,
)
from freelanceflow.modules.billing.domain.issued_invoices import IssuedInvoice

ISSUED_INVOICE_PDF_RENDERER_VERSION = "freelanceflow-issued-invoice-pdf-v1"
ISSUED_INVOICE_PDF_MEDIA_TYPE = "application/pdf"

_FONT_REGULAR = "FreelanceFlowVera"
_FONT_BOLD = "FreelanceFlowVeraBold"

pdfmetrics.registerFont(TTFont(_FONT_REGULAR, "Vera.ttf"))
pdfmetrics.registerFont(TTFont(_FONT_BOLD, "VeraBd.ttf"))


class IssuedInvoicePdfRenderingError(IssuedInvoiceArtifactError):
    """The immutable issued snapshot cannot be represented safely as PDF."""


class UnsupportedInvoicePdfCharacterError(IssuedInvoicePdfRenderingError):
    """The embedded renderer font cannot represent invoice text exactly."""


def _text(value: object) -> str:
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


def _money(minor_units: int, decimal_places: int, currency: str) -> str:
    factor = 10**decimal_places
    whole, fractional = divmod(minor_units, factor)
    # Vera embeds U+00A0 but not U+202F; use an explicit non-breaking space so
    # large monetary values cannot silently render a missing-glyph placeholder.
    number = f"{whole:,}".replace(",", "\u00a0")
    if decimal_places:
        number += f",{fractional:0{decimal_places}d}"
    return f"{number} {currency}"


def _duration(microseconds: int) -> str:
    seconds, micros = divmod(microseconds, 1_000_000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    suffix = f".{micros:06d}" if micros else ""
    return f"{hours:d} h {minutes:02d} min {seconds:02d}{suffix} s"


def _address_lines(address: BillingAddress) -> tuple[str, ...]:
    city_line = " ".join(
        value for value in (address.postal_code, address.city) if value is not None
    )
    return tuple(
        value
        for value in (address.line1, address.line2, city_line, address.country_code)
        if value
    )


def _payment_term(invoice: IssuedInvoice) -> str:
    terms = invoice.fiscal_payment.payment_terms
    if terms.due_rule is PaymentDueRule.DUE_ON_ISSUE:
        return "Paiement à réception"
    if terms.due_rule is PaymentDueRule.NET_DAYS_AFTER_ISSUE:
        assert terms.net_days is not None
        return f"Paiement à {terms.net_days} jours calendaires après émission"
    if terms.due_rule is PaymentDueRule.INVOICE_MONTH_END_PLUS_45_DAYS:
        return "Paiement à 45 jours après la fin du mois de facturation"
    return "Paiement à la fin du mois atteint 45 jours après émission"


def _invoice_strings(invoice: IssuedInvoice) -> Iterable[str]:
    """All dynamic text passed to ReportLab, for explicit glyph validation."""
    seller = invoice.seller
    client = invoice.client
    fiscal = invoice.fiscal_payment
    values: list[object | None] = [
        invoice.number.value,
        invoice.purchase_order_number,
        seller.legal_name,
        seller.trading_name,
        seller.siren,
        seller.siret,
        seller.vat_number,
        seller.legal_form,
        seller.share_capital,
        seller.share_capital_currency,
        client.legal_name,
        client.trading_name,
        client.siren,
        client.vat_number,
        fiscal.franchise_invoice_mention,
        fiscal.early_payment_discount_mention,
        fiscal.late_payment_penalty_annual_rate_percent,
        *(_address_lines(seller.legal_address)),
        *(_address_lines(seller.billing_address) if seller.billing_address else ()),
        *(_address_lines(client.legal_address)),
        *(_address_lines(client.billing_address) if client.billing_address else ()),
    ]
    for line in invoice.lines:
        values.extend(
            (line.description, line.project_name, line.task_name, line.hourly_rate)
        )
    return (str(value) for value in values if value is not None)


def _validate_embedded_font(invoice: IssuedInvoice) -> None:
    font = cast(Any, pdfmetrics.getFont(_FONT_REGULAR))
    supported = font.face.charToGlyph
    missing = sorted(
        {
            ord(character)
            for value in _invoice_strings(invoice)
            for character in value
            if ord(character) not in supported
        }
    )
    if missing:
        rendered = ", ".join(f"U+{value:04X}" for value in missing)
        raise UnsupportedInvoicePdfCharacterError(
            f"Embedded invoice font does not support: {rendered}"
        )


def _invariant_canvas(*args: object, **kwargs: object) -> Canvas:
    options = dict(kwargs)
    options.update(
        invariant=1,
        pageCompression=1,
        lang="fr-FR",
        initialFontName=_FONT_REGULAR,
    )
    return Canvas(*args, **options)


def _set_document_metadata(canvas: Canvas, _document: object) -> None:
    canvas.setAuthor("FreelanceFlow")
    canvas.setCreator(ISSUED_INVOICE_PDF_RENDERER_VERSION)
    canvas.setProducer(ISSUED_INVOICE_PDF_RENDERER_VERSION)
    canvas.setSubject("Facture")
    canvas.setTitle("Facture FreelanceFlow")


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "InvoiceTitle",
            parent=sample["Title"],
            fontName=_FONT_BOLD,
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=5 * mm,
        ),
        "heading": ParagraphStyle(
            "InvoiceHeading",
            parent=sample["Heading2"],
            fontName=_FONT_BOLD,
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#374151"),
            spaceAfter=1.5 * mm,
        ),
        "body": ParagraphStyle(
            "InvoiceBody",
            parent=sample["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#111827"),
        ),
        "small": ParagraphStyle(
            "InvoiceSmall",
            parent=sample["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=7.2,
            leading=9,
            textColor=colors.HexColor("#374151"),
        ),
        "right": ParagraphStyle(
            "InvoiceRight",
            parent=sample["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=8.5,
            leading=11,
            alignment=TA_RIGHT,
        ),
        "right_bold": ParagraphStyle(
            "InvoiceRightBold",
            parent=sample["BodyText"],
            fontName=_FONT_BOLD,
            fontSize=9,
            leading=12,
            alignment=TA_RIGHT,
        ),
    }


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_text(value), style)


def _rich_paragraph(value: str, style: ParagraphStyle) -> Paragraph:
    """Create a paragraph from renderer-owned markup with escaped dynamic values."""
    return Paragraph(value, style)


def _party_blocks(invoice: IssuedInvoice, styles: dict[str, ParagraphStyle]) -> Table:
    seller = invoice.seller
    client = invoice.client
    seller_lines = [seller.legal_name]
    if seller.trading_name:
        seller_lines.append(seller.trading_name)
    seller_lines.append("Adresse légale :")
    seller_lines.extend(_address_lines(seller.legal_address))
    if seller.billing_address is not None:
        seller_lines.append("Adresse de facturation :")
        seller_lines.extend(_address_lines(seller.billing_address))
    seller_lines.extend((f"SIREN : {seller.siren}", f"SIRET : {seller.siret}"))
    if seller.vat_number:
        seller_lines.append(f"TVA intracommunautaire : {seller.vat_number}")
    if seller.legal_form:
        seller_lines.append(f"Forme juridique : {seller.legal_form}")
    if seller.share_capital is not None and seller.share_capital_currency:
        seller_lines.append(
            f"Capital social : {seller.share_capital} {seller.share_capital_currency}"
        )

    client_lines = [client.legal_name]
    if client.trading_name:
        client_lines.append(client.trading_name)
    client_lines.append("Adresse légale :")
    client_lines.extend(_address_lines(client.legal_address))
    if client.billing_address is not None:
        client_lines.append("Adresse de facturation :")
        client_lines.extend(_address_lines(client.billing_address))
    client_lines.append(f"SIREN : {client.siren}")
    if client.vat_number:
        client_lines.append(f"TVA intracommunautaire : {client.vat_number}")

    data = [
        [
            _paragraph("ÉMETTEUR", styles["heading"]),
            _paragraph("CLIENT", styles["heading"]),
        ],
        [
            _rich_paragraph(
                "<br/>".join(_text(value) for value in seller_lines), styles["body"]
            ),
            _rich_paragraph(
                "<br/>".join(_text(value) for value in client_lines), styles["body"]
            ),
        ],
    ]
    table = Table(data, colWidths=(86 * mm, 86 * mm), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        )
    )
    return table


def _line_table(invoice: IssuedInvoice, styles: dict[str, ParagraphStyle]) -> Table:
    header = [
        _paragraph("Description", styles["small"]),
        _paragraph("Projet / tâche", styles["small"]),
        _paragraph("Durée", styles["small"]),
        _paragraph("Taux HT", styles["small"]),
        _paragraph("Montant HT", styles["small"]),
    ]
    rows: list[list[Paragraph]] = [header]
    for line in invoice.lines:
        context = line.project_name
        if line.task_name:
            context += f" / {line.task_name}"
        rows.append(
            [
                _paragraph(line.description, styles["body"]),
                _paragraph(context, styles["small"]),
                _paragraph(_duration(line.duration_microseconds), styles["small"]),
                _paragraph(f"{line.hourly_rate} {invoice.currency}/h", styles["right"]),
                _paragraph(
                    _money(
                        line.rounded_ht.minor_units,
                        invoice.currency_decimal_places,
                        invoice.currency,
                    ),
                    styles["right"],
                ),
            ]
        )
    table = Table(
        rows,
        colWidths=(57 * mm, 37 * mm, 31 * mm, 25 * mm, 30 * mm),
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
                ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ]
        )
    )
    return table


def _vat_and_totals(invoice: IssuedInvoice, styles: dict[str, ParagraphStyle]) -> Table:
    vat_rows: list[list[Paragraph]] = [
        [
            _paragraph("Base HT", styles["small"]),
            _paragraph("Traitement / taux", styles["small"]),
            _paragraph("TVA", styles["small"]),
        ]
    ]
    for breakdown in invoice.vat_breakdowns:
        treatment = (
            breakdown.franchise_invoice_mention
            if breakdown.vat_rate is None
            else f"{breakdown.vat_rate.percent} %"
        )
        vat_rows.append(
            [
                _paragraph(
                    _money(
                        breakdown.ht_base.minor_units,
                        invoice.currency_decimal_places,
                        invoice.currency,
                    ),
                    styles["right"],
                ),
                _paragraph(treatment or "Franchise en base", styles["small"]),
                _paragraph(
                    _money(
                        breakdown.vat_amount.minor_units,
                        invoice.currency_decimal_places,
                        invoice.currency,
                    ),
                    styles["right"],
                ),
            ]
        )
    vat_table = Table(vat_rows, colWidths=(34 * mm, 60 * mm, 34 * mm), repeatRows=1)
    vat_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        )
    )
    totals = Table(
        [
            [
                _paragraph("Total HT", styles["right"]),
                _paragraph(
                    _money(
                        invoice.ht_total.minor_units,
                        invoice.currency_decimal_places,
                        invoice.currency,
                    ),
                    styles["right"],
                ),
            ],
            [
                _paragraph("Total TVA", styles["right"]),
                _paragraph(
                    _money(
                        invoice.vat_total.minor_units,
                        invoice.currency_decimal_places,
                        invoice.currency,
                    ),
                    styles["right"],
                ),
            ],
            [
                _paragraph("Total TTC", styles["right_bold"]),
                _paragraph(
                    _money(
                        invoice.ttc_total.minor_units,
                        invoice.currency_decimal_places,
                        invoice.currency,
                    ),
                    styles["right_bold"],
                ),
            ],
        ],
        colWidths=(30 * mm, 34 * mm),
        hAlign="RIGHT",
    )
    totals.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.HexColor("#111827")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return Table(
        [[vat_table, totals]],
        colWidths=(128 * mm, 52 * mm),
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )


def render_issued_invoice_pdf(invoice: IssuedInvoice) -> bytes:
    """Render byte-identical PDF bytes for one immutable issuance snapshot."""
    _validate_embedded_font(invoice)
    styles = _styles()
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Facture FreelanceFlow",
        author="FreelanceFlow",
        subject="Facture",
        creator=ISSUED_INVOICE_PDF_RENDERER_VERSION,
        producer=ISSUED_INVOICE_PDF_RENDERER_VERSION,
    )
    issue_details = [
        [
            _paragraph("Numéro", styles["small"]),
            _paragraph(invoice.number.value, styles["right_bold"]),
        ],
        [
            _paragraph("Date d'émission", styles["small"]),
            _paragraph(invoice.issue_date.strftime("%d/%m/%Y"), styles["right"]),
        ],
        [
            _paragraph("Date de réalisation", styles["small"]),
            _paragraph(
                invoice.service_completion_date.strftime("%d/%m/%Y"), styles["right"]
            ),
        ],
        [
            _paragraph("Date d'échéance", styles["small"]),
            _paragraph(invoice.due_date.strftime("%d/%m/%Y"), styles["right"]),
        ],
    ]
    if invoice.purchase_order_number:
        issue_details.append(
            [
                _paragraph("Bon de commande", styles["small"]),
                _paragraph(invoice.purchase_order_number, styles["right"]),
            ]
        )
    details = Table(issue_details, colWidths=(35 * mm, 45 * mm), hAlign="RIGHT")
    details.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
            ]
        )
    )
    title = Table(
        [[_paragraph("FACTURE", styles["title"]), details]],
        colWidths=(100 * mm, 80 * mm),
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )

    fiscal = invoice.fiscal_payment
    recovery_amount = _money(
        fiscal.recovery_indemnity_minor_units,
        2,
        fiscal.recovery_indemnity_currency,
    )
    payment_lines = [
        "Catégorie d'opération : prestations de services",
        f"Conditions de paiement : {_payment_term(invoice)}",
        f"Échéance : {invoice.due_date.strftime('%d/%m/%Y')}",
        fiscal.early_payment_discount_mention,
        (
            "Pénalités de retard : "
            f"{fiscal.late_payment_penalty_annual_rate_percent} % par an"
        ),
        (
            "Indemnité forfaitaire pour frais de recouvrement : "
            f"{recovery_amount}"
        ),
    ]
    if fiscal.vat_on_debits:
        payment_lines.append("TVA acquittée d'après les débits")
    if fiscal.vat_regime is VatRegime.FRANCHISE_EN_BASE:
        assert fiscal.franchise_invoice_mention is not None
        payment_lines.append(fiscal.franchise_invoice_mention)
    story: list[Any] = [
        title,
        Spacer(1, 4 * mm),
        _party_blocks(invoice, styles),
        Spacer(1, 5 * mm),
        _line_table(invoice, styles),
        Spacer(1, 5 * mm),
        _vat_and_totals(invoice, styles),
        Spacer(1, 6 * mm),
        KeepTogether(
            [
                _paragraph("CONDITIONS DE PAIEMENT", styles["heading"]),
                _rich_paragraph(
                    "<br/>".join(_text(value) for value in payment_lines),
                    styles["small"],
                ),
            ]
        ),
    ]
    canvas_maker = cast(Callable[..., Canvas], _invariant_canvas)
    document.build(
        story,
        onFirstPage=_set_document_metadata,
        onLaterPages=_set_document_metadata,
        canvasmaker=canvas_maker,
    )
    return output.getvalue()


class ReportLabIssuedInvoicePdfRenderer:
    """Narrow application adapter for the versioned deterministic PDF renderer."""

    representation = IssuedInvoiceRepresentation.PDF
    renderer_version = ISSUED_INVOICE_PDF_RENDERER_VERSION
    media_type = ISSUED_INVOICE_PDF_MEDIA_TYPE

    def render(self, invoice: IssuedInvoice) -> bytes:
        return render_issued_invoice_pdf(invoice)
