from uuid import UUID, uuid4

import pytest

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
from app.schemas.analysis import (
    EXPECTED_VALUE_TYPES,
    ExtractedTerm,
    ExtractedTermCandidate,
)
from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermSourceType
from app.services.analysis import (
    _apply_solar_review_content,
    _build_review_items,
    _build_solar_review_inputs,
    _normalize_renewal_candidates,
    _unresolved_fields,
)

CONTRACT_ID = UUID("20000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
SUPPORT_DOCUMENT_ID = UUID("20000000-0000-4000-8000-000000000003")
SECOND_SUPPORT_DOCUMENT_ID = UUID("20000000-0000-4000-8000-000000000004")


def make_term(
    *,
    field: ExtractedField,
    value,
    status: VerificationStatus,
    source_text: str | None = None,
    document_id: UUID = DOCUMENT_ID,
    source_type: ExtractedSourceType = ExtractedSourceType.CONTRACT_DOCUMENT,
) -> ExtractedTerm:
    has_evidence = source_text is not None
    return ExtractedTerm(
        id=uuid4(),
        contract_id=CONTRACT_ID,
        document_id=document_id,
        source_type=source_type,
        field=field,
        value_type=EXPECTED_VALUE_TYPES.get(field, ExtractedValueType.TEXT),
        value=value,
        source_page=1 if has_evidence else None,
        source_text=source_text,
        confidence=0.93 if has_evidence else 0,
        verification_status=status,
    )


def make_candidate(
    *,
    field: ExtractedField,
    value,
    status: VerificationStatus,
    source_text: str | None,
) -> ExtractedTermCandidate:
    return ExtractedTermCandidate(
        field=field,
        value_type=EXPECTED_VALUE_TYPES.get(field, ExtractedValueType.TEXT),
        value=value,
        source_page=1 if source_text is not None else None,
        source_text=source_text,
        confidence=0.93 if source_text is not None else 0,
        verification_status=status,
    )


def test_not_found_refund_with_understood_condition_creates_only_missing() -> None:
    refund = make_term(
        field=ExtractedField.REFUND_CONDITION,
        value=None,
        status=VerificationStatus.NOT_FOUND,
    )
    understood = UnderstoodTerm(
        contract_id=CONTRACT_ID,
        duration_text="12개월",
        monthly_amount=400_000,
        total_amount=4_800_000,
        refund_text="해지 이후 남은 기간 대금은 환불",
        termination_text="30일 전에 알리면 중도해지 가능",
        source_type=UnderstoodTermSourceType.USER_MEMORY,
    )

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=[refund],
        understood=understood,
    )

    refund_reviews = [
        review for review in reviews if refund.id in review.related_extracted_term_ids
    ]
    assert [review.type for review in refund_reviews] == [ReviewSignalType.MISSING]
    assert all(review.type != ReviewSignalType.MISMATCH for review in reviews)


def test_auto_renewal_yes_deterministically_creates_auto_renewal_type() -> None:
    auto = make_candidate(
        field=ExtractedField.AUTO_RENEWAL,
        value="YES",
        status=VerificationStatus.VERIFIED,
        source_text="계약은 별도 거절이 없으면 자동갱신된다.",
    )
    candidates = {
        ExtractedField.AUTO_RENEWAL: auto,
        ExtractedField.CONTRACT_RENEWAL_TYPE: make_candidate(
            field=ExtractedField.CONTRACT_RENEWAL_TYPE,
            value=None,
            status=VerificationStatus.NOT_FOUND,
            source_text=None,
        ),
    }

    _normalize_renewal_candidates(candidates)

    renewal_type = candidates[ExtractedField.CONTRACT_RENEWAL_TYPE]
    assert renewal_type.value == "AUTO"
    assert renewal_type.verification_status == VerificationStatus.VERIFIED
    assert renewal_type.source_page == auto.source_page
    assert renewal_type.source_text == auto.source_text
    assert renewal_type.confidence == auto.confidence
    assert ExtractedField.CONTRACT_RENEWAL_TYPE not in _unresolved_fields(candidates)


def test_conflicting_verified_renewal_values_remain_needs_check() -> None:
    candidates = {
        ExtractedField.AUTO_RENEWAL: make_candidate(
            field=ExtractedField.AUTO_RENEWAL,
            value="YES",
            status=VerificationStatus.VERIFIED,
            source_text="계약은 자동갱신된다.",
        ),
        ExtractedField.CONTRACT_RENEWAL_TYPE: make_candidate(
            field=ExtractedField.CONTRACT_RENEWAL_TYPE,
            value="MANUAL",
            status=VerificationStatus.VERIFIED,
            source_text="계약 갱신은 당사자 합의로 한다.",
        ),
    }

    _normalize_renewal_candidates(candidates)

    assert all(
        candidate.verification_status == VerificationStatus.NEEDS_CHECK
        for candidate in candidates.values()
    )
    assert {
        ExtractedField.AUTO_RENEWAL,
        ExtractedField.CONTRACT_RENEWAL_TYPE,
    }.issubset(_unresolved_fields(candidates))


def test_uncertain_auto_renewal_yes_derives_uncertain_auto_type() -> None:
    auto = make_candidate(
        field=ExtractedField.AUTO_RENEWAL,
        value="YES",
        status=VerificationStatus.NEEDS_CHECK,
        source_text="별도 의사표시가 없으면 갱신되는 것으로 보인다.",
    )
    candidates = {
        ExtractedField.AUTO_RENEWAL: auto,
        ExtractedField.CONTRACT_RENEWAL_TYPE: make_candidate(
            field=ExtractedField.CONTRACT_RENEWAL_TYPE,
            value=None,
            status=VerificationStatus.NOT_FOUND,
            source_text=None,
        ),
    }

    _normalize_renewal_candidates(candidates)

    renewal_type = candidates[ExtractedField.CONTRACT_RENEWAL_TYPE]
    assert renewal_type.value == "AUTO"
    assert renewal_type.verification_status == VerificationStatus.NEEDS_CHECK
    assert renewal_type.source_text == auto.source_text
    assert ExtractedField.CONTRACT_RENEWAL_TYPE in _unresolved_fields(candidates)


def test_verified_no_and_verified_auto_type_are_both_downgraded() -> None:
    candidates = {
        ExtractedField.AUTO_RENEWAL: make_candidate(
            field=ExtractedField.AUTO_RENEWAL,
            value="NO",
            status=VerificationStatus.VERIFIED,
            source_text="이 계약은 자동으로 갱신되지 않는다.",
        ),
        ExtractedField.CONTRACT_RENEWAL_TYPE: make_candidate(
            field=ExtractedField.CONTRACT_RENEWAL_TYPE,
            value="AUTO",
            status=VerificationStatus.VERIFIED,
            source_text="계약은 매년 자동 연장된다.",
        ),
    }

    _normalize_renewal_candidates(candidates)

    assert all(
        candidate.verification_status == VerificationStatus.NEEDS_CHECK
        for candidate in candidates.values()
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
        source_text=("촬영 중 시설 파손의 책임 범위는 별도 협의하며 광고주가 일체의 책임을 진다."),
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
        item for item in candidates if reporting.id in item.related_extracted_term_ids
    )
    liability_reviews = [
        item for item in candidates if one_sided_liability.id in item.related_extracted_term_ids
    ]
    liability_review = next(
        item for item in liability_reviews if item.type == ReviewSignalType.NEEDS_CHECK
    )
    quantity_review = next(
        item for item in candidates if missing_quantity.id in item.related_extracted_term_ids
    )
    safety_review = next(
        item for item in candidates if missing_safety.id in item.related_extracted_term_ids
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
    assert all("비보정 자기평가" in (item.model_limitations or "") for item in merged)
    assert merged_reporting.source_document_id == reporting.document_id
    assert merged_reporting.source_page == reporting.source_page
    assert merged_reporting.source_text == reporting.source_text
    assert merged_reporting.source_confidence == reporting.confidence
    assert merged_safety.source_document_id is None
    assert "보고 의무" in merged_reporting.suggestion_request
    assert "촬영 안전" in merged_safety.suggestion_request


@pytest.mark.parametrize(
    ("field", "contract_value", "support_value"),
    [
        (
            ExtractedField.CONTRACT_START_DATE,
            "2026-08-01",
            "2026-09-01",
        ),
        (ExtractedField.MONTHLY_AMOUNT, 500_000, 400_000),
        (ExtractedField.CONTENT_QUANTITY, 4, 3),
        (ExtractedField.AUTO_RENEWAL, "NO", "YES"),
        (ExtractedField.CONTRACT_RENEWAL_TYPE, "MANUAL", "AUTO"),
        (
            ExtractedField.REFUND_CONDITION,
            "미사용 기간 일부 환불",
            "환불 불가",
        ),
    ],
)
def test_documented_explanation_mismatch_uses_deterministic_typed_comparison(
    field: ExtractedField,
    contract_value,
    support_value,
) -> None:
    contract_term = make_term(
        field=field,
        value=contract_value,
        status=VerificationStatus.VERIFIED,
        source_text=f"계약 문서상 {contract_value}",
    )
    support_term = make_term(
        field=field,
        value=support_value,
        status=VerificationStatus.VERIFIED,
        source_text=f"선택 자료상 {support_value}",
        document_id=SUPPORT_DOCUMENT_ID,
        source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
    )

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=[contract_term, support_term],
        understood=None,
    )

    comparison = next(
        review for review in reviews if support_term.id in review.related_extracted_term_ids
    )
    assert comparison.type == ReviewSignalType.MISMATCH
    assert comparison.detection_method == DetectionMethod.DETERMINISTIC
    assert comparison.verification_status == VerificationStatus.VERIFIED
    assert comparison.related_extracted_term_ids == [
        contract_term.id,
        support_term.id,
    ]
    assert comparison.source_document_id == contract_term.document_id
    assert comparison.source_page == contract_term.source_page
    assert comparison.source_text == contract_term.source_text
    assert comparison.source_confidence == contract_term.confidence
    assert "문서로 확인된" in comparison.plain_explanation


def test_equal_documented_text_ignores_case_and_whitespace() -> None:
    contract_term = make_term(
        field=ExtractedField.REFUND_CONDITION,
        value="미사용 기간 일부 환불",
        status=VerificationStatus.VERIFIED,
        source_text="미사용 기간 일부 환불",
    )
    support_term = make_term(
        field=ExtractedField.REFUND_CONDITION,
        value="  미사용   기간 일부 환불  ",
        status=VerificationStatus.VERIFIED,
        source_text="미사용 기간 일부 환불",
        document_id=SUPPORT_DOCUMENT_ID,
        source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
    )

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=[contract_term, support_term],
        understood=None,
    )

    assert all(support_term.id not in review.related_extracted_term_ids for review in reviews)


def test_multiple_supporting_documents_share_all_term_ids_for_one_mismatch() -> None:
    contract_term = make_term(
        field=ExtractedField.CONTRACT_TOTAL_AMOUNT,
        value=5_000_000,
        status=VerificationStatus.VERIFIED,
        source_text="총 계약금액은 500만원이다.",
    )
    supporting_terms = [
        make_term(
            field=ExtractedField.CONTRACT_TOTAL_AMOUNT,
            value=4_800_000,
            status=VerificationStatus.VERIFIED,
            source_text="총 견적은 480만원이다.",
            document_id=document_id,
            source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
        )
        for document_id in (SUPPORT_DOCUMENT_ID, SECOND_SUPPORT_DOCUMENT_ID)
    ]

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=[contract_term, *supporting_terms],
        understood=None,
    )

    comparisons = [
        review
        for review in reviews
        if any(term.id in review.related_extracted_term_ids for term in supporting_terms)
    ]
    assert len(comparisons) == 1
    assert comparisons[0].type == ReviewSignalType.MISMATCH
    assert comparisons[0].related_extracted_term_ids == [
        contract_term.id,
        *(term.id for term in supporting_terms),
    ]


def test_conflicting_supporting_documents_create_check_before_solar_copy() -> None:
    contract_term = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=500_000,
        status=VerificationStatus.VERIFIED,
        source_text="월 납부액은 50만원이다.",
    )
    first_support = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=400_000,
        status=VerificationStatus.VERIFIED,
        source_text="월 관리비는 40만원이다.",
        document_id=SUPPORT_DOCUMENT_ID,
        source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
    )
    second_support = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=300_000,
        status=VerificationStatus.VERIFIED,
        source_text="월 관리비는 30만원이다.",
        document_id=SECOND_SUPPORT_DOCUMENT_ID,
        source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
    )
    terms = [contract_term, first_support, second_support]

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=terms,
        understood=None,
    )
    comparison = next(
        review for review in reviews if first_support.id in review.related_extracted_term_ids
    )
    solar_input = next(
        item
        for item in _build_solar_review_inputs(
            reviews=reviews,
            terms=terms,
            understood=None,
            contract=None,
        )
        if item.review_item_id == comparison.id
    )

    assert comparison.type == ReviewSignalType.NEEDS_CHECK
    assert comparison.verification_status == VerificationStatus.NEEDS_CHECK
    assert comparison.related_extracted_term_ids == [
        contract_term.id,
        first_support.id,
        second_support.id,
    ]
    assert solar_input.signal == ReviewSignalType.NEEDS_CHECK
    assert solar_input.deterministic_explanation == comparison.plain_explanation
    assert any(value.startswith("계약 문서상 조건") for value in solar_input.contract_values)
    assert sum(value.startswith("문서로 확인된 설명") for value in solar_input.contract_values) == 2


def test_contract_not_found_does_not_hide_supporting_document_conflict() -> None:
    contract_term = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=None,
        status=VerificationStatus.NOT_FOUND,
        source_text=None,
    )
    first_support = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=400_000,
        status=VerificationStatus.VERIFIED,
        source_text="월 관리비는 40만원이다.",
        document_id=SUPPORT_DOCUMENT_ID,
        source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
    )
    second_support = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=300_000,
        status=VerificationStatus.VERIFIED,
        source_text="월 관리비는 30만원이다.",
        document_id=SECOND_SUPPORT_DOCUMENT_ID,
        source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
    )

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=[contract_term, first_support, second_support],
        understood=None,
    )
    comparison = next(
        review for review in reviews if first_support.id in review.related_extracted_term_ids
    )

    assert comparison.type == ReviewSignalType.NEEDS_CHECK
    assert comparison.verification_status == VerificationStatus.NOT_FOUND
    assert comparison.related_extracted_term_ids == [
        contract_term.id,
        first_support.id,
        second_support.id,
    ]
    assert comparison.source_document_id is None


@pytest.mark.parametrize(
    (
        "contract_status",
        "contract_value",
        "contract_source",
        "support_status",
        "support_value",
        "support_source",
        "expected_signal",
        "expected_verification_status",
    ),
    [
        (
            VerificationStatus.VERIFIED,
            500_000,
            "월 납부액은 50만원이다.",
            VerificationStatus.MISSING_EVIDENCE,
            400_000,
            None,
            ReviewSignalType.NEEDS_CHECK,
            VerificationStatus.NEEDS_CHECK,
        ),
        (
            VerificationStatus.VERIFIED,
            500_000,
            "월 납부액은 50만원이다.",
            VerificationStatus.NEEDS_CHECK,
            400_000,
            "월 납부액은 약 40만원으로 보인다.",
            ReviewSignalType.NEEDS_CHECK,
            VerificationStatus.NEEDS_CHECK,
        ),
        (
            VerificationStatus.NOT_FOUND,
            None,
            None,
            VerificationStatus.VERIFIED,
            400_000,
            "월 납부액은 40만원이다.",
            ReviewSignalType.NO_BASIS,
            VerificationStatus.NOT_FOUND,
        ),
    ],
)
def test_unverified_document_comparison_never_confirms_mismatch(
    contract_status: VerificationStatus,
    contract_value,
    contract_source: str | None,
    support_status: VerificationStatus,
    support_value,
    support_source: str | None,
    expected_signal: ReviewSignalType,
    expected_verification_status: VerificationStatus,
) -> None:
    contract_term = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=contract_value,
        status=contract_status,
        source_text=contract_source,
    )
    support_term = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=support_value,
        status=support_status,
        source_text=support_source,
        document_id=SUPPORT_DOCUMENT_ID,
        source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
    )

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=[contract_term, support_term],
        understood=None,
    )
    comparison = next(
        review for review in reviews if support_term.id in review.related_extracted_term_ids
    )

    assert comparison.type == expected_signal
    assert comparison.verification_status == expected_verification_status
    assert comparison.related_extracted_term_ids == [
        contract_term.id,
        support_term.id,
    ]
    assert all(
        review.type != ReviewSignalType.MISMATCH
        for review in reviews
        if support_term.id in review.related_extracted_term_ids
    )
    if contract_source is None:
        assert comparison.source_document_id is None
        assert comparison.source_page is None
        assert comparison.source_text is None
        assert comparison.source_confidence is None
    else:
        assert comparison.source_document_id == contract_term.document_id


def test_supporting_document_not_found_without_claim_adds_no_comparison_noise() -> None:
    contract_term = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=500_000,
        status=VerificationStatus.VERIFIED,
        source_text="월 납부액은 50만원이다.",
    )
    absent_support_term = make_term(
        field=ExtractedField.MONTHLY_AMOUNT,
        value=None,
        status=VerificationStatus.NOT_FOUND,
        source_text=None,
        document_id=SUPPORT_DOCUMENT_ID,
        source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION,
    )

    reviews = _build_review_items(
        contract_id=CONTRACT_ID,
        terms=[contract_term, absent_support_term],
        understood=None,
    )

    assert all(
        absent_support_term.id not in review.related_extracted_term_ids for review in reviews
    )
