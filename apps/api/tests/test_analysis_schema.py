from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.enums import (
    AnalysisStatus,
    DetectionMethod,
    ExtractedField,
    ExtractedValueType,
    ReviewSeverity,
    ReviewSignalType,
    VerificationStatus,
)
from app.core.errors import ErrorCode
from app.schemas.analysis import AnalysisTask, ExtractedTerm, ReviewItem


def test_accepts_verified_term_with_evidence() -> None:
    term = ExtractedTerm(
        field=ExtractedField.CONTRACT_TOTAL_AMOUNT,
        value_type=ExtractedValueType.MONEY_KRW,
        value=6_000_000,
        source_page=2,
        source_text="총 계약금액은 금 육백만원으로 한다.",
        confidence=0.96,
        verification_status=VerificationStatus.VERIFIED,
    )

    assert term.source_page == 2


def test_accepts_not_found_term_without_evidence() -> None:
    term = ExtractedTerm(
        field=ExtractedField.REFUND_CONDITION,
        value_type=ExtractedValueType.TEXT,
        value=None,
        source_page=None,
        source_text=None,
        confidence=0.74,
        verification_status=VerificationStatus.NOT_FOUND,
    )

    assert term.source_text is None


@pytest.mark.parametrize(
    ("source_page", "source_text", "status"),
    [
        (None, None, VerificationStatus.VERIFIED),
        (1, "환불 조항", VerificationStatus.NOT_FOUND),
        (1, None, VerificationStatus.NEEDS_CHECK),
    ],
)
def test_rejects_inconsistent_evidence(source_page, source_text, status) -> None:
    with pytest.raises(ValidationError):
        ExtractedTerm(
            field=ExtractedField.REFUND_CONDITION,
            value_type=ExtractedValueType.TEXT,
            value=None,
            source_page=source_page,
            source_text=source_text,
            confidence=0.7,
            verification_status=status,
        )


def test_review_item_keeps_evidence() -> None:
    item = ReviewItem(
        type=ReviewSignalType.MISMATCH,
        severity=ReviewSeverity.IMPORTANT,
        detection_method=DetectionMethod.MODEL,
        plain_explanation="이해한 기간과 계약서의 기간이 다릅니다.",
        source_page=1,
        source_text="계약 기간은 5년으로 한다.",
        source_confidence=0.96,
        model_confidence=0.92,
        verification_status=VerificationStatus.VERIFIED,
        suggestion_accept="원안을 유지합니다.",
        suggestion_compromise="기간을 2년으로 조정하는 방안을 제안드립니다.",
        suggestion_request="기간을 1년으로 조정해 주시길 요청드립니다.",
    )

    assert item.source_text == "계약 기간은 5년으로 한다."
    assert item.source_confidence == 0.96


@pytest.mark.parametrize(
    ("field", "value_type", "value"),
    [
        (ExtractedField.CONTRACT_TOTAL_AMOUNT, ExtractedValueType.MONEY_KRW, -1),
        (ExtractedField.CONTRACT_START_DATE, ExtractedValueType.DATE, "2026-02-30"),
        (ExtractedField.AUTO_RENEWAL, ExtractedValueType.BOOLEAN, "POSSIBLE"),
        (ExtractedField.TERMINATION_PENALTY_RATE, ExtractedValueType.PERCENT, 101),
    ],
)
def test_rejects_invalid_structured_values(field, value_type, value) -> None:
    with pytest.raises(ValidationError):
        ExtractedTerm(
            field=field,
            value_type=value_type,
            value=value,
            source_page=1,
            source_text="계약 조건",
            confidence=0.8,
            verification_status=VerificationStatus.VERIFIED,
        )


def test_deterministic_review_does_not_fake_model_confidence() -> None:
    item = ReviewItem(
        type=ReviewSignalType.MISMATCH,
        severity=ReviewSeverity.IMPORTANT,
        detection_method=DetectionMethod.DETERMINISTIC,
        model_confidence=None,
        plain_explanation="계산한 총액이 입력한 총액과 다릅니다.",
        source_page=1,
        source_text="월 10만원을 12개월 납부한다.",
        source_confidence=0.88,
        verification_status=VerificationStatus.VERIFIED,
        suggestion_accept="원안을 유지합니다.",
        suggestion_compromise="금액 확인을 요청합니다.",
        suggestion_request="총액을 명시해 주시길 요청드립니다.",
    )

    assert item.model_confidence is None


@pytest.mark.parametrize(
    ("source_page", "source_text", "source_confidence", "status"),
    [
        (1, "계약 조건", None, VerificationStatus.VERIFIED),
        (None, None, 0.8, VerificationStatus.NOT_FOUND),
        (None, None, None, VerificationStatus.NEEDS_CHECK),
    ],
)
def test_review_item_rejects_inconsistent_source_confidence(
    source_page, source_text, source_confidence, status
) -> None:
    with pytest.raises(ValidationError):
        ReviewItem(
            type=ReviewSignalType.MISMATCH,
            severity=ReviewSeverity.CHECK,
            detection_method=DetectionMethod.DETERMINISTIC,
            model_confidence=None,
            plain_explanation="추가 확인이 필요합니다.",
            source_page=source_page,
            source_text=source_text,
            source_confidence=source_confidence,
            verification_status=status,
            suggestion_accept="원안을 유지합니다.",
            suggestion_compromise="조건 확인을 제안합니다.",
            suggestion_request="조건을 명시해 주시길 요청드립니다.",
        )


def test_performance_guarantee_is_extracted_as_text() -> None:
    term = ExtractedTerm(
        field=ExtractedField.PERFORMANCE_GUARANTEE,
        value_type=ExtractedValueType.TEXT,
        value="월 방문자 수를 보장하지 않는다.",
        source_page=3,
        source_text="성과는 보장하지 않는다.",
        confidence=0.88,
        verification_status=VerificationStatus.VERIFIED,
    )

    assert term.value_type == ExtractedValueType.TEXT


def test_analysis_task_rejects_inconsistent_status_payload() -> None:
    with pytest.raises(ValidationError):
        AnalysisTask(
            id=uuid4(),
            contract_id=uuid4(),
            document_id=uuid4(),
            status=AnalysisStatus.FAILED,
            attempt_count=1,
            error_code=ErrorCode.ANALYSIS_START_FAILED,
            result=None,
            created_at="2026-07-29T00:00:00Z",
            updated_at="2026-07-29T00:00:00Z",
        )
