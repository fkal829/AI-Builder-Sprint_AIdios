"""P2-C-5: `performance-inquiry-copy-v1` deterministic template rendering.

The production code (`app/domain/performance_inquiry.py`) already exists —
P2-C-3's confirm/correct write needed it to pair one inquiry draft with every
flag in the same transaction. This file is the dedicated, exact-match
verification the spec (17.3) asks for: the literal template wording, the
percent/rounding format, and the "missing data raises" boundary — none of
which the C-3/C-4 test suites pin down precisely (they only check substrings).
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.enums import (
    ExtractedField,
    ExtractedSourceType,
    PerformanceFlagType,
    VerificationStatus,
)
from app.domain.performance_inquiry import TEMPLATE_VERSION, render_inquiry_draft_text
from app.schemas.performance import (
    PerformanceFlag,
    PerformanceFlagBasisSnapshot,
    PerformanceInquiryDraft,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)


def _basis_snapshot(*, extracted_term_id, field: ExtractedField) -> PerformanceFlagBasisSnapshot:
    return PerformanceFlagBasisSnapshot(
        extracted_term_id=extracted_term_id,
        document_id=uuid4(),
        field=field,
        source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
        source_page=2,
        source_text="계약 원문 발췌",
        confidence=0.95,
        verification_status=VerificationStatus.VERIFIED,
    )


def make_shortfall_flag(*, expected: int, actual: int) -> PerformanceFlag:
    quantity_id, frequency_id = uuid4(), uuid4()
    return PerformanceFlag(
        id=uuid4(),
        report_revision_id=uuid4(),
        flag_type=PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL,
        basis_extracted_term_ids=[quantity_id, frequency_id],
        basis_snapshots=[
            _basis_snapshot(extracted_term_id=quantity_id, field=ExtractedField.CONTENT_QUANTITY),
            _basis_snapshot(extracted_term_id=frequency_id, field=ExtractedField.POSTING_FREQUENCY),
        ],
        comparison_report_revision_id=None,
        expected_content_count=expected,
        expected_period_unit="MONTH",
        actual_content_count=actual,
        previous_engagement_rate=None,
        current_engagement_rate=None,
        issue_note=None,
        created_at=NOW,
    )


def make_drop_flag(*, previous_rate: Decimal, current_rate: Decimal) -> PerformanceFlag:
    return PerformanceFlag(
        id=uuid4(),
        report_revision_id=uuid4(),
        flag_type=PerformanceFlagType.ENGAGEMENT_RATE_DROP,
        basis_extracted_term_ids=[],
        basis_snapshots=[],
        comparison_report_revision_id=uuid4(),
        expected_content_count=None,
        expected_period_unit=None,
        actual_content_count=None,
        previous_engagement_rate=previous_rate,
        current_engagement_rate=current_rate,
        issue_note=None,
        created_at=NOW,
    )


def make_owner_issue_flag(*, issue_note: str) -> PerformanceFlag:
    return PerformanceFlag(
        id=uuid4(),
        report_revision_id=uuid4(),
        flag_type=PerformanceFlagType.OWNER_REPORTED_ISSUE,
        basis_extracted_term_ids=[],
        basis_snapshots=[],
        comparison_report_revision_id=None,
        expected_content_count=None,
        expected_period_unit=None,
        actual_content_count=None,
        previous_engagement_rate=None,
        current_engagement_rate=None,
        issue_note=issue_note,
        created_at=NOW,
    )


def test_deliverable_count_shortfall_template_is_an_exact_match() -> None:
    flag = make_shortfall_flag(expected=4, actual=3)

    text = render_inquiry_draft_text(flag=flag, current_period="2026-07")

    assert text == (
        "2026-07 리포트의 게시물 수는 3건으로 기록되어 있습니다. 계약 원문에서 확인한 월 4건과 "
        "차이가 있어 해당 월 게시 수와 집계 기준을 확인 부탁드립니다."
    )


def test_engagement_rate_drop_template_is_an_exact_match() -> None:
    flag = make_drop_flag(
        previous_rate=Decimal("0.040000"),
        current_rate=Decimal("0.030000"),
    )

    text = render_inquiry_draft_text(
        flag=flag, current_period="2026-08", previous_period="2026-07"
    )

    assert text == (
        "2026-07 반응률 4.00%에서 2026-08 3.00%로 낮아진 것으로 계산됩니다. "
        "두 달 리포트의 집계 기준과 변동 사유를 확인 부탁드립니다."
    )


def test_owner_reported_issue_template_is_an_exact_match() -> None:
    flag = make_owner_issue_flag(issue_note="숫자가 이상해 보여요")

    text = render_inquiry_draft_text(flag=flag, current_period="2026-07")

    assert text == (
        "2026-07 리포트와 관련해 다음 내용을 확인하고 싶습니다: 숫자가 이상해 보여요 "
        "관련 수치와 집계 기준을 확인 부탁드립니다."
    )


@pytest.mark.parametrize(
    ("rate", "expected_percent"),
    [
        # Exact tie: ROUND_HALF_UP breaks 2.9950 up to 3.00, not down to 2.99.
        (Decimal("0.029950"), "3.00"),
        (Decimal("0.029949"), "2.99"),
        (Decimal("0.100000"), "10.00"),
        (Decimal("0.000100"), "0.01"),
    ],
)
def test_engagement_rate_percent_formatting_and_rounding_boundary(
    rate: Decimal, expected_percent: str
) -> None:
    # Pair the rate under test with a distinctly higher previous rate so the
    # flag's own "current < previous" invariant holds regardless of which
    # side is being exercised.
    flag = make_drop_flag(previous_rate=Decimal("0.500000"), current_rate=rate)

    text = render_inquiry_draft_text(
        flag=flag, current_period="2026-08", previous_period="2026-07"
    )

    assert f"{expected_percent}%" in text


def test_engagement_rate_drop_requires_previous_period() -> None:
    flag = make_drop_flag(
        previous_rate=Decimal("0.040000"),
        current_rate=Decimal("0.030000"),
    )

    with pytest.raises(ValueError, match="두 달의 기간과 반응률"):
        render_inquiry_draft_text(flag=flag, current_period="2026-08")


def test_owner_reported_issue_requires_issue_note_on_the_flag() -> None:
    # The schema itself won't let an OWNER_REPORTED_ISSUE flag exist without
    # issue_note, so this exercises the renderer's own defensive check by
    # constructing a flag through model_construct to bypass that validator.
    flag = PerformanceFlag.model_construct(
        id=uuid4(),
        report_revision_id=uuid4(),
        flag_type=PerformanceFlagType.OWNER_REPORTED_ISSUE,
        basis_extracted_term_ids=[],
        basis_snapshots=[],
        comparison_report_revision_id=None,
        expected_content_count=None,
        expected_period_unit=None,
        actual_content_count=None,
        previous_engagement_rate=None,
        current_engagement_rate=None,
        issue_note=None,
        created_at=NOW,
    )

    with pytest.raises(ValueError, match="issue_note가 필요합니다"):
        render_inquiry_draft_text(flag=flag, current_period="2026-07")


def test_rendered_text_fits_the_stored_snapshot_schema() -> None:
    flag = make_shortfall_flag(expected=12, actual=4)
    text = render_inquiry_draft_text(flag=flag, current_period="2026-07")

    draft = PerformanceInquiryDraft(
        id=uuid4(),
        flag_id=flag.id,
        text=text,
        template_version=TEMPLATE_VERSION,
        created_at=NOW,
    )

    assert draft.template_version == "performance-inquiry-copy-v1"
    assert 1 <= len(draft.text) <= 1000
