from uuid import UUID, uuid4

from app.core.enums import (
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
    ReviewSeverity,
    ReviewSignalType,
    VerificationStatus,
)
from app.domain.obligations import build_representative_obligation
from app.schemas.analysis import EXPECTED_VALUE_TYPES, ExtractedTerm
from app.services.analysis import _build_review_items

CONTRACT_ID = UUID("30000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("30000000-0000-4000-8000-000000000002")
EVIDENCE = "인스타그램 SNS 홍보 콘텐츠 4건을 2026년 8월 20일까지 제작한다."


def make_term(
    *,
    field: ExtractedField,
    value,
    source_text: str = EVIDENCE,
    confidence: float = 0.9,
    status: VerificationStatus = VerificationStatus.VERIFIED,
    document_id: UUID = DOCUMENT_ID,
    source_type: ExtractedSourceType = ExtractedSourceType.CONTRACT_DOCUMENT,
) -> ExtractedTerm:
    return ExtractedTerm(
        id=uuid4(),
        contract_id=CONTRACT_ID,
        document_id=document_id,
        source_type=source_type,
        field=field,
        value_type=EXPECTED_VALUE_TYPES.get(field, ExtractedValueType.TEXT),
        value=value,
        source_page=2,
        source_text=source_text,
        confidence=confidence,
        verification_status=status,
    )


def representative_terms() -> list[ExtractedTerm]:
    return [
        make_term(
            field=ExtractedField.ADVERTISING_CHANNEL,
            value="인스타그램",
            confidence=0.95,
        ),
        make_term(
            field=ExtractedField.CONTENT_TYPE,
            value="SNS 홍보 콘텐츠",
            confidence=0.93,
        ),
        make_term(
            field=ExtractedField.CONTENT_QUANTITY,
            value=4,
            confidence=0.88,
        ),
        make_term(
            field=ExtractedField.DELIVERABLE_DUE_DATE,
            value="2026-08-20",
            confidence=0.91,
        ),
    ]


def test_builds_deterministic_representative_obligation_from_one_excerpt() -> None:
    terms = list(reversed(representative_terms()))
    terms.append(
        make_term(
            field=ExtractedField.DELIVERABLE_DUE_DATE,
            value="2026-09-01",
            source_text="제안서상 별도 기한",
            document_id=uuid4(),
            source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
        )
    )

    draft = build_representative_obligation(
        contract_id=CONTRACT_ID,
        terms=terms,
    )

    assert draft is not None
    assert draft.title == "인스타그램 SNS 홍보 콘텐츠 4건"
    assert draft.due_date.isoformat() == "2026-08-20"
    assert draft.source_document_id == DOCUMENT_ID
    assert draft.source_page == 2
    assert draft.source_text == EVIDENCE
    assert draft.confidence == 0.88


def test_does_not_create_obligation_from_different_source_excerpts() -> None:
    terms = representative_terms()
    for index, term in enumerate(terms):
        terms[index] = term.model_copy(update={"source_text": f"서로 다른 산출물 근거 {index}"})

    draft = build_representative_obligation(
        contract_id=CONTRACT_ID,
        terms=terms,
    )

    assert draft is None


def test_requires_all_four_representative_fields() -> None:
    terms = representative_terms()

    for missing_field in (
        ExtractedField.ADVERTISING_CHANNEL,
        ExtractedField.CONTENT_TYPE,
        ExtractedField.CONTENT_QUANTITY,
        ExtractedField.DELIVERABLE_DUE_DATE,
    ):
        draft = build_representative_obligation(
            contract_id=CONTRACT_ID,
            terms=[term for term in terms if term.field != missing_field],
        )

        assert draft is None


def test_requires_every_representative_field_to_be_verified() -> None:
    terms = representative_terms()

    for unverified_field in (
        ExtractedField.ADVERTISING_CHANNEL,
        ExtractedField.CONTENT_TYPE,
        ExtractedField.CONTENT_QUANTITY,
        ExtractedField.DELIVERABLE_DUE_DATE,
    ):
        changed = [
            (
                term.model_copy(update={"verification_status": VerificationStatus.NEEDS_CHECK})
                if term.field == unverified_field
                else term
            )
            for term in terms
        ]

        draft = build_representative_obligation(
            contract_id=CONTRACT_ID,
            terms=changed,
        )

        assert draft is None


def test_rejects_ambiguous_duplicate_representative_field() -> None:
    terms = representative_terms()
    terms.append(
        make_term(
            field=ExtractedField.CONTENT_TYPE,
            value="릴스",
        )
    )

    draft = build_representative_obligation(
        contract_id=CONTRACT_ID,
        terms=terms,
    )

    assert draft is None


def test_keeps_confirmation_signal_when_verified_terms_are_not_coherent() -> None:
    terms = representative_terms()
    for index, term in enumerate(terms):
        terms[index] = term.model_copy(update={"source_text": f"서로 다른 산출물 근거 {index}"})

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=terms,
        understood=None,
    )

    review = next(
        item
        for item in reviews
        if set(item.related_extracted_term_ids) == {term.id for term in terms}
    )
    assert review.type == ReviewSignalType.NEEDS_CHECK
    assert review.severity == ReviewSeverity.IMPORTANT
    assert "하나의 대표 이행 항목으로 확정할 수 없습니다" in review.plain_explanation
    assert review.source_document_id == DOCUMENT_ID


def test_does_not_create_obligation_from_unverified_due_date() -> None:
    terms = representative_terms()
    terms[-1] = make_term(
        field=ExtractedField.DELIVERABLE_DUE_DATE,
        value="2026-08-20",
        status=VerificationStatus.NEEDS_CHECK,
    )

    draft = build_representative_obligation(
        contract_id=CONTRACT_ID,
        terms=terms,
    )

    assert draft is None
