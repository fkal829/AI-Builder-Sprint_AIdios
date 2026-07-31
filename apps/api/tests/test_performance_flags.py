"""P2-C-2: deterministic decision rules for when a `PerformanceFlag` is
created. Pure function tests — no repository, no schema-validation retread
(that's `test_performance_contract.py`'s job)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.enums import (
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
    PerformanceFlagType,
    PerformanceMetricVerificationStatus,
    PerformanceReportStatus,
    VerificationStatus,
)
from app.domain.performance_flags import (
    build_deliverable_shortfall_flag,
    build_engagement_rate_drop_flag,
)
from app.schemas.analysis import ExtractedTerm
from app.schemas.performance import (
    PerformanceConfirmedPayload,
    PerformanceExtractedPayload,
    PerformanceNonNegativeMetricCandidate,
    PerformanceReport,
    PerformanceReportRevision,
    PerformanceSignedMetricCandidate,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)
CONTRACT_ID = uuid4()
DOCUMENT_ID = uuid4()
REVISION_ID = uuid4()


def make_payload(**overrides) -> PerformanceConfirmedPayload:
    values = {
        "impressions": 1_000,
        "likes": 0,
        "comments": 0,
        "reach": None,
        "saves": None,
        "shares": None,
        "follower_net_change": None,
        "published_content_count": None,
        "inquiries": None,
        "reservations": None,
        "purchases": None,
    }
    values.update(overrides)
    return PerformanceConfirmedPayload(**values)


def make_term(
    *,
    field: ExtractedField,
    value: object,
    value_type: ExtractedValueType = ExtractedValueType.TEXT,
    verification_status: VerificationStatus = VerificationStatus.VERIFIED,
    source_type: ExtractedSourceType = ExtractedSourceType.CONTRACT_DOCUMENT,
    source_page: int | None = 3,
    source_text: str | None = "원문 발췌",
) -> ExtractedTerm:
    return ExtractedTerm(
        id=uuid4(),
        contract_id=CONTRACT_ID,
        document_id=DOCUMENT_ID,
        source_type=source_type,
        field=field,
        value_type=value_type,
        value=value,
        source_page=source_page,
        source_text=source_text,
        confidence=0.95,
        verification_status=verification_status,
    )


def quantity_term(value: int = 4, **overrides) -> ExtractedTerm:
    return make_term(
        field=ExtractedField.CONTENT_QUANTITY,
        value=value,
        value_type=ExtractedValueType.INTEGER,
        **overrides,
    )


def frequency_term(**overrides) -> ExtractedTerm:
    return make_term(field=ExtractedField.POSTING_FREQUENCY, value="매월", **overrides)


def _candidate(value, *, signed: bool = False):
    candidate_type = (
        PerformanceSignedMetricCandidate if signed else PerformanceNonNegativeMetricCandidate
    )
    return candidate_type(
        value=value,
        source_page=1 if value is not None else None,
        source_text="리포트 원문" if value is not None else None,
        confidence=0.9,
        verification_status=(
            PerformanceMetricVerificationStatus.VERIFIED
            if value is not None
            else PerformanceMetricVerificationStatus.NOT_FOUND
        ),
    )


def make_confirmed_report(
    *, period: str, payload: PerformanceConfirmedPayload
) -> PerformanceReport:
    extracted = PerformanceExtractedPayload(
        impressions=_candidate(payload.impressions),
        likes=_candidate(payload.likes),
        comments=_candidate(payload.comments),
        reach=_candidate(payload.reach),
        saves=_candidate(payload.saves),
        shares=_candidate(payload.shares),
        follower_net_change=_candidate(payload.follower_net_change, signed=True),
        published_content_count=_candidate(payload.published_content_count),
    )
    revision = PerformanceReportRevision(
        id=uuid4(),
        report_id=uuid4(),
        version=1,
        status=PerformanceReportStatus.CONFIRMED,
        confirmed_payload=payload,
        engagement_rate=payload.calculate_engagement_rate(),
        corrected_from_revision_id=None,
        correction_reason=None,
        confirmed_at=NOW,
        flags=[],
        inquiry_drafts=[],
    )
    return PerformanceReport(
        id=revision.report_id,
        contract_id=CONTRACT_ID,
        period=period,
        source_document_id=DOCUMENT_ID,
        status=PerformanceReportStatus.CONFIRMED,
        extracted_payload=extracted,
        current_revision=revision,
        revision_count=1,
        revisions=[revision],
        created_at=NOW,
        updated_at=NOW,
    )


# --- DELIVERABLE_COUNT_SHORTFALL ---------------------------------------------


def test_shortfall_flag_created_when_actual_is_below_contract_quantity() -> None:
    flag = build_deliverable_shortfall_flag(
        contract_id=CONTRACT_ID,
        report_revision_id=REVISION_ID,
        actual_content_count=3,
        contract_terms=[quantity_term(4), frequency_term()],
        now=NOW,
    )

    assert flag is not None
    assert flag.flag_type == PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL
    assert flag.expected_content_count == 4
    assert flag.actual_content_count == 3
    assert flag.expected_period_unit == "MONTH"
    assert len(flag.basis_snapshots) == 2


@pytest.mark.parametrize("actual", [4, 5])
def test_no_shortfall_flag_when_actual_meets_or_exceeds_quantity(actual: int) -> None:
    flag = build_deliverable_shortfall_flag(
        contract_id=CONTRACT_ID,
        report_revision_id=REVISION_ID,
        actual_content_count=actual,
        contract_terms=[quantity_term(4), frequency_term()],
        now=NOW,
    )
    assert flag is None


def test_no_shortfall_flag_when_actual_content_count_is_unconfirmed() -> None:
    flag = build_deliverable_shortfall_flag(
        contract_id=CONTRACT_ID,
        report_revision_id=REVISION_ID,
        actual_content_count=None,
        contract_terms=[quantity_term(4), frequency_term()],
        now=NOW,
    )
    assert flag is None


def test_no_shortfall_flag_when_posting_frequency_term_missing() -> None:
    flag = build_deliverable_shortfall_flag(
        contract_id=CONTRACT_ID,
        report_revision_id=REVISION_ID,
        actual_content_count=1,
        contract_terms=[quantity_term(4)],
        now=NOW,
    )
    assert flag is None


def test_no_shortfall_flag_when_quantity_term_is_not_verified() -> None:
    flag = build_deliverable_shortfall_flag(
        contract_id=CONTRACT_ID,
        report_revision_id=REVISION_ID,
        actual_content_count=1,
        contract_terms=[
            quantity_term(4, verification_status=VerificationStatus.NEEDS_CHECK),
            frequency_term(),
        ],
        now=NOW,
    )
    assert flag is None


def test_no_shortfall_flag_when_evidence_is_not_from_contract_document() -> None:
    flag = build_deliverable_shortfall_flag(
        contract_id=CONTRACT_ID,
        report_revision_id=REVISION_ID,
        actual_content_count=1,
        contract_terms=[
            quantity_term(4, source_type=ExtractedSourceType.DOCUMENTED_EXPLANATION),
            frequency_term(),
        ],
        now=NOW,
    )
    assert flag is None


# --- ENGAGEMENT_RATE_DROP -----------------------------------------------------


def test_no_drop_flag_without_a_previous_month_report() -> None:
    flag = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=30),
        previous_report=None,
        now=NOW,
    )
    assert flag is None


def test_no_drop_flag_when_previous_month_report_is_not_confirmed() -> None:
    payload = make_payload(likes=40)
    report = make_confirmed_report(period="2026-06", payload=payload)
    unconfirmed = report.model_copy(
        update={
            "status": PerformanceReportStatus.EXTRACTED,
            "current_revision": None,
            "revision_count": 0,
            "revisions": [],
        }
    )
    flag = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=30),
        previous_report=unconfirmed,
        now=NOW,
    )
    assert flag is None


def test_no_drop_flag_when_previous_report_skips_a_calendar_month() -> None:
    previous = make_confirmed_report(period="2026-05", payload=make_payload(likes=40))
    flag = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=30),
        previous_report=previous,
        now=NOW,
    )
    assert flag is None


def test_no_drop_flag_when_either_month_is_under_the_impression_floor() -> None:
    previous = make_confirmed_report(
        period="2026-06", payload=make_payload(impressions=999, likes=40)
    )
    flag = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=30),
        previous_report=previous,
        now=NOW,
    )
    assert flag is None


def test_no_drop_flag_when_saves_shares_composition_differs() -> None:
    previous = make_confirmed_report(
        period="2026-06", payload=make_payload(likes=40, saves=5)
    )
    flag = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=30),  # saves=None here, saves=5 last month
        previous_report=previous,
        now=NOW,
    )
    assert flag is None


def test_no_drop_flag_when_rate_did_not_fall() -> None:
    previous = make_confirmed_report(period="2026-06", payload=make_payload(likes=30))
    flag = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=40),
        previous_report=previous,
        now=NOW,
    )
    assert flag is None


def test_no_drop_flag_when_below_threshold_on_either_axis() -> None:
    # previous 4%, current 3.1%: 0.9pp absolute drop — fails the 1.0pp floor.
    previous = make_confirmed_report(period="2026-06", payload=make_payload(likes=40))
    just_under_absolute = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=31),
        previous_report=previous,
        now=NOW,
    )
    assert just_under_absolute is None

    # previous 5%, current 4%: 1.0pp absolute but only 20% relative — fails
    # the 25% floor.
    previous_5pct = make_confirmed_report(period="2026-06", payload=make_payload(likes=50))
    just_under_relative = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=40),
        previous_report=previous_5pct,
        now=NOW,
    )
    assert just_under_relative is None


def test_drop_flag_created_at_the_exact_threshold_boundary() -> None:
    # previous 4%, current 3%: 1.0pp absolute AND 25% relative — both floors
    # met exactly.
    previous = make_confirmed_report(period="2026-06", payload=make_payload(likes=40))
    current_revision_id = previous.current_revision.id

    flag = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-07",
        current_payload=make_payload(likes=30),
        previous_report=previous,
        now=NOW,
    )

    assert flag is not None
    assert flag.flag_type == PerformanceFlagType.ENGAGEMENT_RATE_DROP
    assert flag.comparison_report_revision_id == current_revision_id
    assert flag.previous_engagement_rate == make_payload(likes=40).calculate_engagement_rate()
    assert flag.current_engagement_rate == make_payload(likes=30).calculate_engagement_rate()


def test_drop_flag_handles_the_december_to_january_year_boundary() -> None:
    previous = make_confirmed_report(period="2025-12", payload=make_payload(likes=40))
    flag = build_engagement_rate_drop_flag(
        report_revision_id=REVISION_ID,
        current_period="2026-01",
        current_payload=make_payload(likes=30),
        previous_report=previous,
        now=NOW,
    )
    assert flag is not None
