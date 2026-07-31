from uuid import UUID, uuid4

from app.adapters.solar import SolarReviewAdapter
from app.core.enums import (
    DetectionMethod,
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
    ReviewSeverity,
    ReviewSignalType,
    VerificationStatus,
)
from app.schemas.analysis import EXPECTED_VALUE_TYPES, ExtractedTerm
from app.services.analysis import (
    _apply_solar_review_content,
    _build_review_items,
    _build_solar_review_inputs,
)

CONTRACT_ID = UUID("20000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-4000-8000-000000000002")


def make_term(
    *,
    field: ExtractedField,
    value,
    status: VerificationStatus,
    source_text: str | None = None,
) -> ExtractedTerm:
    has_evidence = source_text is not None
    return ExtractedTerm(
        id=uuid4(),
        contract_id=CONTRACT_ID,
        document_id=DOCUMENT_ID,
        source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
        field=field,
        value_type=EXPECTED_VALUE_TYPES.get(field, ExtractedValueType.TEXT),
        value=value,
        source_page=1 if has_evidence else None,
        source_text=source_text,
        confidence=0.93 if has_evidence else 0,
        verification_status=status,
    )


async def test_solar_enriches_p0_signals_without_changing_source_evidence() -> None:
    reporting = make_term(
        field=ExtractedField.REPORTING_FREQUENCY,
        value="상황에 따라 변경",
        status=VerificationStatus.VERIFIED,
        source_text="성과 보고 일정은 상황에 따라 변경한다.",
    )
    one_sided_liability = make_term(
        field=ExtractedField.FACILITY_DAMAGE_LIABILITY,
        value="책임 범위는 별도 협의하며 광고주가 일체의 책임을 진다.",
        status=VerificationStatus.NEEDS_CHECK,
        source_text=(
            "촬영 중 시설 파손의 책임 범위는 별도 협의하며 "
            "광고주가 일체의 책임을 진다."
        ),
    )
    missing_quantity = make_term(
        field=ExtractedField.CONTENT_QUANTITY,
        value=None,
        status=VerificationStatus.NOT_FOUND,
    )
    missing_safety = make_term(
        field=ExtractedField.SHOOTING_SAFETY,
        value=None,
        status=VerificationStatus.NOT_FOUND,
    )
    terms = [reporting, one_sided_liability, missing_quantity, missing_safety]

    candidates = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=terms,
        understood=None,
    )

    reporting_review = next(
        item
        for item in candidates
        if reporting.id in item.related_extracted_term_ids
    )
    liability_reviews = [
        item
        for item in candidates
        if one_sided_liability.id in item.related_extracted_term_ids
    ]
    liability_review = next(
        item
        for item in liability_reviews
        if item.type == ReviewSignalType.NEEDS_CHECK
    )
    quantity_review = next(
        item
        for item in candidates
        if missing_quantity.id in item.related_extracted_term_ids
    )
    safety_review = next(
        item
        for item in candidates
        if missing_safety.id in item.related_extracted_term_ids
    )
    assert reporting_review.type == ReviewSignalType.UNCLEAR
    assert reporting_review.source_text == reporting.source_text
    assert {item.type for item in liability_reviews} == {
        ReviewSignalType.UNCLEAR,
        ReviewSignalType.NEEDS_CHECK,
    }
    assert liability_review.type == ReviewSignalType.NEEDS_CHECK
    assert liability_review.severity == ReviewSeverity.IMPORTANT
    assert quantity_review.type == ReviewSignalType.MISSING
    assert quantity_review.severity == ReviewSeverity.IMPORTANT
    assert safety_review.type == ReviewSignalType.MISSING
    assert safety_review.source_document_id is None

    solar_inputs = _build_solar_review_inputs(
        reviews=candidates,
        terms=terms,
        understood=None,
        contract=None,
    )
    outputs = await SolarReviewAdapter(
        mode="mock",
        api_key="",
        base_url="https://api.upstage.ai",
    ).generate_review_content(items=solar_inputs)
    merged = _apply_solar_review_content(reviews=candidates, outputs=outputs)

    merged_reporting = next(
        item for item in merged if reporting.id in item.related_extracted_term_ids
    )
    merged_safety = next(
        item for item in merged if missing_safety.id in item.related_extracted_term_ids
    )
    assert all(item.detection_method == DetectionMethod.HYBRID for item in merged)
    assert all(item.model_confidence is not None for item in merged)
    assert all(
        "비보정 자기평가" in (item.model_limitations or "")
        for item in merged
    )
    assert merged_reporting.source_document_id == reporting.document_id
    assert merged_reporting.source_page == reporting.source_page
    assert merged_reporting.source_text == reporting.source_text
    assert merged_reporting.source_confidence == reporting.confidence
    assert merged_safety.source_document_id is None
    assert "보고 의무" in merged_reporting.suggestion_request
    assert "촬영 안전" in merged_safety.suggestion_request
