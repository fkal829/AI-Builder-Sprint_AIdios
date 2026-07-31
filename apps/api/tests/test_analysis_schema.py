from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.enums import (
    AnalysisStatus,
    DetectionMethod,
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
    ReviewBasisType,
    ReviewSeverity,
    ReviewSignalType,
    VerificationStatus,
)
from app.core.errors import ErrorCode
from app.schemas.analysis import (
    Analysis,
    AnalysisStartRequest,
    AnalysisTask,
    ExtractedTerm,
    ExtractedTermCandidate,
    ReviewItem,
)

CONTRACT_ID = uuid4()
DOCUMENT_ID = uuid4()
TERM_ID = uuid4()


def make_review_item(**overrides) -> ReviewItem:
    evidence_values = (
        overrides.get("source_page"),
        overrides.get("source_text"),
        overrides.get("source_confidence"),
    )
    values = {
        "id": uuid4(),
        "contract_id": CONTRACT_ID,
        "basis_type": ReviewBasisType.INTERNAL_RULE,
        "basis_text": "계약 원문과 사용자 이해조건 비교",
        "basis_citation": None,
        "related_extracted_term_ids": [TERM_ID],
        "source_document_id": DOCUMENT_ID if any(v is not None for v in evidence_values) else None,
    }
    values.update(overrides)
    return ReviewItem(**values)


def test_accepts_verified_term_with_evidence() -> None:
    term = ExtractedTermCandidate(
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
    term = ExtractedTermCandidate(
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
        ExtractedTermCandidate(
            field=ExtractedField.REFUND_CONDITION,
            value_type=ExtractedValueType.TEXT,
            value=None,
            source_page=source_page,
            source_text=source_text,
            confidence=0.7,
            verification_status=status,
        )


def test_review_item_keeps_evidence() -> None:
    item = make_review_item(
        type=ReviewSignalType.MISMATCH,
        severity=ReviewSeverity.IMPORTANT,
        detection_method=DetectionMethod.MODEL,
        plain_explanation="이해한 기간과 계약서의 기간이 다릅니다.",
        source_page=1,
        source_text="계약 기간은 5년으로 한다.",
        source_confidence=0.96,
        model_confidence=0.92,
        model_limitations="계약 원문 표현은 사용자가 직접 확인해야 합니다.",
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
        ExtractedTermCandidate(
            field=field,
            value_type=value_type,
            value=value,
            source_page=1,
            source_text="계약 조건",
            confidence=0.8,
            verification_status=VerificationStatus.VERIFIED,
        )


def test_deterministic_review_does_not_fake_model_confidence() -> None:
    item = make_review_item(
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
        make_review_item(
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
    term = ExtractedTermCandidate(
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
            supporting_document_ids=[],
            status=AnalysisStatus.FAILED,
            attempt_count=1,
            error_code=ErrorCode.ANALYSIS_START_FAILED,
            result=None,
            created_at="2026-07-29T00:00:00Z",
            updated_at="2026-07-29T00:00:00Z",
        )


def test_persisted_extracted_term_keeps_document_and_source_type() -> None:
    term = ExtractedTerm(
        id=TERM_ID,
        contract_id=CONTRACT_ID,
        document_id=DOCUMENT_ID,
        source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
        field=ExtractedField.CONTRACT_TOTAL_AMOUNT,
        value_type=ExtractedValueType.MONEY_KRW,
        value=6_000_000,
        source_page=2,
        source_text="총 계약금액은 금 육백만원으로 한다.",
        confidence=0.96,
        verification_status=VerificationStatus.VERIFIED,
    )

    assert term.document_id == DOCUMENT_ID
    assert term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT


def make_persisted_term() -> ExtractedTerm:
    return ExtractedTerm(
        id=TERM_ID,
        contract_id=CONTRACT_ID,
        document_id=DOCUMENT_ID,
        source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
        field=ExtractedField.CONTRACT_TOTAL_AMOUNT,
        value_type=ExtractedValueType.MONEY_KRW,
        value=6_000_000,
        source_page=2,
        source_text="총 계약금액은 금 육백만원으로 한다.",
        confidence=0.96,
        verification_status=VerificationStatus.VERIFIED,
    )


def make_linked_review(**overrides) -> ReviewItem:
    values = {
        "type": ReviewSignalType.MISMATCH,
        "severity": ReviewSeverity.IMPORTANT,
        "detection_method": DetectionMethod.DETERMINISTIC,
        "model_confidence": None,
        "model_limitations": None,
        "plain_explanation": "이해한 총액과 계약서의 총액이 다릅니다.",
        "source_page": 2,
        "source_text": "총 계약금액은 금 육백만원으로 한다.",
        "source_confidence": 0.96,
        "verification_status": VerificationStatus.VERIFIED,
        "suggestion_accept": "원안을 유지합니다.",
        "suggestion_compromise": "금액을 다시 확인하는 방안을 제안합니다.",
        "suggestion_request": "총액을 명확히 기재해 주시길 요청드립니다.",
    }
    values.update(overrides)
    return make_review_item(**values)


def test_analysis_accepts_review_evidence_linked_to_its_extracted_term() -> None:
    result = Analysis(
        contract_id=CONTRACT_ID,
        extracted_terms=[make_persisted_term()],
        review_items=[make_linked_review()],
    )

    assert result.review_items[0].related_extracted_term_ids == [TERM_ID]


def test_analysis_rejects_related_term_outside_its_result() -> None:
    with pytest.raises(ValidationError, match="같은 분석 결과의 추출값"):
        Analysis(
            contract_id=CONTRACT_ID,
            extracted_terms=[make_persisted_term()],
            review_items=[
                make_linked_review(
                    related_extracted_term_ids=[uuid4()],
                )
            ],
        )


def make_completed_task(*, result: Analysis, **overrides) -> AnalysisTask:
    values = {
        "id": uuid4(),
        "contract_id": CONTRACT_ID,
        "document_id": DOCUMENT_ID,
        "supporting_document_ids": [],
        "status": AnalysisStatus.COMPLETED,
        "attempt_count": 1,
        "error_code": None,
        "result": result,
        "created_at": "2026-07-29T00:00:00Z",
        "updated_at": "2026-07-29T00:00:00Z",
    }
    values.update(overrides)
    return AnalysisTask(**values)


def test_completed_task_rejects_result_from_another_contract() -> None:
    other_contract_id = uuid4()
    result = Analysis(
        contract_id=other_contract_id,
        extracted_terms=[],
        review_items=[],
    )

    with pytest.raises(ValidationError, match="작업과 같은 계약"):
        make_completed_task(result=result)


def test_completed_task_rejects_contract_term_from_another_document() -> None:
    term = make_persisted_term().model_copy(update={"document_id": uuid4()})
    result = Analysis(
        contract_id=CONTRACT_ID,
        extracted_terms=[term],
        review_items=[],
    )

    with pytest.raises(ValidationError, match="주 문서"):
        make_completed_task(result=result)


def test_completed_task_requires_documented_term_in_supporting_documents() -> None:
    supporting_document_id = uuid4()
    term = make_persisted_term().model_copy(
        update={
            "document_id": supporting_document_id,
            "source_type": ExtractedSourceType.DOCUMENTED_EXPLANATION,
        }
    )
    result = Analysis(
        contract_id=CONTRACT_ID,
        extracted_terms=[term],
        review_items=[],
    )

    with pytest.raises(ValidationError, match="선택 문서"):
        make_completed_task(result=result)

    task = make_completed_task(
        result=result,
        supporting_document_ids=[supporting_document_id],
    )
    assert task.result == result


def test_analysis_rejects_source_fields_that_do_not_match_related_term() -> None:
    with pytest.raises(ValidationError, match="연결된 계약 추출값과 일치"):
        Analysis(
            contract_id=CONTRACT_ID,
            extracted_terms=[make_persisted_term()],
            review_items=[
                make_linked_review(
                    source_text="실제 관련 추출값과 다른 원문",
                )
            ],
        )


def test_analysis_start_requires_unique_supporting_documents() -> None:
    supporting = uuid4()
    with pytest.raises(ValidationError):
        AnalysisStartRequest(
            document_id=DOCUMENT_ID,
            supporting_document_ids=[supporting, supporting],
        )
