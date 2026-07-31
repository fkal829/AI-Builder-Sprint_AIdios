"""Render a confirmed agreement into the PDF supplied to Modusign.

The PDF is created in memory only.  It is not written to local disk, storage, or logs.
"""

from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.schemas.agreements import Agreement

_FONT_NAME = "AgreementKorean"
_FALLBACK_FONT = "Helvetica"
_WINDOWS_KOREAN_FONT = Path(r"C:\Windows\Fonts\malgun.ttf")


class AgreementPdfRenderer:
    """Create a readable agreement PDF without retaining its contents."""

    def __init__(self, *, font_path: str = "") -> None:
        self._font_path = Path(font_path) if font_path else None

    def render(self, agreement: Agreement) -> bytes:
        buffer = BytesIO()
        canvas = Canvas(buffer, pagesize=A4, pageCompression=1)
        font_name = self._register_font()
        width, height = A4
        left = 18 * mm
        right = width - 18 * mm
        y = height - 20 * mm

        def line(text: str, *, size: float = 10, gap: float = 5) -> None:
            nonlocal y
            for wrapped in _wrap_text(text, font_name=font_name, size=size, width=right - left):
                if y < 22 * mm:
                    canvas.showPage()
                    y = height - 20 * mm
                canvas.setFont(font_name, size)
                canvas.drawString(left, y, wrapped)
                y -= size + gap

        line(agreement.title, size=16, gap=10)
        line(f"Version: {agreement.version}", size=9)
        line(f"Original contract: {agreement.original_contract.title}")
        line(f"Original signed date: {agreement.original_contract.signed_date.isoformat()}")
        line("Agreement summary", size=12, gap=7)
        for label, value in (
            ("Term and payment", agreement.condition_summary.term_and_payment),
            ("Deliverables and reporting", agreement.condition_summary.deliverables_and_reporting),
            ("Termination and renewal", agreement.condition_summary.termination_and_renewal),
            (
                "Rights, safety and liability",
                agreement.condition_summary.rights_safety_and_liability,
            ),
        ):
            line(f"{label}: {value}")
        line("Agreed adjustments", size=12, gap=7)
        for index, clause in enumerate(agreement.clauses, start=1):
            line(f"{index}. [{clause.category}] {clause.outcome}")
            line(f"Before: {clause.before}")
            line(f"After: {clause.after}")
            if clause.reason:
                line(f"Reason: {clause.reason}")
        line(agreement.unchanged_terms_policy)
        line("Signature fields are placed by the requester in Modusign.", size=9)
        canvas.save()
        return buffer.getvalue()

    def _register_font(self) -> str:
        if _FONT_NAME in pdfmetrics.getRegisteredFontNames():
            return _FONT_NAME
        candidates = [path for path in (self._font_path, _WINDOWS_KOREAN_FONT) if path]
        for path in candidates:
            if path.is_file():
                pdfmetrics.registerFont(TTFont(_FONT_NAME, str(path)))
                return _FONT_NAME
        return _FALLBACK_FONT


def _wrap_text(text: str, *, font_name: str, size: float, width: float) -> list[str]:
    words = text.replace("\n", " ").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and pdfmetrics.stringWidth(candidate, font_name, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
