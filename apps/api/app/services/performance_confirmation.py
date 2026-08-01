"""P2-C-3: PATCH .../performance-reports/{report_id} — first confirmation and
append-only correction.

The service builds a fully self-validating `PerformanceReportRevision`
(running the P2-C-2 decision rules and P2-C-5 inquiry-text rendering) and
hands it to the repository's single atomic RPC, which owns the
optimistic-lock (`expected_revision`) and correction-dependency checks under
a row lock. The service never re-implements those checks against a
prior read — a stale read here is exactly the race the lock exists to catch.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.enums import (
    ExtractedField,
    IdempotencyOperation,
    PerformanceFlagType,
    PerformanceReportStatus,
)
from app.core.exceptions import (
    PerformanceReportCorrectionDependencyExists,
    PerformanceReportRevisionConflict,
    ResourceNotFound,
)
from app.domain.performance_flags import (
    build_deliverable_shortfall_flag,
    build_engagement_rate_drop_flag,
)
from app.domain.performance_inquiry import TEMPLATE_VERSION, render_inquiry_draft_text
from app.repositories.analysis import AnalysisRepository
from app.repositories.performance import PerformanceAccessRepository, PerformanceReportRepository
from app.schemas.analysis import ExtractedTerm
from app.schemas.performance import (
    PerformanceConfirmedPayload,
    PerformanceFlag,
    PerformanceInquiryDraft,
    PerformanceReport,
    PerformanceReportConfirmation,
    PerformanceReportConfirmed,
    PerformanceReportRevision,
)
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.performance import PerformanceAccessGuard
from app.services.state_machine import InvalidStatusTransition

_SHORTFALL_BASIS_FIELDS = (ExtractedField.CONTENT_QUANTITY, ExtractedField.POSTING_FREQUENCY)


class PerformanceConfirmationService:
    def __init__(
        self,
        *,
        access_repository: PerformanceAccessRepository,
        confirmation_repository: PerformanceReportRepository,
        analysis_repository: AnalysisRepository,
        idempotency: IdempotencyService,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._access_repository = access_repository
        self._confirmation_repository = confirmation_repository
        self._analysis_repository = analysis_repository
        self._idempotency = idempotency
        self._guard = PerformanceAccessGuard(access_repository)
        self._now = now or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or uuid4

    async def confirm(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        idempotency_key: UUID,
        payload: PerformanceReportConfirmation,
    ) -> PerformanceReportConfirmed:
        async def perform() -> IdempotentOutcome[PerformanceReportConfirmed]:
            confirmed = await self._perform_confirm(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                payload=payload,
            )
            return IdempotentOutcome(
                status_code=200,
                response=confirmed,
                replay_payload=confirmed.model_dump(mode="json"),
            )

        result = await self._idempotency.execute(
            owner_id=owner_id,
            operation=IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM,
            resource_id=report_id,
            key=idempotency_key,
            request_payload=payload,
            perform=perform,
            replay=lambda stored: PerformanceReportConfirmed.model_validate(stored),
        )
        return result.response

    async def _perform_confirm(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        payload: PerformanceReportConfirmation,
    ) -> PerformanceReportConfirmed:
        context = await self._guard.require_report(
            owner_id=owner_id,
            contract_id=contract_id,
            report_id=report_id,
            for_write=True,
        )
        report = context.report
        if report.status == PerformanceReportStatus.UPLOADED:
            raise InvalidStatusTransition(
                "지표를 추출하기 전에는 광고효과 리포트를 확정할 수 없습니다."
            )

        confirmed_at = self._utc_now()
        confirmed_payload = PerformanceConfirmedPayload(**payload.confirmed_payload.model_dump())
        engagement_rate = confirmed_payload.calculate_engagement_rate()
        version = payload.expected_revision + 1
        revision_id = self._id_factory()

        previous_report = await self._get_previous_month_report(
            owner_id=owner_id,
            contract_id=contract_id,
            period=report.period,
        )
        contract_terms = await self._verified_shortfall_terms(
            owner_id=owner_id, contract_id=contract_id
        )

        flags: list[PerformanceFlag] = []
        shortfall_flag = build_deliverable_shortfall_flag(
            contract_id=contract_id,
            report_revision_id=revision_id,
            actual_content_count=confirmed_payload.published_content_count,
            contract_terms=contract_terms,
            now=confirmed_at,
        )
        if shortfall_flag is not None:
            flags.append(shortfall_flag)
        drop_flag = build_engagement_rate_drop_flag(
            report_revision_id=revision_id,
            current_period=report.period,
            current_payload=confirmed_payload,
            previous_report=previous_report,
            now=confirmed_at,
        )
        if drop_flag is not None:
            flags.append(drop_flag)
        if payload.has_issue:
            assert payload.issue_note is not None  # schema-enforced pairing
            flags.append(
                PerformanceFlag(
                    id=self._id_factory(),
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
                    issue_note=payload.issue_note,
                    created_at=confirmed_at,
                )
            )

        inquiry_drafts = [
            PerformanceInquiryDraft(
                id=self._id_factory(),
                flag_id=flag.id,
                text=render_inquiry_draft_text(
                    flag=flag,
                    current_period=report.period,
                    previous_period=(
                        previous_report.period if previous_report is not None else None
                    ),
                ),
                template_version=TEMPLATE_VERSION,
                created_at=confirmed_at,
            )
            for flag in flags
        ]

        revision = PerformanceReportRevision(
            id=revision_id,
            report_id=report_id,
            version=version,
            status=(
                PerformanceReportStatus.FLAGGED if flags else PerformanceReportStatus.CONFIRMED
            ),
            confirmed_payload=confirmed_payload,
            engagement_rate=engagement_rate,
            corrected_from_revision_id=(report.current_revision_id if version > 1 else None),
            correction_reason=payload.correction_reason if version > 1 else None,
            confirmed_at=confirmed_at,
            flags=flags,
            inquiry_drafts=inquiry_drafts,
        )

        result = await self._confirmation_repository.confirm_performance_report_with_audit(
            owner_id=owner_id,
            contract_id=contract_id,
            report_id=report_id,
            expected_revision=payload.expected_revision,
            revision=revision,
        )
        if result.outcome == "REVISION_CONFLICT":
            raise PerformanceReportRevisionConflict()
        if result.outcome == "CORRECTION_DEPENDENCY_EXISTS":
            raise PerformanceReportCorrectionDependencyExists()
        if result.outcome == "INVALID_STATUS":
            raise InvalidStatusTransition(
                "지표를 추출하기 전에는 광고효과 리포트를 확정할 수 없습니다."
            )
        if result.outcome == "NOT_FOUND":
            raise ResourceNotFound()
        if result.report is None:
            raise RuntimeError("광고효과 리포트 확정 결과가 없습니다.")
        return PerformanceReportConfirmed.model_validate(result.report.model_dump())

    async def _get_previous_month_report(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        period: str,
    ) -> PerformanceReport | None:
        previous_period = _immediately_preceding_month(period)
        previous_access = await self._access_repository.get_owned_performance_report_for_period(
            owner_id=owner_id,
            contract_id=contract_id,
            period=previous_period,
        )
        if previous_access is None:
            return None
        return await self._confirmation_repository.get_report(report_id=previous_access.id)

    async def _verified_shortfall_terms(
        self, *, owner_id: UUID, contract_id: UUID
    ) -> Sequence[ExtractedTerm]:
        task = await self._analysis_repository.get_latest_analysis_task(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if task is None or task.result is None:
            return []
        return [
            term for term in task.result.extracted_terms if term.field in _SHORTFALL_BASIS_FIELDS
        ]

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("광고효과 리포트 확정 시각은 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)


def _immediately_preceding_month(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"
