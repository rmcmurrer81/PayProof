"""Build polished, clearly synthetic PDF copies of bundled intake paperwork."""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "demo_intake"
OUTPUT_DIR = ROOT / "output" / "pdf" / "demo_intake"

REVIEW_SIGNALS = {
    "EXP-2026-041": ("Routine sample", ["Receipt matched", "Manager approved"]),
    "EXP-2026-042": ("Routine sample", ["Receipt matched", "Manager approved"]),
    "EXP-2026-043": (
        "Possible issue - review only",
        ["Receipt is missing", "Approval is still pending"],
    ),
    "EXP-2026-044": (
        "Pending review",
        ["Mileage calculation is documented", "Approval is still pending"],
    ),
}


def money(amount: str, currency: str) -> str:
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{prefix}{float(amount):,.2f}"


def build_pdf(record: dict[str, object], output_path: Path) -> None:
    styles = getSampleStyleSheet()
    navy = colors.HexColor("#071827")
    cyan = colors.HexColor("#28c8ff")
    pale = colors.HexColor("#eaf8ff")
    red = colors.HexColor("#db3659")
    amber = colors.HexColor("#f0a928")
    gray = colors.HexColor("#5f6f7c")
    light_gray = colors.HexColor("#e5edf2")

    title_style = ParagraphStyle(
        "Title", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=23, leading=27, textColor=navy, alignment=TA_LEFT,
        spaceAfter=2,
    )
    meta_style = ParagraphStyle(
        "Meta", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9, leading=12, textColor=gray,
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=8, leading=10, textColor=gray,
    )
    value_style = ParagraphStyle(
        "Value", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=11, leading=14, textColor=navy,
    )
    warning_style = ParagraphStyle(
        "Warning", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=10, leading=14, textColor=red,
    )
    note_style = ParagraphStyle(
        "Note", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9, leading=13, textColor=navy,
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8, leading=10, textColor=gray, alignment=TA_CENTER,
    )
    amount_style = ParagraphStyle(
        "Amount", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=24, leading=26, textColor=navy, alignment=TA_RIGHT,
    )

    record_id = str(record["id"])
    review_label, default_signals = REVIEW_SIGNALS.get(
        record_id, ("Review required", ["A person must verify this paperwork"]),
    )
    review_label = str(record.get("demo_review_label") or review_label)
    signals = record.get("demo_review_signals") or default_signals
    if not isinstance(signals, list):
        signals = default_signals
    is_attention = "routine" not in review_label.casefold()
    accent = red if "fraud" in review_label.casefold() else (amber if is_attention else cyan)

    doc = SimpleDocTemplate(
        str(output_path), pagesize=LETTER,
        leftMargin=0.62 * inch, rightMargin=0.62 * inch,
        topMargin=0.38 * inch, bottomMargin=0.32 * inch,
        title=f"Synthetic PayProof paperwork {record_id}",
        author="PayProof demonstration",
        subject="Fictional bookkeeping evidence for product demonstration",
    )

    story: list[object] = []
    banner = Table(
        [[Paragraph("SYNTHETIC DEMO - NOT A REAL BILL OR RECEIPT", warning_style)]],
        colWidths=[7.26 * inch],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff0f3")),
        ("BOX", (0, 0), (-1, -1), 1.2, red),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([banner, Spacer(1, 0.13 * inch)])

    header = Table([
        [Paragraph("PAYPROOF", ParagraphStyle(
            "Brand", parent=title_style, fontSize=12, leading=14,
            textColor=cyan, spaceAfter=0,
        )), Paragraph(str(record["document_type"]).replace("_", " ").upper(), meta_style)],
        [Paragraph("Employee expense paperwork", title_style),
         Paragraph(money(str(record["amount"]), str(record["currency"])), amount_style)],
        [Paragraph(f"Document {record_id}", meta_style),
         Paragraph(str(record["date"]), ParagraphStyle(
             "Date", parent=meta_style, alignment=TA_RIGHT,
         ))],
    ], colWidths=[4.55 * inch, 2.71 * inch])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.extend([header, Spacer(1, 0.1 * inch), HRFlowable(color=cyan, thickness=2), Spacer(1, 0.13 * inch)])

    fields = [
        ("Employee", record["employee"]),
        ("Department", record["department"]),
        ("Office", record["office"]),
        ("Merchant", record["merchant"]),
        ("Category", record["category"]),
        ("Business purpose", record["purpose"]),
        ("Receipt status", str(record["receipt_status"]).replace("_", " ").title()),
        ("Approval status", str(record["approval_status"]).replace("_", " ").title()),
    ]
    cells = []
    for label, value in fields:
        cells.append([
            Paragraph(str(label).upper(), label_style),
            Paragraph(str(value), value_style),
        ])
    details = Table(cells, colWidths=[1.55 * inch, 5.71 * inch])
    details.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), pale),
        ("GRID", (0, 0), (-1, -1), 0.5, light_gray),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([details, Spacer(1, 0.14 * inch)])

    signal_rows = [[Paragraph(review_label.upper(), ParagraphStyle(
        "RiskHeader", parent=warning_style, textColor=accent,
    ))]]
    for signal in signals:
        signal_rows.append([Paragraph(f"- {signal}", note_style)])
    signal_rows.append([Paragraph(
        "These signals are reasons to review, not proof of fraud. PayProof never "
        "approves, rejects, or accuses a person automatically.",
        ParagraphStyle("Guardrail", parent=note_style, fontName="Helvetica-Bold"),
    )])
    signal_box = Table(signal_rows, colWidths=[7.26 * inch])
    signal_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffaf0") if is_attention else pale),
        ("BOX", (0, 0), (-1, -1), 1.2, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([signal_box, Spacer(1, 0.14 * inch)])

    signoff = Table([
        [Paragraph("EMPLOYEE ATTESTATION", label_style), Paragraph("MANAGER REVIEW", label_style)],
        [Paragraph("Name/signature: ________________________", note_style),
         Paragraph("Decision/signature: ____________________", note_style)],
        [Paragraph("Date: _________________________________", note_style),
         Paragraph("Date: _________________________________", note_style)],
    ], colWidths=[3.63 * inch, 3.63 * inch])
    signoff.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, light_gray),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, light_gray),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([signoff, Spacer(1, 0.1 * inch), Paragraph(
        "Fictional names, merchants, amounts, and review scenarios created only to demonstrate PayProof. "
        f"Machine-readable source: data/demo_intake/{record_id}.json",
        footer_style,
    )])
    doc.build(story)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_files = sorted(SOURCE_DIR.glob("EXP-*.json"))
    if len(source_files) != 8:
        raise SystemExit(f"Expected exactly 8 demo intake records, found {len(source_files)}")
    for source_path in source_files:
        record = json.loads(source_path.read_text(encoding="utf-8"))
        build_pdf(record, OUTPUT_DIR / f"{record['id']}-synthetic.pdf")
    print(f"Built {len(source_files)} synthetic PDFs in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
