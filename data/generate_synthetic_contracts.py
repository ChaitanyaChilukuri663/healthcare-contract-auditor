"""Generate synthetic provider-agreement PDFs for the Healthcare Contract Auditor demo.

Standalone: depends only on reportlab (already in the project venv). Writes three
single-page PDFs into data/contracts/:

  - contract_provider_a.pdf  Provider A, COMPLIANT
  - contract_provider_b.pdf  Provider B, NON-COMPLIANT
  - amendment_provider_a.pdf Amendment to Provider A (later timely-filing window)

The clauses contain explicit terms so downstream extraction has concrete values
to find. None of this is a real contract.

Run with:
  & "$env:LOCALAPPDATA\\Programs\\Python\\Python313\\Scripts\\uv.exe" run \\
      --directory "C:\\RAG" python data\\generate_synthetic_contracts.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUTPUT_DIR = Path(__file__).resolve().parent / "contracts"

BANNER = "SYNTHETIC SAMPLE — NOT A REAL CONTRACT"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "banner": ParagraphStyle(
            "banner",
            parent=base["Title"],
            fontSize=13,
            textColor="#B00020",
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "title": ParagraphStyle(
            "doc_title",
            parent=base["Heading1"],
            fontSize=15,
            spaceAfter=10,
        ),
        "heading": ParagraphStyle(
            "clause_heading",
            parent=base["Heading2"],
            fontSize=11,
            spaceBefore=8,
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontSize=10,
            leading=14,
            spaceAfter=6,
        ),
    }


def _build(path: Path, blocks: list[tuple[str, str]]) -> None:
    """Render a one-page PDF. Each block is (style_name, text)."""
    styles = _styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        leftMargin=1.0 * inch,
        rightMargin=1.0 * inch,
        title=path.stem,
    )
    flow = [Paragraph(BANNER, styles["banner"])]
    for style_name, text in blocks:
        flow.append(Paragraph(text, styles[style_name]))
        if style_name == "title":
            flow.append(Spacer(1, 4))
    doc.build(flow)


def contract_provider_a() -> list[tuple[str, str]]:
    return [
        ("title", "Provider Participation Agreement"),
        (
            "body",
            "This Provider Participation Agreement (the &ldquo;Agreement&rdquo;) is entered "
            "into by and between the Payer and the Provider identified below.",
        ),
        ("heading", "1. Parties and Identifiers"),
        (
            "body",
            "Provider NPI: 1234567890<br/>"
            "Contract ID: C-TX-001<br/>"
            "State: TX<br/>"
            "Line of Business: Medicare<br/>"
            "Effective Date: January 1, 2023",
        ),
        ("heading", "2. Timely Filing"),
        (
            "body",
            "Claims must be submitted within 90 days of the date of service. Claims "
            "received after this window may be denied for untimely filing.",
        ),
        ("heading", "3. Reimbursement"),
        (
            "body",
            "Covered services are reimbursed at 100% of the Medicare Physician Fee "
            "Schedule. Physical therapy (CPT 97110, 97530) reimbursed at 100% of Medicare.",
        ),
        ("heading", "4. Lesser-of Provision"),
        (
            "body",
            "Reimbursement shall be the lesser of billed charges or the applicable fee "
            "schedule amount.",
        ),
    ]


def contract_provider_b() -> list[tuple[str, str]]:
    return [
        ("title", "Provider Participation Agreement"),
        (
            "body",
            "This Provider Participation Agreement (the &ldquo;Agreement&rdquo;) is entered "
            "into by and between the Payer and the Provider identified below.",
        ),
        ("heading", "1. Parties and Identifiers"),
        (
            "body",
            "Provider NPI: 1987654321<br/>"
            "Contract ID: C-NY-001<br/>"
            "State: NY<br/>"
            "Line of Business: Medicaid<br/>"
            "Effective Date: March 1, 2022",
        ),
        ("heading", "2. Timely Filing"),
        (
            "body",
            "Claims must be submitted within 180 days of the date of service. Claims "
            "received after this window may be denied for untimely filing.",
        ),
        ("heading", "3. Reimbursement"),
        (
            "body",
            "Speech therapy (CPT 92507) reimbursed at 130% of Medicare.",
        ),
    ]


def amendment_provider_a() -> list[tuple[str, str]]:
    return [
        ("title", "Amendment to Provider Participation Agreement"),
        (
            "body",
            "Amendment to Agreement C-TX-001 for Provider NPI 1234567890, effective "
            "January 1, 2024.",
        ),
        ("heading", "1. Recitals"),
        (
            "body",
            "The parties previously entered into the Provider Participation Agreement "
            "identified as Contract ID C-TX-001 with an original Effective Date of "
            "January 1, 2023. The parties now wish to amend the timely-filing terms.",
        ),
        ("heading", "2. Amended Timely-Filing Window"),
        (
            "body",
            "Effective January 1, 2024, the timely filing window is amended to 120 days. "
            "All other terms of the Agreement remain in full force and effect.",
        ),
    ]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    documents = {
        "contract_provider_a.pdf": contract_provider_a(),
        "contract_provider_b.pdf": contract_provider_b(),
        "amendment_provider_a.pdf": amendment_provider_a(),
    }
    for filename, blocks in documents.items():
        path = OUTPUT_DIR / filename
        _build(path, blocks)
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
