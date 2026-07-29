import pytest
from pydantic import ValidationError

from app.core.enums import ReviewSeverity, ReviewSignalType, VerificationStatus
from app.schemas.analysis import ExtractedTerm, ReviewItem


def test_accepts_verified_term_with_evidence() -> None:
    term = ExtractedTerm(
        field="contract_total_amount",
        value=6_000_000,
        source_page=2,
        source_text="총 계약금액은 금 육백만원으로 한다.",
        confidence=0.96,
        verification_status=VerificationStatus.VERIFIED,
    )

    assert term.source_page == 2


def test_accepts_not_found_term_without_evidence() -> None:
    term = ExtractedTerm(
        field="refund",
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
            field="refund",
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
        plain_explanation="이해한 기간과 계약서의 기간이 다릅니다.",
        source_page=1,
        source_text="계약 기간은 5년으로 한다.",
        confidence=0.92,
        verification_status=VerificationStatus.VERIFIED,
        suggestion_accept="원안을 유지합니다.",
        suggestion_compromise="기간을 2년으로 조정하는 방안을 제안드립니다.",
        suggestion_request="기간을 1년으로 조정해 주시길 요청드립니다.",
    )

    assert item.source_text == "계약 기간은 5년으로 한다."
