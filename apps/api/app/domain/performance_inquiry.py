"""Deterministic inquiry-draft text for a `PerformanceFlag` (spec 17.3,
template `performance-inquiry-copy-v1`).

This is P2-C-5's eventual home, but P2-C-3's confirm/correct write needs one
draft per flag in the same transaction (`PerformanceReportRevision.flags`
must pair 1:1 with `.inquiry_drafts`), so the minimum needed to satisfy that
is implemented now. No AI, no formatting beyond the fixed templates below.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import PerformanceFlagType
from app.schemas.performance import PerformanceFlag

TEMPLATE_VERSION = "performance-inquiry-copy-v1"


def render_inquiry_draft_text(
    *,
    flag: PerformanceFlag,
    current_period: str,
    previous_period: str | None = None,
) -> str:
    if flag.flag_type == PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL:
        return (
            f"{current_period} 리포트의 게시물 수는 {flag.actual_content_count}건으로 "
            f"기록되어 있습니다. 계약 원문에서 확인한 월 {flag.expected_content_count}건과 "
            "차이가 있어 해당 월 게시 수와 집계 기준을 확인 부탁드립니다."
        )
    if flag.flag_type == PerformanceFlagType.ENGAGEMENT_RATE_DROP:
        if (
            previous_period is None
            or flag.previous_engagement_rate is None
            or flag.current_engagement_rate is None
        ):
            raise ValueError("반응률 하락 문의 문안에는 두 달의 기간과 반응률이 필요합니다.")
        return (
            f"{previous_period} 반응률 {_format_percent(flag.previous_engagement_rate)}%에서 "
            f"{current_period} {_format_percent(flag.current_engagement_rate)}%로 낮아진 것으로 "
            "계산됩니다. 두 달 리포트의 집계 기준과 변동 사유를 확인 부탁드립니다."
        )
    if flag.issue_note is None:
        raise ValueError("소상공인 이상 신고 문의 문안에는 issue_note가 필요합니다.")
    return (
        f"{current_period} 리포트와 관련해 다음 내용을 확인하고 싶습니다: "
        f"{flag.issue_note} 관련 수치와 집계 기준을 확인 부탁드립니다."
    )


def _format_percent(rate: Decimal) -> str:
    percent = (rate * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{percent:.2f}"
