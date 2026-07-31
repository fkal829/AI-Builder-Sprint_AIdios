"""P2-C-2: deterministic decision rules for `PerformanceFlag` creation.

`PerformanceFlag`'s own Pydantic validators (app/schemas/performance.py) only
check that a flag's fields are *internally* consistent once someone decides
to build one (e.g. a shortfall flag's `actual_content_count` must be below
`expected_content_count`). They cannot know the 1,000-impression /
1.0-percentage-point / 25% engagement-drop thresholds, since those need the
full picture (both months' payloads, the contract's verified terms) that a
lone flag object doesn't carry. This module is that missing decision layer:
pure functions, no I/O, no AI — either they return a flag or they return
`None`.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.core.enums import (
    ExtractedField,
    ExtractedSourceType,
    PerformanceFlagType,
    PerformanceReportStatus,
    VerificationStatus,
)
from app.schemas.analysis import ExtractedTerm
from app.schemas.performance import (
    PerformanceConfirmedPayload,
    PerformanceFlag,
    PerformanceFlagBasisSnapshot,
    PerformanceReport,
)

_MINIMUM_IMPRESSIONS = 1_000
_MINIMUM_ABSOLUTE_DROP_POINTS = Decimal("1.0")
_MINIMUM_RELATIVE_DROP_PERCENT = Decimal("25")


def build_deliverable_shortfall_flag(
    *,
    contract_id: UUID,
    report_revision_id: UUID,
    actual_content_count: int | None,
    contract_terms: Sequence[ExtractedTerm],
    now: datetime,
) -> PerformanceFlag | None:
    """A shortfall signal needs a verified, contract-document `CONTENT_QUANTITY`
    and a verified `POSTING_FREQUENCY` (confirming the cadence is monthly),
    and the confirmed count must actually be below what the contract
    promises. Equal or higher never produces a signal."""

    if actual_content_count is None:
        return None

    verified_terms = [
        term
        for term in contract_terms
        if term.contract_id == contract_id
        and term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT
        and term.verification_status == VerificationStatus.VERIFIED
        and term.source_page is not None
        and term.source_text is not None
    ]
    quantity_terms = [t for t in verified_terms if t.field == ExtractedField.CONTENT_QUANTITY]
    frequency_terms = [t for t in verified_terms if t.field == ExtractedField.POSTING_FREQUENCY]
    if len(quantity_terms) != 1 or len(frequency_terms) != 1:
        return None
    quantity_term, frequency_term = quantity_terms[0], frequency_terms[0]

    try:
        expected_content_count = int(quantity_term.value)
    except (TypeError, ValueError):
        return None
    if expected_content_count < 1:
        return None
    if actual_content_count >= expected_content_count:
        return None

    return PerformanceFlag(
        id=uuid4(),
        report_revision_id=report_revision_id,
        flag_type=PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL,
        basis_extracted_term_ids=[quantity_term.id, frequency_term.id],
        basis_snapshots=[
            _basis_snapshot(quantity_term, field=ExtractedField.CONTENT_QUANTITY),
            _basis_snapshot(frequency_term, field=ExtractedField.POSTING_FREQUENCY),
        ],
        comparison_report_revision_id=None,
        expected_content_count=expected_content_count,
        expected_period_unit="MONTH",
        actual_content_count=actual_content_count,
        previous_engagement_rate=None,
        current_engagement_rate=None,
        issue_note=None,
        created_at=now,
    )


def build_engagement_rate_drop_flag(
    *,
    report_revision_id: UUID,
    current_period: str,
    current_payload: PerformanceConfirmedPayload,
    previous_report: PerformanceReport | None,
    now: datetime,
) -> PerformanceFlag | None:
    """Only the calendar-immediately-preceding month counts as "전월" — a gap
    (no report, or an unconfirmed one) means no comparison is made at all,
    not a comparison against whatever the latest confirmed month happens to
    be."""

    if previous_report is None or previous_report.current_revision is None:
        return None
    if previous_report.status not in {
        PerformanceReportStatus.CONFIRMED,
        PerformanceReportStatus.FLAGGED,
    }:
        return None
    if not _is_immediately_preceding_month(previous_report.period, current_period):
        return None

    previous_payload = previous_report.current_revision.confirmed_payload
    if (
        current_payload.impressions < _MINIMUM_IMPRESSIONS
        or previous_payload.impressions < _MINIMUM_IMPRESSIONS
    ):
        return None
    if (current_payload.saves is None) != (previous_payload.saves is None):
        return None
    if (current_payload.shares is None) != (previous_payload.shares is None):
        return None

    previous_rate = previous_payload.calculate_engagement_rate()
    current_rate = current_payload.calculate_engagement_rate()
    if previous_rate is None or previous_rate <= 0:
        return None
    if current_rate is None or current_rate >= previous_rate:
        return None

    absolute_drop_points = (previous_rate - current_rate) * 100
    relative_drop_percent = (previous_rate - current_rate) / previous_rate * 100
    if (
        absolute_drop_points < _MINIMUM_ABSOLUTE_DROP_POINTS
        or relative_drop_percent < _MINIMUM_RELATIVE_DROP_PERCENT
    ):
        return None

    return PerformanceFlag(
        id=uuid4(),
        report_revision_id=report_revision_id,
        flag_type=PerformanceFlagType.ENGAGEMENT_RATE_DROP,
        basis_extracted_term_ids=[],
        basis_snapshots=[],
        comparison_report_revision_id=previous_report.current_revision.id,
        expected_content_count=None,
        expected_period_unit=None,
        actual_content_count=None,
        previous_engagement_rate=previous_rate,
        current_engagement_rate=current_rate,
        issue_note=None,
        created_at=now,
    )


def _basis_snapshot(
    term: ExtractedTerm, *, field: ExtractedField
) -> PerformanceFlagBasisSnapshot:
    assert term.source_page is not None
    assert term.source_text is not None
    return PerformanceFlagBasisSnapshot(
        extracted_term_id=term.id,
        document_id=term.document_id,
        field=field,
        source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
        source_page=term.source_page,
        source_text=term.source_text,
        confidence=term.confidence,
        verification_status=VerificationStatus.VERIFIED,
    )


def _is_immediately_preceding_month(previous_period: str, current_period: str) -> bool:
    previous_year, previous_month = (int(part) for part in previous_period.split("-"))
    current_year, current_month = (int(part) for part in current_period.split("-"))
    if previous_month == 12:
        return current_year == previous_year + 1 and current_month == 1
    return current_year == previous_year and current_month == previous_month + 1
