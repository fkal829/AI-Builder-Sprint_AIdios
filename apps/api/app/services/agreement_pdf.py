"""Render a confirmed agreement into its immutable private-PDF artifact.

Callers create the bytes in memory and store them only through the private Storage adapter.
This renderer never writes to disk or logs agreement contents.
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
        # ``invariant`` prevents timestamps/random identifiers in the PDF trailer so the
        # stored artifact is reproducible from the same confirmed agreement data.
        canvas = Canvas(buffer, pagesize=A4, pageCompression=1, invariant=1)
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
        line(f"버전: {agreement.version}", size=9)
        line(f"원계약 제목: {agreement.original_contract.title}")
        line(f"원계약 체결일: {agreement.original_contract.signed_date.isoformat()}")
        line(f"원계약 문서 ID: {agreement.original_contract.document_id}", size=8)
        line("계약 조건 요약", size=12, gap=7)
        for label, value in (
            ("계약기간·총액·결제", agreement.condition_summary.term_and_payment),
            ("산출물·채널·보고", agreement.condition_summary.deliverables_and_reporting),
            ("해지·환불·자동갱신", agreement.condition_summary.termination_and_renewal),
            (
                "권리·안전·책임",
                agreement.condition_summary.rights_safety_and_liability,
            ),
        ):
            line(f"{label}: {value}")
        line("확정된 조정 조항", size=12, gap=7)
        for index, clause in enumerate(agreement.clauses, start=1):
            line(f"{index}. [{clause.category}] {clause.outcome}")
            line(f"변경 전: {clause.before}")
            line(f"변경 후: {clause.after}")
            if clause.reason:
                line(f"사유: {clause.reason}")
        line(agreement.unchanged_terms_policy)
        line("서명란은 모두싸인 편집기에서 요청자가 직접 배치합니다.", size=9)
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
