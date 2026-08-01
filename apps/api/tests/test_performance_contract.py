from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml
from pydantic import ValidationError

from app.core.enums import (
    AuditEventType,
    ExtractedField,
    ExtractedSourceType,
    IdempotencyOperation,
    PerformanceFlagType,
    PerformanceMetricVerificationStatus,
    PerformanceReportStatus,
    PerformanceStateEntityType,
    StateEntityType,
    VerificationStatus,
)
from app.core.errors import ErrorCode
from app.schemas.documents import ContractDocumentUploadType, DocumentType
from app.schemas.performance import (
    ContractPerformance,
    PerformanceConfirmedPayload,
    PerformanceConfirmedPayloadInput,
    PerformanceConfirmedSeriesPoint,
    PerformanceExtractedPayload,
    PerformanceFlag,
    PerformanceFlagBasisSnapshot,
    PerformanceInquiryDraft,
    PerformanceNonNegativeMetricCandidate,
    PerformanceReport,
    PerformanceReportConfirmation,
    PerformanceReportConfirmed,
    PerformanceReportCreated,
    PerformanceReportExtracted,
    PerformanceReportRevision,
    PerformanceSignedMetricCandidate,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml"
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def confirmed_payload_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "impressions": 1_000,
        "likes": 80,
        "comments": 10,
        "reach": 900,
        "saves": 6,
        "shares": 4,
        "follower_net_change": -2,
        "published_content_count": 3,
        "inquiries": None,
        "reservations": None,
        "purchases": None,
    }
    values.update(overrides)
    return values


def make_confirmed_payload(**overrides: object) -> PerformanceConfirmedPayload:
    return PerformanceConfirmedPayload(**confirmed_payload_values(**overrides))


def make_non_negative_candidate(
    value: int | None,
    *,
    status: PerformanceMetricVerificationStatus = PerformanceMetricVerificationStatus.VERIFIED,
) -> PerformanceNonNegativeMetricCandidate:
    has_evidence = status != PerformanceMetricVerificationStatus.NOT_FOUND
    return PerformanceNonNegativeMetricCandidate(
        value=value,
        source_page=1 if has_evidence else None,
        source_text="리포트에 표시된 지표" if has_evidence else None,
        confidence=0.9,
        verification_status=status,
    )


def make_extracted_payload() -> PerformanceExtractedPayload:
    return PerformanceExtractedPayload(
        impressions=make_non_negative_candidate(1_000),
        likes=make_non_negative_candidate(80),
        comments=make_non_negative_candidate(10),
        reach=make_non_negative_candidate(900),
        saves=make_non_negative_candidate(6),
        shares=make_non_negative_candidate(4),
        follower_net_change=PerformanceSignedMetricCandidate(
            value=-2,
            source_page=1,
            source_text="팔로워 순증 -2",
            confidence=0.88,
            verification_status=PerformanceMetricVerificationStatus.VERIFIED,
        ),
        published_content_count=make_non_negative_candidate(3),
    )


def make_revision(
    *,
    report_id: UUID,
    revision_id: UUID,
    version: int = 1,
    corrected_from_revision_id: UUID | None = None,
    correction_reason: str | None = None,
    engagement_rate: Decimal | None = Decimal("0.100000"),
) -> PerformanceReportRevision:
    return PerformanceReportRevision(
        id=revision_id,
        report_id=report_id,
        version=version,
        status=PerformanceReportStatus.CONFIRMED,
        confirmed_payload=make_confirmed_payload(),
        engagement_rate=engagement_rate,
        corrected_from_revision_id=corrected_from_revision_id,
        correction_reason=correction_reason,
        confirmed_at=NOW,
        flags=[],
        inquiry_drafts=[],
    )


def make_owner_issue_flag(
    *,
    revision_id: UUID,
) -> tuple[PerformanceFlag, PerformanceInquiryDraft]:
    flag = PerformanceFlag(
        id=uuid4(),
        report_revision_id=revision_id,
        flag_type=PerformanceFlagType.OWNER_REPORTED_ISSUE,
        basis_extracted_term_ids=[],
        basis_snapshots=[],
        comparison_report_revision_id=None,
        expected_content_count=None,
        expected_period_unit=None,
        actual_content_count=None,
        previous_engagement_rate=None,
        current_engagement_rate=None,
        issue_note="집계 기준을 확인하고 싶습니다.",
        created_at=NOW,
    )
    draft = PerformanceInquiryDraft(
        id=uuid4(),
        flag_id=flag.id,
        text="2026-07 리포트의 관련 수치와 집계 기준을 확인 부탁드립니다.",
        template_version="performance-inquiry-copy-v1",
        created_at=NOW,
    )
    return flag, draft


def test_performance_common_enums_match_the_planned_contract() -> None:
    assert {status.value for status in PerformanceReportStatus} == {
        "UPLOADED",
        "EXTRACTED",
        "CONFIRMED",
        "FLAGGED",
    }
    assert {flag.value for flag in PerformanceFlagType} == {
        "DELIVERABLE_COUNT_SHORTFALL",
        "ENGAGEMENT_RATE_DROP",
        "OWNER_REPORTED_ISSUE",
    }
    assert {status.value for status in PerformanceMetricVerificationStatus} == {
        "VERIFIED",
        "NOT_FOUND",
        "NEEDS_CHECK",
    }
    assert PerformanceStateEntityType.PERFORMANCE_REPORT.value == "PERFORMANCE_REPORT"
    assert "PERFORMANCE_REPORT" not in {entity.value for entity in StateEntityType}
    assert DocumentType.PERFORMANCE_REPORT.value == "PERFORMANCE_REPORT"
    assert "PERFORMANCE_REPORT" not in {item.value for item in ContractDocumentUploadType}

    assert {
        IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD,
        IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT,
        IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM,
    } <= set(IdempotencyOperation)


def test_performance_events_are_public_after_the_foundation_migration() -> None:
    expected = {
        "PERFORMANCE_REPORT_UPLOADED",
        "PERFORMANCE_REPORT_EXTRACTED",
        "PERFORMANCE_REPORT_CONFIRMED",
        "PERFORMANCE_REPORT_FLAGGED",
        "PERFORMANCE_REPORT_CORRECTED",
        "PERFORMANCE_REPORT_EXTRACTION_RECOVERED",
    }

    assert expected <= {event.value for event in AuditEventType}

    openapi = OPENAPI_PATH.read_text(encoding="utf-8")
    assert "PerformanceAuditEventType:" not in openapi
    for event in expected:
        assert f"        - {event}" in openapi


def test_performance_error_codes_match_the_five_approved_codes() -> None:
    assert {
        ErrorCode.REPORT_PERIOD_ALREADY_EXISTS.value,
        ErrorCode.REPORT_REVISION_CONFLICT.value,
        ErrorCode.REPORT_CORRECTION_DEPENDENCY_EXISTS.value,
        ErrorCode.REPORT_EXTRACTION_IN_PROGRESS.value,
        ErrorCode.REPORT_EXTRACT_FAILED.value,
    } == {
        "REPORT_PERIOD_ALREADY_EXISTS",
        "REPORT_REVISION_CONFLICT",
        "REPORT_CORRECTION_DEPENDENCY_EXISTS",
        "REPORT_EXTRACTION_IN_PROGRESS",
        "REPORT_EXTRACT_FAILED",
    }
    assert ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE.value == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "REPORT_UPLOAD_FAILED" not in {code.value for code in ErrorCode}


def test_performance_metric_candidates_are_strict_and_evidence_backed() -> None:
    missing = make_non_negative_candidate(
        None,
        status=PerformanceMetricVerificationStatus.NOT_FOUND,
    )
    signed = PerformanceSignedMetricCandidate(
        value=-7,
        source_page=2,
        source_text="팔로워 순증 -7",
        confidence=0.8,
        verification_status=PerformanceMetricVerificationStatus.VERIFIED,
    )

    assert missing.value is None
    assert signed.value == -7
    with pytest.raises(ValidationError):
        PerformanceNonNegativeMetricCandidate(
            value=None,
            source_page=1,
            source_text="찾지 못했지만 만든 근거",
            confidence=0.7,
            verification_status=PerformanceMetricVerificationStatus.NOT_FOUND,
        )
    with pytest.raises(ValidationError):
        PerformanceNonNegativeMetricCandidate(
            value=1,
            source_page=1,
            source_text="노출 1",
            confidence=0.7,
            verification_status=PerformanceMetricVerificationStatus.VERIFIED,
            roas=2,
        )


def test_confirmed_payload_rejects_derived_or_unknown_fields() -> None:
    payload = PerformanceConfirmedPayloadInput(**confirmed_payload_values())

    assert payload.published_content_count == 3
    with pytest.raises(ValidationError):
        PerformanceConfirmedPayloadInput(
            **confirmed_payload_values(engagement_rate=Decimal("0.100000"))
        )
    with pytest.raises(ValidationError):
        PerformanceConfirmedPayloadInput(**confirmed_payload_values(roas=Decimal("1.2")))


def test_confirmed_payload_requires_nullable_keys_and_preserves_zero() -> None:
    missing_reach = confirmed_payload_values()
    del missing_reach["reach"]

    with pytest.raises(ValidationError):
        PerformanceConfirmedPayloadInput(**missing_reach)
    zero = PerformanceConfirmedPayloadInput(**confirmed_payload_values(published_content_count=0))
    unknown = PerformanceConfirmedPayloadInput(
        **confirmed_payload_values(published_content_count=None)
    )
    assert zero.published_content_count == 0
    assert unknown.published_content_count is None


@pytest.mark.parametrize(
    "field",
    (
        "impressions",
        "likes",
        "comments",
        "reach",
        "saves",
        "shares",
        "published_content_count",
        "inquiries",
        "reservations",
        "purchases",
    ),
)
def test_confirmed_payload_rejects_negative_non_negative_metrics(field: str) -> None:
    with pytest.raises(ValidationError):
        PerformanceConfirmedPayloadInput(**confirmed_payload_values(**{field: -1}))


def test_confirmed_payload_allows_negative_follower_net_change_but_rejects_boolean() -> None:
    payload = PerformanceConfirmedPayloadInput(**confirmed_payload_values(follower_net_change=-12))

    assert payload.follower_net_change == -12
    with pytest.raises(ValidationError):
        PerformanceConfirmedPayloadInput(**confirmed_payload_values(published_content_count=True))


def test_published_content_count_candidate_preserves_not_found_and_zero() -> None:
    base_payload = make_extracted_payload().model_dump()
    unknown = PerformanceExtractedPayload(
        **{
            **base_payload,
            "published_content_count": make_non_negative_candidate(
                None,
                status=PerformanceMetricVerificationStatus.NOT_FOUND,
            ).model_dump(),
        }
    )
    zero = PerformanceExtractedPayload(
        **{
            **base_payload,
            "published_content_count": make_non_negative_candidate(0).model_dump(),
        }
    )

    assert "published_content_count" in unknown.model_dump()
    assert unknown.published_content_count.value is None
    assert zero.published_content_count.value == 0
    with pytest.raises(ValidationError):
        make_non_negative_candidate(-1)
    with pytest.raises(ValidationError):
        PerformanceNonNegativeMetricCandidate(
            value=None,
            source_page=None,
            source_text=None,
            confidence=0.5,
            verification_status=PerformanceMetricVerificationStatus.NEEDS_CHECK,
        )


def test_revision_validates_decimal_half_up_engagement_rate() -> None:
    report_id = uuid4()
    payload = make_confirmed_payload(
        impressions=3,
        likes=2,
        comments=0,
        saves=None,
        shares=None,
    )

    revision = PerformanceReportRevision(
        id=uuid4(),
        report_id=report_id,
        version=1,
        status=PerformanceReportStatus.CONFIRMED,
        confirmed_payload=payload,
        engagement_rate=Decimal("0.666667"),
        corrected_from_revision_id=None,
        correction_reason=None,
        confirmed_at=NOW,
        flags=[],
        inquiry_drafts=[],
    )

    assert revision.engagement_rate == Decimal("0.666667")
    with pytest.raises(ValidationError, match="원본 정수"):
        PerformanceReportRevision(
            **{
                **revision.model_dump(),
                "id": uuid4(),
                "engagement_rate": Decimal("0.666666"),
            }
        )


def test_revision_requires_null_rate_for_zero_impressions() -> None:
    payload = make_confirmed_payload(
        impressions=0,
        likes=0,
        comments=0,
        saves=None,
        shares=None,
    )
    values = {
        "id": uuid4(),
        "report_id": uuid4(),
        "version": 1,
        "status": PerformanceReportStatus.CONFIRMED,
        "confirmed_payload": payload,
        "corrected_from_revision_id": None,
        "correction_reason": None,
        "confirmed_at": NOW,
        "flags": [],
        "inquiry_drafts": [],
    }

    assert PerformanceReportRevision(**values, engagement_rate=None).engagement_rate is None
    with pytest.raises(ValidationError, match="원본 정수"):
        PerformanceReportRevision(**values, engagement_rate=Decimal("0.000000"))


def test_confirmation_distinguishes_initial_correction_and_owner_issue() -> None:
    payload = PerformanceConfirmedPayloadInput(**confirmed_payload_values())

    initial = PerformanceReportConfirmation(
        expected_revision=0,
        confirmed_payload=payload,
        has_issue=False,
        issue_note=None,
        correction_reason=None,
    )
    correction = PerformanceReportConfirmation(
        expected_revision=1,
        confirmed_payload=payload,
        has_issue=True,
        issue_note="게시 수 집계 기준을 확인하고 싶습니다.",
        correction_reason="리포트 수치를 다시 확인했습니다.",
    )

    assert initial.expected_revision == 0
    assert correction.expected_revision == 1
    with pytest.raises(ValidationError, match="issue_note가 null"):
        PerformanceReportConfirmation(
            expected_revision=0,
            confirmed_payload=payload,
            has_issue=False,
            issue_note="상태와 맞지 않는 사유",
            correction_reason=None,
        )
    with pytest.raises(ValidationError, match="정정에는"):
        PerformanceReportConfirmation(
            expected_revision=1,
            confirmed_payload=payload,
            has_issue=False,
            issue_note=None,
            correction_reason=None,
        )


def test_deliverable_flag_requires_two_verified_basis_snapshots_and_a_shortfall() -> None:
    revision_id = uuid4()
    quantity_term_id = uuid4()
    frequency_term_id = uuid4()
    snapshots = [
        PerformanceFlagBasisSnapshot(
            extracted_term_id=quantity_term_id,
            document_id=uuid4(),
            field=ExtractedField.CONTENT_QUANTITY,
            source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
            source_page=2,
            source_text="월 4건을 게시한다.",
            confidence=0.95,
            verification_status=VerificationStatus.VERIFIED,
        ),
        PerformanceFlagBasisSnapshot(
            extracted_term_id=frequency_term_id,
            document_id=uuid4(),
            field=ExtractedField.POSTING_FREQUENCY,
            source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
            source_page=2,
            source_text="매월 게시한다.",
            confidence=0.91,
            verification_status=VerificationStatus.VERIFIED,
        ),
    ]
    values = {
        "id": uuid4(),
        "report_revision_id": revision_id,
        "flag_type": PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL,
        "basis_extracted_term_ids": [quantity_term_id, frequency_term_id],
        "basis_snapshots": snapshots,
        "comparison_report_revision_id": None,
        "expected_content_count": 4,
        "expected_period_unit": "MONTH",
        "actual_content_count": 3,
        "previous_engagement_rate": None,
        "current_engagement_rate": None,
        "issue_note": None,
        "created_at": NOW,
    }

    assert PerformanceFlag(**values).actual_content_count == 3
    with pytest.raises(ValidationError, match="수량 부족"):
        PerformanceFlag(**{**values, "actual_content_count": 4})


def test_report_revisions_reference_the_actual_previous_revision() -> None:
    report_id = uuid4()
    first_id = uuid4()
    first = make_revision(report_id=report_id, revision_id=first_id)
    second = make_revision(
        report_id=report_id,
        revision_id=uuid4(),
        version=2,
        corrected_from_revision_id=first_id,
        correction_reason="수치를 다시 확인했습니다.",
    )
    values = {
        "id": report_id,
        "contract_id": uuid4(),
        "period": "2026-07",
        "source_document_id": uuid4(),
        "status": PerformanceReportStatus.CONFIRMED,
        "extracted_payload": make_extracted_payload(),
        "current_revision": second,
        "revision_count": 2,
        "revisions": [first, second],
        "created_at": NOW,
        "updated_at": NOW,
    }

    assert PerformanceReport(**values).current_revision == second
    wrong_second = make_revision(
        report_id=report_id,
        revision_id=uuid4(),
        version=2,
        corrected_from_revision_id=uuid4(),
        correction_reason="수치를 다시 확인했습니다.",
    )
    with pytest.raises(ValidationError, match="실제 직전"):
        PerformanceReport(
            **{
                **values,
                "current_revision": wrong_second,
                "revisions": [first, wrong_second],
            }
        )


def test_operation_specific_report_models_narrow_the_response_state() -> None:
    uploaded_values = {
        "id": uuid4(),
        "contract_id": uuid4(),
        "period": "2026-07",
        "source_document_id": uuid4(),
        "status": PerformanceReportStatus.UPLOADED,
        "extracted_payload": None,
        "current_revision": None,
        "revision_count": 0,
        "revisions": [],
        "created_at": NOW,
        "updated_at": NOW,
    }
    created = PerformanceReportCreated(**uploaded_values)
    extracted = PerformanceReportExtracted(
        **{
            **uploaded_values,
            "status": PerformanceReportStatus.EXTRACTED,
            "extracted_payload": make_extracted_payload(),
        }
    )

    assert created.status == PerformanceReportStatus.UPLOADED
    assert extracted.status == PerformanceReportStatus.EXTRACTED
    with pytest.raises(ValidationError):
        PerformanceReportCreated(
            **{
                **uploaded_values,
                "status": PerformanceReportStatus.EXTRACTED,
                "extracted_payload": make_extracted_payload(),
            }
        )


def test_flagged_revision_requires_exactly_one_saved_draft_per_flag() -> None:
    report_id = uuid4()
    revision_id = uuid4()
    flag, draft = make_owner_issue_flag(revision_id=revision_id)
    values = {
        "id": revision_id,
        "report_id": report_id,
        "version": 1,
        "status": PerformanceReportStatus.FLAGGED,
        "confirmed_payload": make_confirmed_payload(),
        "engagement_rate": Decimal("0.100000"),
        "corrected_from_revision_id": None,
        "correction_reason": None,
        "confirmed_at": NOW,
        "flags": [flag],
        "inquiry_drafts": [draft],
    }

    assert PerformanceReportRevision(**values).inquiry_drafts == [draft]
    with pytest.raises(ValidationError, match="정확히 한 개"):
        PerformanceReportRevision(**{**values, "inquiry_drafts": []})


def test_contract_performance_uses_only_current_confirmed_revisions() -> None:
    report_id = uuid4()
    first_id = uuid4()
    old_flag, old_draft = make_owner_issue_flag(revision_id=first_id)
    first = PerformanceReportRevision(
        id=first_id,
        report_id=report_id,
        version=1,
        status=PerformanceReportStatus.FLAGGED,
        confirmed_payload=make_confirmed_payload(),
        engagement_rate=Decimal("0.100000"),
        corrected_from_revision_id=None,
        correction_reason=None,
        confirmed_at=NOW,
        flags=[old_flag],
        inquiry_drafts=[old_draft],
    )
    revision = make_revision(
        report_id=report_id,
        revision_id=uuid4(),
        version=2,
        corrected_from_revision_id=first.id,
        correction_reason="사용자 이상 기록을 정정했습니다.",
    )
    report = PerformanceReport(
        id=report_id,
        contract_id=uuid4(),
        period="2026-07",
        source_document_id=uuid4(),
        status=PerformanceReportStatus.CONFIRMED,
        extracted_payload=make_extracted_payload(),
        current_revision=revision,
        revision_count=2,
        revisions=[first, revision],
        created_at=NOW,
        updated_at=NOW,
    )
    point = PerformanceConfirmedSeriesPoint(
        report_id=report.id,
        report_revision_id=revision.id,
        period=report.period,
        version=revision.version,
        status=revision.status,
        confirmed_payload=revision.confirmed_payload,
        engagement_rate=revision.engagement_rate,
        confirmed_at=revision.confirmed_at,
    )

    result = ContractPerformance(
        contract_id=report.contract_id,
        reports=[report],
        confirmed_series=[point],
        flags=[],
        inquiry_drafts=[],
    )

    assert result.confirmed_series == [point]
    with pytest.raises(ValidationError, match="최신 revision"):
        ContractPerformance(
            contract_id=report.contract_id,
            reports=[report],
            confirmed_series=[point],
            flags=[old_flag],
            inquiry_drafts=[old_draft],
        )


def test_performance_models_forbid_additional_properties() -> None:
    models = (
        PerformanceNonNegativeMetricCandidate,
        PerformanceSignedMetricCandidate,
        PerformanceExtractedPayload,
        PerformanceConfirmedPayloadInput,
        PerformanceConfirmedPayload,
        PerformanceReportConfirmation,
        PerformanceFlagBasisSnapshot,
        PerformanceFlag,
        PerformanceInquiryDraft,
        PerformanceReportRevision,
        PerformanceReport,
        PerformanceReportCreated,
        PerformanceReportExtracted,
        PerformanceReportConfirmed,
        PerformanceConfirmedSeriesPoint,
        ContractPerformance,
    )

    for model in models:
        assert model.model_json_schema()["additionalProperties"] is False


def test_pydantic_performance_properties_match_openapi() -> None:
    canonical = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    schemas = canonical["components"]["schemas"]
    models = {
        "PerformanceNonNegativeMetricCandidate": PerformanceNonNegativeMetricCandidate,
        "PerformanceSignedMetricCandidate": PerformanceSignedMetricCandidate,
        "PerformanceExtractedPayload": PerformanceExtractedPayload,
        "PerformanceConfirmedPayloadInput": PerformanceConfirmedPayloadInput,
        "PerformanceConfirmedPayload": PerformanceConfirmedPayload,
        "PerformanceReportConfirmation": PerformanceReportConfirmation,
        "PerformanceFlagBasisSnapshot": PerformanceFlagBasisSnapshot,
        "PerformanceFlag": PerformanceFlag,
        "PerformanceInquiryDraft": PerformanceInquiryDraft,
        "PerformanceReportRevision": PerformanceReportRevision,
        "PerformanceReport": PerformanceReport,
        "PerformanceConfirmedSeriesPoint": PerformanceConfirmedSeriesPoint,
        "ContractPerformance": ContractPerformance,
    }

    for name, model in models.items():
        pydantic_schema = model.model_json_schema()
        openapi_schema = schemas[name]
        assert set(pydantic_schema["properties"]) == set(openapi_schema["properties"]), name
        assert set(pydantic_schema["required"]) == set(openapi_schema["required"]), name
        assert pydantic_schema["additionalProperties"] is False
        assert openapi_schema["additionalProperties"] is False


def test_openapi_marks_no_performance_operations_as_planned() -> None:
    canonical = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    planned = {
        (method.upper(), path, operation["operationId"])
        for path, path_item in canonical["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
        and path.startswith("/contracts/{contract_id}/performance")
        and operation.get("x-implementation-status") == "planned"
    }

    assert planned == set()
