"""P2-C-1: PerformanceReportRevision/Flag/InquiryDraft data model.

`PerformanceReport` itself is P2-B's schema and hasn't landed yet, so this
exercises the P2-C-owned shapes and the append-only invariant against an
in-memory fake of `PerformanceRevisionRepository` (see task_separation.md's
P2-B/P2-C parallel development notes).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.enums import PerformanceFlagType, PerformanceRevisionStatus
from app.repositories.performance import PerformanceRevisionRepository
from app.schemas.performance import (
    INQUIRY_TEMPLATE_VERSION,
    PerformanceFlag,
    PerformanceFlagBasisTerm,
    PerformanceInquiryDraft,
    PerformanceMetrics,
    PerformanceReportRevision,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)
REPORT_ID = uuid4()


class InMemoryPerformanceRevisionRepository(PerformanceRevisionRepository):
    def __init__(self) -> None:
        self._revisions: dict[UUID, list[PerformanceReportRevision]] = {}
        self._flags_by_revision: dict[UUID, list[PerformanceFlag]] = {}
        self._inquiry_drafts_by_flag: dict[UUID, PerformanceInquiryDraft] = {}
        self._current_revision_id: dict[UUID, UUID] = {}

    async def append_revision(
        self,
        *,
        revision: PerformanceReportRevision,
        flags: Sequence[PerformanceFlag],
        inquiry_drafts: Sequence[PerformanceInquiryDraft],
    ) -> PerformanceReportRevision:
        self._revisions.setdefault(revision.report_id, []).append(revision)
        self._flags_by_revision[revision.id] = list(flags)
        for draft in inquiry_drafts:
            self._inquiry_drafts_by_flag[draft.flag_id] = draft
        self._current_revision_id[revision.report_id] = revision.id
        return revision

    async def get_current_revision(
        self, *, report_id: UUID
    ) -> PerformanceReportRevision | None:
        current_id = self._current_revision_id.get(report_id)
        if current_id is None:
            return None
        return next(
            r for r in self._revisions[report_id] if r.id == current_id
        )

    async def list_revisions(
        self, *, report_id: UUID
    ) -> Sequence[PerformanceReportRevision]:
        return tuple(
            sorted(self._revisions.get(report_id, []), key=lambda r: r.version)
        )

    async def list_flags_for_revision(
        self, *, report_revision_id: UUID
    ) -> Sequence[PerformanceFlag]:
        return tuple(self._flags_by_revision.get(report_revision_id, []))

    async def get_inquiry_draft(
        self, *, flag_id: UUID
    ) -> PerformanceInquiryDraft | None:
        return self._inquiry_drafts_by_flag.get(flag_id)


def make_metrics(**overrides) -> PerformanceMetrics:
    values = {"impressions": 10_000, "likes": 300, "comments": 20}
    values.update(overrides)
    return PerformanceMetrics(**values)


def make_revision(
    *,
    version: int,
    status: PerformanceRevisionStatus = PerformanceRevisionStatus.CONFIRMED,
    corrected_from_revision_id: UUID | None = None,
    correction_reason: str | None = None,
    metrics: PerformanceMetrics | None = None,
) -> PerformanceReportRevision:
    return PerformanceReportRevision(
        id=uuid4(),
        report_id=REPORT_ID,
        version=version,
        confirmed_payload=metrics or make_metrics(),
        engagement_rate=None,
        status=status,
        corrected_from_revision_id=corrected_from_revision_id,
        correction_reason=correction_reason,
        confirmed_at=NOW,
    )


def make_basis_term(**overrides) -> PerformanceFlagBasisTerm:
    values = {
        "extracted_term_id": uuid4(),
        "document_id": uuid4(),
        "source_page": 2,
        "source_text": "월 4건의 콘텐츠를 게시한다.",
        "confidence": 0.95,
    }
    values.update(overrides)
    return PerformanceFlagBasisTerm(**values)


def test_first_confirmation_creates_version_1() -> None:
    revision = make_revision(version=1)
    assert revision.corrected_from_revision_id is None
    assert revision.correction_reason is None


def test_version_1_rejects_correction_fields() -> None:
    with pytest.raises(ValidationError):
        make_revision(
            version=1,
            corrected_from_revision_id=uuid4(),
            correction_reason="오타 수정",
        )


def test_version_2_requires_correction_fields() -> None:
    with pytest.raises(ValidationError):
        make_revision(version=2)
    with pytest.raises(ValidationError):
        make_revision(version=2, corrected_from_revision_id=uuid4())
    with pytest.raises(ValidationError):
        make_revision(version=2, correction_reason="")


def test_deliverable_shortfall_flag_requires_two_basis_terms_and_quantity() -> None:
    with pytest.raises(ValidationError):
        PerformanceFlag(
            id=uuid4(),
            report_revision_id=uuid4(),
            flag_type=PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL,
            basis_terms=(make_basis_term(),),
            expected_quantity=4,
            expected_quantity_unit="건",
            created_at=NOW,
        )
    with pytest.raises(ValidationError):
        PerformanceFlag(
            id=uuid4(),
            report_revision_id=uuid4(),
            flag_type=PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL,
            basis_terms=(make_basis_term(), make_basis_term()),
            created_at=NOW,
        )
    flag = PerformanceFlag(
        id=uuid4(),
        report_revision_id=uuid4(),
        flag_type=PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL,
        basis_terms=(make_basis_term(), make_basis_term()),
        expected_quantity=4,
        expected_quantity_unit="건",
        created_at=NOW,
    )
    assert len(flag.basis_terms) == 2


def test_engagement_rate_drop_flag_forbids_basis_terms_and_requires_comparison() -> None:
    with pytest.raises(ValidationError):
        PerformanceFlag(
            id=uuid4(),
            report_revision_id=uuid4(),
            flag_type=PerformanceFlagType.ENGAGEMENT_RATE_DROP,
            basis_terms=(make_basis_term(),),
            comparison_report_revision_id=uuid4(),
            created_at=NOW,
        )
    with pytest.raises(ValidationError):
        PerformanceFlag(
            id=uuid4(),
            report_revision_id=uuid4(),
            flag_type=PerformanceFlagType.ENGAGEMENT_RATE_DROP,
            created_at=NOW,
        )
    flag = PerformanceFlag(
        id=uuid4(),
        report_revision_id=uuid4(),
        flag_type=PerformanceFlagType.ENGAGEMENT_RATE_DROP,
        comparison_report_revision_id=uuid4(),
        created_at=NOW,
    )
    assert flag.basis_terms == ()


def test_owner_reported_issue_requires_note_and_forbids_others() -> None:
    with pytest.raises(ValidationError):
        PerformanceFlag(
            id=uuid4(),
            report_revision_id=uuid4(),
            flag_type=PerformanceFlagType.OWNER_REPORTED_ISSUE,
            created_at=NOW,
        )
    with pytest.raises(ValidationError):
        PerformanceFlag(
            id=uuid4(),
            report_revision_id=uuid4(),
            flag_type=PerformanceFlagType.OWNER_REPORTED_ISSUE,
            owner_issue_note="숫자가 이상해요",
            basis_terms=(make_basis_term(),),
            created_at=NOW,
        )
    flag = PerformanceFlag(
        id=uuid4(),
        report_revision_id=uuid4(),
        flag_type=PerformanceFlagType.OWNER_REPORTED_ISSUE,
        owner_issue_note="숫자가 이상해요",
        created_at=NOW,
    )
    assert flag.owner_issue_note == "숫자가 이상해요"


def test_metrics_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PerformanceMetrics(impressions=1, likes=0, comments=0, ctr=0.5)


async def test_correction_appends_new_version_without_mutating_previous() -> None:
    repo = InMemoryPerformanceRevisionRepository()
    v1 = make_revision(version=1, metrics=make_metrics(impressions=10_000, likes=300))
    await repo.append_revision(revision=v1, flags=(), inquiry_drafts=())

    v2 = make_revision(
        version=2,
        corrected_from_revision_id=v1.id,
        correction_reason="노출 수 오타 수정",
        metrics=make_metrics(impressions=12_500, likes=430),
    )
    await repo.append_revision(revision=v2, flags=(), inquiry_drafts=())

    history = await repo.list_revisions(report_id=REPORT_ID)
    assert [r.version for r in history] == [1, 2]
    assert history[0] == v1
    assert history[0].confirmed_payload.impressions == 10_000

    current = await repo.get_current_revision(report_id=REPORT_ID)
    assert current == v2
    assert current.confirmed_payload.impressions == 12_500


async def test_flags_and_inquiry_drafts_stay_scoped_to_their_own_revision() -> None:
    repo = InMemoryPerformanceRevisionRepository()
    v1 = make_revision(version=1, status=PerformanceRevisionStatus.FLAGGED)
    v1_flag = PerformanceFlag(
        id=uuid4(),
        report_revision_id=v1.id,
        flag_type=PerformanceFlagType.OWNER_REPORTED_ISSUE,
        owner_issue_note="v1에서만 있었던 이상 신고",
        created_at=NOW,
    )
    v1_draft = PerformanceInquiryDraft(
        flag_id=v1_flag.id,
        text=(
            f"{NOW.date().isoformat()} 리포트와 관련해 다음 내용을 확인하고 싶습니다: "
            "v1에서만 있었던 이상 신고 관련 수치와 집계 기준을 확인 부탁드립니다."
        ),
        created_at=NOW,
    )
    await repo.append_revision(revision=v1, flags=(v1_flag,), inquiry_drafts=(v1_draft,))

    v2 = make_revision(
        version=2,
        status=PerformanceRevisionStatus.CONFIRMED,
        corrected_from_revision_id=v1.id,
        correction_reason="이상 신고 철회, 수치 재확인 완료",
    )
    await repo.append_revision(revision=v2, flags=(), inquiry_drafts=())

    v1_flags = await repo.list_flags_for_revision(report_revision_id=v1.id)
    v2_flags = await repo.list_flags_for_revision(report_revision_id=v2.id)
    assert v1_flags == (v1_flag,)
    assert v2_flags == ()

    draft = await repo.get_inquiry_draft(flag_id=v1_flag.id)
    assert draft == v1_draft
    assert draft.template_version == INQUIRY_TEMPLATE_VERSION
