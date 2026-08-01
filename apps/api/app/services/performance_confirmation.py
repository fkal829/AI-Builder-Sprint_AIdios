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
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from app.core.enums import (
    ExtractedField,
    IdempotencyOperation,
    PerformanceFlagType,
    PerformanceReportStatus,
)
from app.core.exceptions import (
    ExternalServiceUnavailable,
    ExternalStorageFailure,
    IdempotencyConflict,
    PerformanceReportCorrectionDependencyExists,
    PerformanceReportPeriodOrderConflict,
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
_CONFIRMATION_ID_NAMESPACE = UUID("e673494a-33dc-4d54-9499-8beadcc1f8da")


class _PerformanceConfirmationRecoveryRequired(ExternalStorageFailure):
    """The atomic confirmation RPC may have committed before its response was lost."""


@dataclass(frozen=True)
class _StoredConfirmationResponse:
    report: PerformanceReportConfirmed
    request_id: str


@dataclass(frozen=True)
class PerformanceConfirmationExecution:
    status_code: int
    report: PerformanceReportConfirmed
    request_id: str
    replayed: bool


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
        request_id: str | None = None,
    ) -> PerformanceConfirmationExecution:
        # A pending idempotency row does not persist the request ID until completion.
        # Derive the logical response ID from the scoped key so a later request can
        # reconstruct the first response after an ambiguous business commit.
        current_request_id = _confirmation_request_id(
            owner_id=owner_id,
            contract_id=contract_id,
            report_id=report_id,
            idempotency_key=idempotency_key,
        )
        revision_id = _confirmation_revision_id(
            owner_id=owner_id,
            contract_id=contract_id,
            report_id=report_id,
            idempotency_key=idempotency_key,
        )

        async def perform() -> IdempotentOutcome[_StoredConfirmationResponse]:
            confirmed = await self._perform_confirm(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                payload=payload,
                revision_id=revision_id,
            )
            return _confirmation_success_outcome(
                confirmed,
                request_id=current_request_id,
            )

        async def recover_pending() -> IdempotentOutcome[_StoredConfirmationResponse] | None:
            return await self._recover_pending_outcome(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                revision_id=revision_id,
                payload=payload,
                request_id=current_request_id,
            )

        try:
            result = await self._idempotency.execute(
                owner_id=owner_id,
                operation=IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM,
                resource_id=report_id,
                key=idempotency_key,
                request_payload=payload,
                perform=perform,
                replay=_stored_confirmation_response_from_payload,
                pending_recovery=recover_pending,
                preserve_pending_exception=lambda error: isinstance(
                    error,
                    _PerformanceConfirmationRecoveryRequired,
                ),
            )
        except ExternalStorageFailure as error:
            raise ExternalServiceUnavailable() from error
        return PerformanceConfirmationExecution(
            status_code=result.status_code,
            report=result.response.report,
            request_id=result.response.request_id,
            replayed=result.replayed,
        )

    async def _perform_confirm(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        payload: PerformanceReportConfirmation,
        revision_id: UUID,
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

        try:
            result = await self._confirmation_repository.confirm_performance_report_with_audit(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                expected_revision=payload.expected_revision,
                expected_comparison_revision_id=(
                    previous_report.current_revision.id
                    if previous_report is not None and previous_report.current_revision is not None
                    else None
                ),
                revision=revision,
            )
        except ExternalStorageFailure as error:
            # The RPC and its follow-up read share one repository method. A
            # transport failure here cannot prove that the atomic append rolled
            # back, so keep the idempotency reservation for deterministic recovery.
            raise _PerformanceConfirmationRecoveryRequired(
                "광고효과 리포트 확정 커밋 상태를 복구해야 합니다."
            ) from error
        if result.outcome in {"REVISION_CONFLICT", "COMPARISON_REVISION_CONFLICT"}:
            raise PerformanceReportRevisionConflict()
        if result.outcome == "CORRECTION_DEPENDENCY_EXISTS":
            raise PerformanceReportCorrectionDependencyExists()
        if result.outcome == "PERIOD_ORDER_CONFLICT":
            raise PerformanceReportPeriodOrderConflict()
        if result.outcome == "CONTRACT_INVALID_STATUS":
            raise InvalidStatusTransition(
                "현재 계약 상태에서는 광고효과 리포트를 확정할 수 없습니다."
            )
        if result.outcome == "REPORT_INVALID_STATUS":
            raise InvalidStatusTransition(
                "지표를 추출하기 전에는 광고효과 리포트를 확정할 수 없습니다."
            )
        if result.outcome == "NOT_FOUND":
            raise ResourceNotFound()
        if result.report is None:
            raise RuntimeError("광고효과 리포트 확정 결과가 없습니다.")
        return PerformanceReportConfirmed.model_validate(result.report.model_dump())

    async def _recover_pending_outcome(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        revision_id: UUID,
        payload: PerformanceReportConfirmation,
        request_id: str,
    ) -> IdempotentOutcome[_StoredConfirmationResponse] | None:
        try:
            reports = await self._confirmation_repository.get_owned_contract_performance_reports(
                owner_id=owner_id,
                contract_id=contract_id,
            )
        except ExternalStorageFailure as error:
            raise _PerformanceConfirmationRecoveryRequired(
                "광고효과 리포트 확정 커밋 상태를 확인할 수 없습니다."
            ) from error
        report = next(
            (candidate for candidate in reports or [] if candidate.id == report_id),
            None,
        )
        if report is None or not _matches_committed_confirmation(
            report,
            contract_id=contract_id,
            report_id=report_id,
            revision_id=revision_id,
            payload=payload,
        ):
            # The original RPC may still be in flight, may have rolled back, or a
            # different correction may already be current. Never execute or replay
            # a different revision while this reservation is pending.
            return None
        return _confirmation_success_outcome(
            PerformanceReportConfirmed.model_validate(report.model_dump()),
            request_id=request_id,
        )

    async def _get_previous_month_report(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        period: str,
    ) -> PerformanceReport | None:
        previous_period = _immediately_preceding_month(period)
        reports = await self._confirmation_repository.get_owned_contract_performance_reports(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        return next(
            (report for report in reports or [] if report.period == previous_period),
            None,
        )

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


def _stored_confirmation_response_payload(
    response: _StoredConfirmationResponse,
) -> dict[str, object]:
    return {
        "report": response.report.model_dump(mode="json"),
        "requestId": response.request_id,
    }


def _stored_confirmation_response_from_payload(
    payload: dict[str, object],
) -> _StoredConfirmationResponse:
    raw_report = payload.get("report")
    stored_request_id = payload.get("requestId")
    if (
        not isinstance(raw_report, dict)
        or not isinstance(stored_request_id, str)
        or not stored_request_id.startswith("req_")
    ):
        raise IdempotencyConflict("저장된 광고효과 리포트 확정 응답이 올바르지 않습니다.")
    return _StoredConfirmationResponse(
        report=PerformanceReportConfirmed.model_validate(raw_report),
        request_id=stored_request_id,
    )


def _confirmation_success_outcome(
    report: PerformanceReportConfirmed,
    *,
    request_id: str,
) -> IdempotentOutcome[_StoredConfirmationResponse]:
    stored = _StoredConfirmationResponse(
        report=report,
        request_id=request_id,
    )
    return IdempotentOutcome(
        status_code=200,
        response=stored,
        replay_payload=_stored_confirmation_response_payload(stored),
    )


def _confirmation_scope(
    *,
    owner_id: UUID,
    contract_id: UUID,
    report_id: UUID,
    idempotency_key: UUID,
) -> str:
    return f"{owner_id}:{contract_id}:{report_id}:{idempotency_key}"


def _confirmation_revision_id(
    *,
    owner_id: UUID,
    contract_id: UUID,
    report_id: UUID,
    idempotency_key: UUID,
) -> UUID:
    scope = _confirmation_scope(
        owner_id=owner_id,
        contract_id=contract_id,
        report_id=report_id,
        idempotency_key=idempotency_key,
    )
    return uuid5(_CONFIRMATION_ID_NAMESPACE, f"{scope}:revision")


def _confirmation_request_id(
    *,
    owner_id: UUID,
    contract_id: UUID,
    report_id: UUID,
    idempotency_key: UUID,
) -> str:
    scope = _confirmation_scope(
        owner_id=owner_id,
        contract_id=contract_id,
        report_id=report_id,
        idempotency_key=idempotency_key,
    )
    return f"req_{uuid5(_CONFIRMATION_ID_NAMESPACE, f'{scope}:request').hex}"


def _matches_committed_confirmation(
    report: PerformanceReport,
    *,
    contract_id: UUID,
    report_id: UUID,
    revision_id: UUID,
    payload: PerformanceReportConfirmation,
) -> bool:
    current = report.current_revision
    expected_version = payload.expected_revision + 1
    expected_payload = PerformanceConfirmedPayload(**payload.confirmed_payload.model_dump())
    if (
        report.id != report_id
        or report.contract_id != contract_id
        or report.revision_count != expected_version
        or current is None
        or current.id != revision_id
        or current.report_id != report_id
        or current.version != expected_version
        or current.status != report.status
        or current.confirmed_payload != expected_payload
        or current.engagement_rate != expected_payload.calculate_engagement_rate()
        or current.correction_reason != payload.correction_reason
    ):
        return False

    if expected_version == 1:
        if current.corrected_from_revision_id is not None:
            return False
    elif len(report.revisions) < 2 or current.corrected_from_revision_id != report.revisions[-2].id:
        return False

    owner_issue_notes = [
        flag.issue_note
        for flag in current.flags
        if flag.flag_type is PerformanceFlagType.OWNER_REPORTED_ISSUE
    ]
    if payload.has_issue:
        return owner_issue_notes == [payload.issue_note]
    return owner_issue_notes == []


def _immediately_preceding_month(period: str) -> str | None:
    year, month = (int(part) for part in period.split("-"))
    if month == 1:
        if year == 1:
            return None
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"
