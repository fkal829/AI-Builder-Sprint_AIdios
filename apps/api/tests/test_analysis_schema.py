import pytest
from pydantic import ValidationError

from app.core.enums import (
    DetectionMethod,
    ExtractedField,
    ExtractedValueType,
    ReviewSeverity,
    ReviewSignalType,
    VerificationStatus,
)
from app.schemas.analysis import ExtractedTerm, ReviewItem


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
        model_confidence=0.92,
        verification_status=VerificationStatus.VERIFIED,
        suggestion_accept="원안을 유지합니다.",
        suggestion_compromise="기간을 2년으로 조정하는 방안을 제안드립니다.",
        suggestion_request="기간을 1년으로 조정해 주시길 요청드립니다.",
    )

    assert item.source_text == "계약 기간은 5년으로 한다."


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
        verification_status=VerificationStatus.VERIFIED,
        suggestion_accept="원안을 유지합니다.",
        suggestion_compromise="금액 확인을 요청합니다.",
        suggestion_request="총액을 명시해 주시길 요청드립니다.",
    )

    assert item.model_confidence is None
