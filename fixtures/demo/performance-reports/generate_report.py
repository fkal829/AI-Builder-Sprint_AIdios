"""Generate a polished fictional agency social-media report PDF."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FIXTURE_DIR = Path(__file__).resolve().parent
EXPECTED_PATH = FIXTURE_DIR / "expected-extraction.json"
ASSET_DIR = FIXTURE_DIR / "assets"

PAGE_WIDTH = 960
PAGE_HEIGHT = 540
PAGE_SIZE = (PAGE_WIDTH, PAGE_HEIGHT)
MARGIN = 48

NAVY = HexColor("#173B57")
NAVY_DARK = HexColor("#0F2A3D")
TEAL = HexColor("#19A89D")
TEAL_DARK = HexColor("#118178")
PEACH = HexColor("#FFB36B")
CORAL = HexColor("#F27B70")
BLUE = HexColor("#4D7FF0")
INK = HexColor("#111827")
MUTED = HexColor("#667085")
LINE = HexColor("#E4E7EC")
SURFACE = HexColor("#F5F7FA")
SURFACE_BLUE = HexColor("#EAF2F6")
SURFACE_TEAL = HexColor("#E9F7F5")
SHADOW = HexColor("#DDE3E9")

REGULAR_FONT_CANDIDATES = (
    Path("/mnt/c/Windows/Fonts/malgun.ttf"),
    Path("/mnt/c/Windows/Fonts/NanumBarunGothic.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)
BOLD_FONT_CANDIDATES = (
    Path("/mnt/c/Windows/Fonts/malgunbd.ttf"),
    Path("/mnt/c/Windows/Fonts/NanumBarunGothic_0.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
)


def _first_existing_path(env_name: str, candidates: tuple[Path, ...]) -> Path:
    configured = os.environ.get(env_name)
    paths = (Path(configured), *candidates) if configured else candidates
    for path in paths:
        if path.is_file():
            return path
    searched = ", ".join(str(path) for path in paths)
    raise FileNotFoundError(f"Korean font not found. Set {env_name}. Searched: {searched}")


def _register_fonts() -> tuple[str, str]:
    regular_path = _first_existing_path("DANDI_KOREAN_FONT_REGULAR", REGULAR_FONT_CANDIDATES)
    bold_path = _first_existing_path("DANDI_KOREAN_FONT_BOLD", BOLD_FONT_CANDIDATES)
    pdfmetrics.registerFont(TTFont("DandiRegular", str(regular_path)))
    pdfmetrics.registerFont(TTFont("DandiBold", str(bold_path)))
    return "DandiRegular", "DandiBold"


def _load_fixture() -> dict[str, Any]:
    with EXPECTED_PATH.open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _draw_card(
    canvas: Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    fill: Color = white,
    radius: float = 14,
    shadow: bool = True,
) -> None:
    if shadow:
        canvas.setFillColor(SHADOW)
        canvas.roundRect(x, y - 3, width, height, radius, stroke=0, fill=1)
    canvas.setFillColor(fill)
    canvas.roundRect(x, y, width, height, radius, stroke=0, fill=1)


def _draw_pill(
    canvas: Canvas,
    regular_font: str,
    *,
    x: float,
    y: float,
    text: str,
    fill: Color,
    text_color: Color,
    width: float | None = None,
) -> float:
    pill_width = width or pdfmetrics.stringWidth(text, regular_font, 8) + 22
    canvas.setFillColor(fill)
    canvas.roundRect(x, y, pill_width, 22, 11, stroke=0, fill=1)
    canvas.setFillColor(text_color)
    canvas.setFont(regular_font, 8)
    canvas.drawCentredString(x + pill_width / 2, y + 7, text)
    return pill_width


def _draw_wrapped_text(
    canvas: Canvas,
    text: str,
    *,
    x: float,
    y: float,
    max_width: float,
    font: str,
    size: float,
    color: Color,
    leading: float,
    max_lines: int | None = None,
) -> float:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and pdfmetrics.stringWidth(candidate, font, size) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if max_lines is not None:
        lines = lines[:max_lines]
    canvas.setFillColor(color)
    canvas.setFont(font, size)
    for index, line in enumerate(lines):
        canvas.drawString(x, y - index * leading, line)
    return y - len(lines) * leading


def _draw_image_cover(
    canvas: Canvas,
    image_path: Path,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float = 16,
) -> None:
    image = ImageReader(str(image_path))
    image_width, image_height = image.getSize()
    scale = max(width / image_width, height / image_height)
    draw_width = image_width * scale
    draw_height = image_height * scale
    draw_x = x + (width - draw_width) / 2
    draw_y = y + (height - draw_height) / 2

    canvas.saveState()
    path = canvas.beginPath()
    path.roundRect(x, y, width, height, radius)
    canvas.clipPath(path, stroke=0, fill=0)
    canvas.drawImage(
        image,
        draw_x,
        draw_y,
        width=draw_width,
        height=draw_height,
        preserveAspectRatio=True,
        mask="auto",
    )
    canvas.restoreState()


def _draw_chrome(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    *,
    page_number: int,
    section: str,
) -> None:
    canvas.setFillColor(NAVY)
    canvas.setFont(bold_font, 8)
    canvas.drawString(MARGIN, PAGE_HEIGHT - 31, "BRIDGEWAVE / MONTHLY SOCIAL REPORT")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 8)
    canvas.drawRightString(PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 31, section.upper())
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.7)
    canvas.line(MARGIN, 31, PAGE_WIDTH - MARGIN, 31)
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 7.5)
    canvas.drawString(MARGIN, 16, "파도담 카페 · 2026.07 · DEMO / FICTIONAL DATA")
    canvas.drawRightString(PAGE_WIDTH - MARGIN, 16, f"{page_number:02d} / 06")


def _draw_cover(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    terrace_image: Path,
    drink_image: Path,
) -> None:
    canvas.setFillColor(NAVY_DARK)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)

    canvas.setFillColor(TEAL)
    canvas.circle(98, 468, 4, stroke=0, fill=1)
    canvas.setFillColor(white)
    canvas.setFont(bold_font, 9)
    canvas.drawString(112, 464, "BRIDGEWAVE / CLIENT REPORT")

    _draw_pill(
        canvas,
        regular_font,
        x=64,
        y=393,
        text="DEMO · FICTIONAL DATA",
        fill=Color(1, 1, 1, alpha=0.12),
        text_color=white,
        width=146,
    )
    canvas.setFillColor(white)
    canvas.setFont(bold_font, 34)
    canvas.drawString(64, 334, "MONTHLY")
    canvas.drawString(64, 291, "SOCIAL REPORT")
    canvas.setFillColor(TEAL)
    canvas.rect(64, 265, 72, 4, stroke=0, fill=1)

    canvas.setFillColor(white)
    canvas.setFont(bold_font, 21)
    canvas.drawString(64, 211, "파도담 카페")
    canvas.setFillColor(HexColor("#B9C8D2"))
    canvas.setFont(regular_font, 12)
    canvas.drawString(64, 184, "Instagram organic performance")
    canvas.setFont(bold_font, 16)
    canvas.drawString(64, 139, "2026.07")
    canvas.setFont(regular_font, 9)
    canvas.drawString(64, 113, "Reporting period  2026.07.01 — 2026.07.31")
    canvas.drawString(64, 93, "Prepared by  BRIDGEWAVE")

    _draw_image_cover(
        canvas,
        terrace_image,
        x=518,
        y=0,
        width=442,
        height=540,
        radius=0,
    )
    canvas.saveState()
    canvas.setFillColor(NAVY_DARK)
    canvas.setFillAlpha(0.38)
    canvas.rect(518, 0, 442, 540, stroke=0, fill=1)
    canvas.restoreState()

    canvas.setFillColor(white)
    canvas.roundRect(671, 122, 220, 292, 22, stroke=0, fill=1)
    _draw_image_cover(canvas, drink_image, x=687, y=186, width=188, height=206, radius=14)
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 10)
    canvas.drawString(687, 163, "여름 신메뉴 자몽에이드")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 8)
    canvas.drawString(687, 145, "REELS · 07.08 · FICTIONAL POST")

    canvas.setFillColor(white)
    canvas.setFont(regular_font, 7.5)
    canvas.drawString(64, 30, "CONFIDENTIAL · FOR CLIENT REVIEW")
    canvas.drawRightString(896, 30, "01 / 06")
    canvas.showPage()


def _draw_kpi_card(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    eyebrow: str,
    source_text: str,
    delta: str,
    dark: bool,
) -> None:
    fill = NAVY if dark else white
    _draw_card(canvas, x=x, y=y, width=width, height=height, fill=fill)
    primary = white if dark else INK
    secondary = HexColor("#C8D6DF") if dark else MUTED
    accent = TEAL if dark else TEAL_DARK
    canvas.setFillColor(secondary)
    canvas.setFont(regular_font, 7.5)
    canvas.drawString(x + 16, y + height - 23, eyebrow)
    canvas.setFillColor(primary)
    font_size = 16 if len(source_text) >= 14 else 18
    canvas.setFont(bold_font, font_size)
    canvas.drawString(x + 16, y + 48, source_text)
    canvas.setFillColor(accent)
    canvas.setFont(bold_font, 8)
    canvas.drawString(x + 16, y + 20, delta)


def _draw_snapshot(
    canvas: Canvas,
    fixture: dict[str, Any],
    regular_font: str,
    bold_font: str,
) -> None:
    canvas.setFillColor(SURFACE)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    _draw_chrome(canvas, regular_font, bold_font, page_number=2, section="Executive snapshot")

    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 25)
    canvas.drawString(MARGIN, 457, "2026년 7월 성과 요약")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 9)
    canvas.drawString(MARGIN, 434, "플랫폼 월간 인사이트를 기준으로 정리한 대행사 보고 총계입니다.")
    _draw_pill(
        canvas,
        regular_font,
        x=748,
        y=441,
        text="INSTAGRAM · ORGANIC",
        fill=SURFACE_TEAL,
        text_color=TEAL_DARK,
        width=164,
    )

    metric_order = (
        "impressions",
        "likes",
        "comments",
        "reach",
        "saves",
        "shares",
        "follower_net_change",
        "published_content_count",
    )
    eyebrows = (
        "AWARENESS",
        "INTERACTION",
        "INTERACTION",
        "AWARENESS",
        "INTENT SIGNAL",
        "AMPLIFICATION",
        "AUDIENCE",
        "DELIVERY",
    )
    deltas = (
        "전월 대비 +12.4%",
        "전월 대비 +8.1%",
        "전월 대비 +5건",
        "전월 대비 +10.8%",
        "전월 대비 +14.3%",
        "변동 없음",
        "전월 대비 +9명",
        "운영 보고 2건",
    )
    card_width = 204
    card_height = 130
    x_gap = 16
    row_gap = 16
    start_y = 271
    for index, field_name in enumerate(metric_order):
        metric = fixture["expected_extraction"][field_name]
        row = index // 4
        column = index % 4
        _draw_kpi_card(
            canvas,
            regular_font,
            bold_font,
            x=MARGIN + column * (card_width + x_gap),
            y=start_y - row * (card_height + row_gap),
            width=card_width,
            height=card_height,
            eyebrow=eyebrows[index],
            source_text=metric["source_text"],
            delta=deltas[index],
            dark=index in {0, 3, 7},
        )

    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 9)
    canvas.drawString(MARGIN, 80, "월간 반응 240회")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 8.5)
    canvas.drawString(144, 80, "좋아요 + 댓글 + 저장 + 공유")
    canvas.setFillColor(TEAL_DARK)
    canvas.setFont(bold_font, 9)
    canvas.drawRightString(PAGE_WIDTH - MARGIN, 80, "반응률 2.89% · 단디계약 서버 계산값")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 7)
    canvas.drawRightString(PAGE_WIDTH - MARGIN, 61, "240 ÷ 8,300 = 0.028916")
    canvas.showPage()


def _draw_horizontal_bar(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    *,
    x: float,
    y: float,
    label: str,
    value: int,
    percent: float,
    max_width: float,
    color: Color,
) -> None:
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 9)
    canvas.drawString(x, y + 23, label)
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 8)
    canvas.drawRightString(x + max_width, y + 23, f"{value:,}회 · {percent:.1f}%")
    canvas.setFillColor(LINE)
    canvas.roundRect(x, y, max_width, 12, 6, stroke=0, fill=1)
    canvas.setFillColor(color)
    canvas.roundRect(x, y, max_width * percent / 100, 12, 6, stroke=0, fill=1)


def _draw_donut(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    *,
    center_x: float,
    center_y: float,
) -> None:
    values = (180, 20, 40)
    colors = (TEAL, PEACH, BLUE)
    total = sum(values)
    start = 90.0
    for value, color in zip(values, colors, strict=True):
        extent = 360 * value / total
        canvas.setFillColor(color)
        canvas.wedge(
            center_x - 66,
            center_y - 66,
            center_x + 66,
            center_y + 66,
            start,
            -extent,
            stroke=0,
            fill=1,
        )
        start -= extent
    canvas.setFillColor(white)
    canvas.circle(center_x, center_y, 40, stroke=0, fill=1)
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 20)
    canvas.drawCentredString(center_x, center_y + 2, "240")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 8)
    canvas.drawCentredString(center_x, center_y - 17, "TOTAL INTERACTIONS")


def _draw_breakdown(canvas: Canvas, regular_font: str, bold_font: str) -> None:
    canvas.setFillColor(white)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    _draw_chrome(canvas, regular_font, bold_font, page_number=3, section="Performance breakdown")

    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 25)
    canvas.drawString(MARGIN, 457, "성과 구성")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 9)
    canvas.drawString(MARGIN, 434, "게시물별 노출 기여와 월간 반응 구성을 함께 확인합니다.")

    _draw_card(canvas, x=48, y=116, width=516, height=284, fill=SURFACE, shadow=False)
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 13)
    canvas.drawString(72, 365, "콘텐츠별 노출 기여")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 8)
    canvas.drawString(72, 345, "월간 노출 8,300회를 게시물별로 분해")
    _draw_horizontal_bar(
        canvas,
        regular_font,
        bold_font,
        x=72,
        y=278,
        label="릴스 · 여름 신메뉴 자몽에이드",
        value=5100,
        percent=61.4,
        max_width=442,
        color=TEAL,
    )
    _draw_horizontal_bar(
        canvas,
        regular_font,
        bold_font,
        x=72,
        y=207,
        label="피드 · 테라스 리뉴얼 안내",
        value=3200,
        percent=38.6,
        max_width=442,
        color=NAVY,
    )
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 8)
    canvas.drawString(72, 153, "릴스 콘텐츠가 전체 노출의 61.4%를 차지했습니다.")
    canvas.drawString(72, 135, "게시 시점·형식·노출 정책 등이 함께 영향을 줄 수 있습니다.")

    _draw_card(canvas, x=586, y=116, width=326, height=284, fill=SURFACE, shadow=False)
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 13)
    canvas.drawString(610, 365, "반응 구성")
    _draw_donut(canvas, regular_font, bold_font, center_x=699, center_y=257)
    legend = (
        ("좋아요", "180", TEAL),
        ("댓글", "20", PEACH),
        ("저장", "40", BLUE),
        ("공유", "0", MUTED),
    )
    for index, (label, value, color) in enumerate(legend):
        y = 309 - index * 38
        x = 798
        canvas.setFillColor(color)
        canvas.circle(x, y, 4, stroke=0, fill=1)
        canvas.setFillColor(MUTED)
        canvas.setFont(regular_font, 8)
        canvas.drawString(x + 11, y - 3, label)
        canvas.setFillColor(INK)
        canvas.setFont(bold_font, 9)
        canvas.drawRightString(882, y - 3, value)

    strip = (
        ("보고 게시물", "2건"),
        ("월간 도달", "6,740명"),
        ("팔로워 순증", "+27명"),
    )
    strip_width = 276
    for index, (label, value) in enumerate(strip):
        x = MARGIN + index * (strip_width + 18)
        canvas.setFillColor(NAVY if index == 0 else SURFACE_BLUE)
        canvas.roundRect(x, 55, strip_width, 43, 11, stroke=0, fill=1)
        canvas.setFillColor(white if index == 0 else MUTED)
        canvas.setFont(regular_font, 8)
        canvas.drawString(x + 15, 72, label)
        canvas.setFillColor(white if index == 0 else INK)
        canvas.setFont(bold_font, 12)
        canvas.drawRightString(x + strip_width - 15, 69, value)
    canvas.showPage()


def _draw_content_card(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    *,
    x: float,
    image_path: Path,
    content_type: str,
    date: str,
    title: str,
    insight: str,
    metrics: tuple[tuple[str, str], ...],
) -> None:
    _draw_card(canvas, x=x, y=102, width=414, height=314, fill=white)
    _draw_image_cover(canvas, image_path, x=x + 16, y=118, width=174, height=282, radius=12)
    _draw_pill(
        canvas,
        regular_font,
        x=x + 207,
        y=366,
        text=f"{content_type} · {date}",
        fill=SURFACE_TEAL,
        text_color=TEAL_DARK,
        width=154,
    )
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 14)
    canvas.drawString(x + 207, 336, title)
    _draw_wrapped_text(
        canvas,
        insight,
        x=x + 207,
        y=311,
        max_width=184,
        font=regular_font,
        size=8,
        color=MUTED,
        leading=14,
        max_lines=3,
    )
    canvas.setStrokeColor(LINE)
    canvas.line(x + 207, 258, x + 390, 258)
    for index, (label, value) in enumerate(metrics):
        row = index // 2
        column = index % 2
        metric_x = x + 207 + column * 95
        metric_y = 224 - row * 57
        canvas.setFillColor(MUTED)
        canvas.setFont(regular_font, 7.5)
        canvas.drawString(metric_x, metric_y + 15, label)
        canvas.setFillColor(INK)
        canvas.setFont(bold_font, 12)
        canvas.drawString(metric_x, metric_y - 2, value)


def _draw_content_performance(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    drink_image: Path,
    terrace_image: Path,
) -> None:
    canvas.setFillColor(SURFACE)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    _draw_chrome(canvas, regular_font, bold_font, page_number=4, section="Content performance")
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 25)
    canvas.drawString(MARGIN, 457, "콘텐츠별 성과")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 9)
    canvas.drawString(MARGIN, 434, "7월에 게시된 2개 콘텐츠의 플랫폼 보고값입니다.")

    _draw_content_card(
        canvas,
        regular_font,
        bold_font,
        x=48,
        image_path=drink_image,
        content_type="REELS",
        date="07.08",
        title="여름 신메뉴 자몽에이드",
        insight="선명한 제품 중심 비주얼로 월간 노출의 61.4%를 기록했습니다.",
        metrics=(("노출", "5,100"), ("좋아요", "128"), ("댓글", "14"), ("저장", "31")),
    )
    _draw_content_card(
        canvas,
        regular_font,
        bold_font,
        x=498,
        image_path=terrace_image,
        content_type="FEED",
        date="07.19",
        title="테라스 리뉴얼 안내",
        insight="공간 변화와 이용 장면을 전달한 안내형 피드 콘텐츠입니다.",
        metrics=(("노출", "3,200"), ("좋아요", "52"), ("댓글", "6"), ("저장", "9")),
    )

    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 7.5)
    canvas.drawString(MARGIN, 72, "※ 공유는 두 콘텐츠 모두 0회로 보고되었습니다.")
    canvas.drawRightString(
        PAGE_WIDTH - MARGIN,
        72,
        "도달과 팔로워 순증은 플랫폼 월간 집계이므로 게시물별로 합산하지 않습니다.",
    )
    canvas.showPage()


def _draw_note_column(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    *,
    x: float,
    number: str,
    title: str,
    subtitle: str,
    bullets: tuple[str, ...],
    accent: Color,
) -> None:
    _draw_card(canvas, x=x, y=103, width=276, height=306, fill=white)
    canvas.setFillColor(accent)
    canvas.circle(x + 31, 375, 16, stroke=0, fill=1)
    canvas.setFillColor(white)
    canvas.setFont(bold_font, 9)
    canvas.drawCentredString(x + 31, 372, number)
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 14)
    canvas.drawString(x + 56, 378, title)
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 7.5)
    canvas.drawString(x + 56, 359, subtitle)
    canvas.setStrokeColor(LINE)
    canvas.line(x + 24, 337, x + 252, 337)

    cursor_y = 307
    for bullet in bullets:
        canvas.setFillColor(accent)
        canvas.circle(x + 30, cursor_y + 2, 3, stroke=0, fill=1)
        cursor_y = _draw_wrapped_text(
            canvas,
            bullet,
            x=x + 43,
            y=cursor_y + 6,
            max_width=203,
            font=regular_font,
            size=8.5,
            color=INK,
            leading=15,
            max_lines=3,
        ) - 16


def _draw_agency_notes(canvas: Canvas, regular_font: str, bold_font: str) -> None:
    canvas.setFillColor(SURFACE)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    _draw_chrome(canvas, regular_font, bold_font, page_number=5, section="Agency notes")
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 25)
    canvas.drawString(MARGIN, 457, "운영 메모와 다음 달 제안")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 9)
    canvas.drawString(MARGIN, 434, "수치에서 확인되는 사실과 실행 제안을 구분해 정리했습니다.")

    _draw_note_column(
        canvas,
        regular_font,
        bold_font,
        x=48,
        number="01",
        title="이번 달 운영",
        subtitle="WHAT WE DELIVERED",
        bullets=(
            "7월 중 릴스 1건과 피드 1건, 총 2건이 게시된 것으로 보고되었습니다.",
            "신메뉴 소개와 공간 안내 두 가지 주제로 콘텐츠를 운영했습니다.",
            "모든 수치는 대행사가 플랫폼 인사이트에서 확인해 옮긴 값입니다.",
        ),
        accent=NAVY,
    )
    _draw_note_column(
        canvas,
        regular_font,
        bold_font,
        x=342,
        number="02",
        title="확인된 점",
        subtitle="OBSERVATIONS",
        bullets=(
            "신메뉴 릴스가 전체 노출의 61.4%를 차지했습니다.",
            "저장은 총 40회이며 이 중 릴스에서 31회가 발생했습니다.",
            "게시 시점·형식·계절성·플랫폼 정책 등 여러 요인이 함께 영향을 줄 수 있습니다.",
        ),
        accent=TEAL,
    )
    _draw_note_column(
        canvas,
        regular_font,
        bold_font,
        x=636,
        number="03",
        title="다음 달 제안",
        subtitle="NEXT ACTIONS",
        bullets=(
            "다음 월 게시 일정과 콘텐츠 수량을 운영 캘린더에서 먼저 확인합니다.",
            "제품 중심 릴스와 공간형 피드를 각각 유지해 형식별 반응을 비교합니다.",
            "문의·예약·구매 수는 소상공인이 직접 확인한 값만 별도로 기록합니다.",
        ),
        accent=PEACH,
    )
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 7.5)
    canvas.drawString(MARGIN, 72, "위 내용은 성과 판정이나 매출 원인 분석이 아닌 대행사 운영 메모입니다.")
    canvas.showPage()


def _draw_definition(
    canvas: Canvas,
    regular_font: str,
    bold_font: str,
    *,
    x: float,
    y: float,
    term: str,
    description: str,
) -> None:
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 8.5)
    canvas.drawString(x, y, term)
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 7.5)
    canvas.drawString(x + 82, y, description)


def _draw_data_notes(canvas: Canvas, regular_font: str, bold_font: str) -> None:
    canvas.setFillColor(white)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    _draw_chrome(canvas, regular_font, bold_font, page_number=6, section="Data notes")
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 25)
    canvas.drawString(MARGIN, 457, "데이터 기준과 고지")
    canvas.setFillColor(MUTED)
    canvas.setFont(regular_font, 9)
    canvas.drawString(MARGIN, 434, "리포트 수치의 범위와 단디계약 기록 원칙입니다.")

    _draw_card(canvas, x=48, y=101, width=420, height=307, fill=SURFACE, shadow=False)
    canvas.setFillColor(INK)
    canvas.setFont(bold_font, 13)
    canvas.drawString(72, 374, "REPORT SCOPE")
    scope_rows = (
        ("보고 기간", "2026-07-01 — 2026-07-31"),
        ("플랫폼", "Instagram · Organic"),
        ("작성 기준", "플랫폼 인사이트에 표시된 대행사 보고값"),
        ("작성일", "2026-07-31"),
    )
    for index, (label, value) in enumerate(scope_rows):
        y = 342 - index * 28
        canvas.setFillColor(MUTED)
        canvas.setFont(regular_font, 8)
        canvas.drawString(72, y, label)
        canvas.setFillColor(INK)
        canvas.setFont(bold_font, 8.5)
        canvas.drawString(154, y, value)
    canvas.setStrokeColor(LINE)
    canvas.line(72, 227, 444, 227)
    definitions = (
        ("노출(조회)", "콘텐츠가 화면에 표시·재생된 횟수"),
        ("도달", "콘텐츠를 한 번 이상 본 고유 계정 수"),
        ("반응", "좋아요·댓글·저장·공유의 합계"),
        ("팔로워 순증", "기간 중 증가한 팔로워의 순변화"),
        ("게시물 수", "기간 중 게시 완료로 보고된 콘텐츠 수"),
    )
    for index, (term, description) in enumerate(definitions):
        _draw_definition(
            canvas,
            regular_font,
            bold_font,
            x=72,
            y=201 - index * 22,
            term=term,
            description=description,
        )

    _draw_card(canvas, x=492, y=101, width=420, height=307, fill=NAVY, shadow=False)
    _draw_pill(
        canvas,
        regular_font,
        x=518,
        y=359,
        text="IMPORTANT",
        fill=TEAL,
        text_color=white,
        width=92,
    )
    canvas.setFillColor(white)
    canvas.setFont(bold_font, 15)
    canvas.drawString(518, 324, "가상 데이터 및 확인 원칙")
    notice_lines = (
        "이 문서의 업체명·콘텐츠·이미지·수치는 모두 시연용 가상 데이터입니다.",
        "단디계약은 광고 성과를 자체 측정하거나 좋고 나쁨을 판정하지 않습니다.",
        "대행사가 보고한 값을 소상공인이 확인한 뒤 확정값으로 기록합니다.",
        "전환율·CPA·ROAS·매출 기여도는 이 리포트에 포함하지 않습니다.",
        "사용자가 확인하기 전 AI 추출값은 확정 데이터가 아닙니다.",
    )
    cursor_y = 287
    for line in notice_lines:
        canvas.setFillColor(TEAL)
        canvas.circle(522, cursor_y + 3, 3, stroke=0, fill=1)
        cursor_y = _draw_wrapped_text(
            canvas,
            line,
            x=535,
            y=cursor_y + 7,
            max_width=345,
            font=regular_font,
            size=8.5,
            color=white,
            leading=15,
            max_lines=2,
        ) - 12
    canvas.showPage()


def generate_pdf(output_path: Path) -> None:
    fixture = _load_fixture()
    regular_font, bold_font = _register_fonts()
    drink_image = ASSET_DIR / "grapefruit-ade.png"
    terrace_image = ASSET_DIR / "terrace-renewal.png"
    for asset in (drink_image, terrace_image):
        if not asset.is_file():
            raise FileNotFoundError(f"Report asset is missing: {asset}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(
        str(output_path),
        pagesize=PAGE_SIZE,
        invariant=1,
        pageCompression=1,
    )
    canvas.setTitle("브릿지웨이브 2026년 7월 소셜 미디어 월간 리포트 - 가상 샘플")
    canvas.setAuthor("주식회사 브릿지웨이브 - 가상 대행사")
    canvas.setSubject("광고효과 리포트 업로드 및 지표 추출 검증용 가상 데이터")
    _draw_cover(canvas, regular_font, bold_font, terrace_image, drink_image)
    _draw_snapshot(canvas, fixture, regular_font, bold_font)
    _draw_breakdown(canvas, regular_font, bold_font)
    _draw_content_performance(canvas, regular_font, bold_font, drink_image, terrace_image)
    _draw_agency_notes(canvas, regular_font, bold_font)
    _draw_data_notes(canvas, regular_font, bold_font)
    canvas.save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=FIXTURE_DIR / "브릿지웨이브_7월_광고리포트.pdf",
        help="Output PDF path",
    )
    args = parser.parse_args()
    generate_pdf(args.output.resolve())
    print(args.output.resolve())


if __name__ == "__main__":
    main()
