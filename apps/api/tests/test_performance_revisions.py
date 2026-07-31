"""P2-C-1: append-only persistence of `PerformanceReportRevision` history.

The schema itself (version sequencing, `corrected_from_revision_id` chain,
flag/inquiry-draft pairing, current-revision correctness) comes from the P2-0
common-contract PR and is already exhaustively covered by
`test_performance_contract.py`. This file exercises the one thing that's
P2-C's own concern: a repository that appends a new revision without ever
mutating a previously stored one, and that re-validates the whole
`PerformanceReport` projection on every write. `PerformanceReport` upload/
extraction itself is P2-B's territory and isn't exercised here.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.enums import (
    PerformanceFlagType,
    PerformanceMetricVerificationStatus,
    PerformanceReportStatus,
)
from app.repositories.performance import PerformanceReportRepository
from app.schemas.performance import (
    PerformanceConfirmedPayload,
    PerformanceExtractedPayload,
    PerformanceFlag,
    PerformanceInquiryDraft,
    PerformanceNonNegativeMetricCandidate,
    PerformanceReport,
    PerformanceReportRevision,
    PerformanceSignedMetricCandidate,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)
CONTRACT_ID = uuid4()
SOURCE_DOCUMENT_ID = uuid4()


class InMemoryPerformanceReportRepository(PerformanceReportRepository):
    def __init__(self, report: PerformanceReport) -> None:
        self._reports: dict[UUID, PerformanceReport] = {report.id: report}

    async def get_report(self, *, report_id: UUID) -> PerformanceReport | None:
        return self._reports.get(report_id)

    async def append_revision(
        self, *, report_id: UUID, revision: PerformanceReportRevision
    ) -> PerformanceReport:
        report = self._reports[report_id]
        revisions = [*report.revisions, revision]
        # Reconstruct through the constructor (not `model_copy`) so every
        # append re-runs `PerformanceReport.validate_report_projection` —
        # a corrupt append is rejected the same way a corrupt fresh object
        # would be.
        updated = PerformanceReport(
            id=report.id,
            contract_id=report.contract_id,
            period=report.period,
            source_document_id=report.source_document_id,
            status=revision.status,
            extracted_payload=report.extracted_payload,
            current_revision=revision,
            revision_count=len(revisions),
            revisions=revisions,
            created_at=report.created_at,
            updated_at=revision.confirmed_at,
        )
        self._reports[report_id] = updated
        return updated


def make_extracted_payload_candidate(value: int | None, *, signed: bool = False):
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


def make_report(*, report_id: UUID | None = None, period: str = "2026-07") -> PerformanceReport:
    extracted = PerformanceExtractedPayload(
        impressions=make_extracted_payload_candidate(10_000),
        likes=make_extracted_payload_candidate(300),
        comments=make_extracted_payload_candidate(20),
        reach=make_extracted_payload_candidate(None),
        saves=make_extracted_payload_candidate(None),
        shares=make_extracted_payload_candidate(None),
        follower_net_change=make_extracted_payload_candidate(None, signed=True),
        published_content_count=make_extracted_payload_candidate(None),
    )
    return PerformanceReport(
        id=report_id or uuid4(),
        contract_id=CONTRACT_ID,
        period=period,
        source_document_id=SOURCE_DOCUMENT_ID,
        status=PerformanceReportStatus.EXTRACTED,
        extracted_payload=extracted,
        current_revision=None,
        revision_count=0,
        revisions=[],
        created_at=NOW,
        updated_at=NOW,
    )


def make_confirmed_payload(**overrides) -> PerformanceConfirmedPayload:
    values = {
        "impressions": 10_000,
        "likes": 300,
        "comments": 20,
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


def make_owner_issue_flag(*, revision_id: UUID, note: str = "숫자가 이상해요") -> PerformanceFlag:
    return PerformanceFlag(
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
        issue_note=note,
        created_at=NOW,
    )


def make_inquiry_draft(
    *, flag_id: UUID, text: str = "확인 부탁드립니다."
) -> PerformanceInquiryDraft:
    return PerformanceInquiryDraft(
        id=uuid4(),
        flag_id=flag_id,
        text=text,
        template_version="performance-inquiry-copy-v1",
        created_at=NOW,
    )


def make_revision(
    *,
    report_id: UUID,
    version: int,
    revision_id: UUID | None = None,
    corrected_from_revision_id: UUID | None = None,
    correction_reason: str | None = None,
    flags: tuple[PerformanceFlag, ...] = (),
    inquiry_drafts: tuple[PerformanceInquiryDraft, ...] = (),
    payload: PerformanceConfirmedPayload | None = None,
) -> PerformanceReportRevision:
    payload = payload or make_confirmed_payload()
    status = (
        PerformanceReportStatus.FLAGGED if flags else PerformanceReportStatus.CONFIRMED
    )
    return PerformanceReportRevision(
        id=revision_id or uuid4(),
        report_id=report_id,
        version=version,
        status=status,
        confirmed_payload=payload,
        engagement_rate=payload.calculate_engagement_rate(),
        corrected_from_revision_id=corrected_from_revision_id,
        correction_reason=correction_reason,
        confirmed_at=NOW,
        flags=list(flags),
        inquiry_drafts=list(inquiry_drafts),
    )


async def test_initial_report_has_no_revisions() -> None:
    report = make_report()
    repo = InMemoryPerformanceReportRepository(report)

    fetched = await repo.get_report(report_id=report.id)

    assert fetched is not None
    assert fetched.revision_count == 0
    assert fetched.current_revision is None


async def test_first_confirmation_becomes_current_revision() -> None:
    report = make_report()
    repo = InMemoryPerformanceReportRepository(report)
    v1 = make_revision(report_id=report.id, version=1)

    updated = await repo.append_revision(report_id=report.id, revision=v1)

    assert updated.status == PerformanceReportStatus.CONFIRMED
    assert updated.current_revision == v1
    assert updated.revision_count == 1


async def test_correction_appends_without_mutating_prior_history() -> None:
    report = make_report()
    repo = InMemoryPerformanceReportRepository(report)
    v1 = make_revision(
        report_id=report.id,
        version=1,
        payload=make_confirmed_payload(impressions=10_000, likes=300),
    )
    await repo.append_revision(report_id=report.id, revision=v1)

    # A flag belongs to the revision it's raised on, so its id must be known
    # before the flag (and the draft that cites it) can be built.
    v2_id = uuid4()
    flag_for_v2 = make_owner_issue_flag(revision_id=v2_id)
    draft_for_v2 = make_inquiry_draft(flag_id=flag_for_v2.id)
    v2 = make_revision(
        report_id=report.id,
        version=2,
        revision_id=v2_id,
        corrected_from_revision_id=v1.id,
        correction_reason="노출 수 오타 수정",
        payload=make_confirmed_payload(impressions=12_500, likes=430),
        flags=(flag_for_v2,),
        inquiry_drafts=(draft_for_v2,),
    )

    updated = await repo.append_revision(report_id=report.id, revision=v2)

    assert [r.version for r in updated.revisions] == [1, 2]
    assert updated.revisions[0] == v1
    assert updated.revisions[0].confirmed_payload.impressions == 10_000
    assert updated.current_revision == v2
    assert updated.current_revision.confirmed_payload.impressions == 12_500
    assert updated.status == PerformanceReportStatus.FLAGGED


async def test_skipping_a_version_number_is_rejected() -> None:
    report = make_report()
    repo = InMemoryPerformanceReportRepository(report)
    v1 = make_revision(report_id=report.id, version=1)
    await repo.append_revision(report_id=report.id, revision=v1)

    v3 = make_revision(
        report_id=report.id,
        version=3,
        corrected_from_revision_id=v1.id,
        correction_reason="버전을 건너뛴 정정 시도",
    )

    with pytest.raises(ValidationError):
        await repo.append_revision(report_id=report.id, revision=v3)


async def test_correction_must_reference_the_actual_previous_revision() -> None:
    report = make_report()
    repo = InMemoryPerformanceReportRepository(report)
    v1 = make_revision(report_id=report.id, version=1)
    await repo.append_revision(report_id=report.id, revision=v1)

    v2_with_wrong_parent = make_revision(
        report_id=report.id,
        version=2,
        corrected_from_revision_id=uuid4(),
        correction_reason="엉뚱한 revision을 이전 버전으로 참조",
    )

    with pytest.raises(ValidationError):
        await repo.append_revision(report_id=report.id, revision=v2_with_wrong_parent)
