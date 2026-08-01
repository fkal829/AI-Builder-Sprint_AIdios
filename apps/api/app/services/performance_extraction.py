"""Idempotent orchestration for one explicit performance-report extraction attempt.

The service owns deterministic claim and persistence rules only. Upstage Parse,
Solar mapping, and private-object loading stay behind the injected ``extractor``
callback so this module can be tested without external network calls.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from app.core.enums import IdempotencyOperation, PerformanceReportStatus
from app.core.errors import ErrorCode
from app.core.exceptions import (
    ExternalServiceUnavailable,
    ExternalStorageFailure,
    PerformanceReportExtractFailed,
    PerformanceReportExtractionInProgress,
    ResourceNotFound,
)
from app.repositories.documents import DocumentRecord
from app.repositories.performance import (
    PerformanceExtractionApplyResult,
    PerformanceExtractionClaim,
    PerformanceExtractionRepository,
    PerformanceReportAccess,
)
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.performance import PerformanceExtractedPayload, PerformanceReportExtracted
from app.services.idempotency import (
    IdempotencyService,
    IdempotentOutcome,
)
from app.services.state_machine import InvalidStatusTransition

PERFORMANCE_EXTRACTION_STALE_AFTER = timedelta(minutes=15)

type PerformanceExtractor = Callable[[DocumentRecord], Awaitable[object]]
type _StoredOutcome = Literal["SUCCESS", "FAILED"]


class PerformanceDocumentParseError(RuntimeError):
    """The injected extractor could not parse the source document."""


class PerformanceMetricMappingError(RuntimeError):
    """Solar mapping failed before a strict metric payload was produced."""


class _PerformanceExtractionRecoveryRequired(ExternalStorageFailure):
    """The business commit is uncertain and the idempotency claim must survive."""


@dataclass(frozen=True)
class _StoredExtractionResponse:
    outcome: _StoredOutcome
    report: PerformanceReportExtracted | None
    request_id: str


@dataclass(frozen=True)
class PerformanceReportExtractionExecution:
    status_code: int
    report: PerformanceReportExtracted | None
    error_code: ErrorCode | None
    error_message: str | None
    request_id: str
    replayed: bool

    @property
    def response(self) -> PerformanceReportExtracted | None:
        """Backward-compatible alias used by the extraction foundation tests."""

        return self.report


class PerformanceReportExtractionService:
    """Claim, execute, and atomically apply a user-requested extraction attempt."""

    def __init__(
        self,
        repository: PerformanceExtractionRepository,
        idempotency: IdempotencyService,
        extractor: PerformanceExtractor,
        *,
        now: Callable[[], datetime] | None = None,
        stale_after: timedelta = PERFORMANCE_EXTRACTION_STALE_AFTER,
    ) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("Extraction stale duration must be positive.")
        self._repository = repository
        self._idempotency = idempotency
        self._extractor = extractor
        self._now = now or (lambda: datetime.now(UTC))
        self._stale_after = stale_after

    async def extract(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        idempotency_key: UUID,
        request_id: str | None = None,
    ) -> PerformanceReportExtractionExecution:
        """Run at most one external extraction for the scoped idempotency key.

        A successful response and a terminal ``REPORT_EXTRACT_FAILED`` response are
        persisted for replay. Admission conflicts are not persisted, allowing the
        caller to try again after the active attempt has finished or become stale.
        """

        current_request_id = request_id or f"req_{idempotency_key.hex}"

        async def perform() -> IdempotentOutcome[_StoredExtractionResponse]:
            report_access = await self._perform_extraction(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=idempotency_key,
                idempotency_key=idempotency_key,
            )
            return _success_outcome(
                _extracted_snapshot(report_access),
                request_id=current_request_id,
            )

        def persist_extract_failure(
            error: Exception,
        ) -> IdempotentOutcome[_StoredExtractionResponse] | None:
            if not isinstance(error, PerformanceReportExtractFailed):
                return None
            return _failure_outcome(request_id=current_request_id)

        async def recover_pending() -> IdempotentOutcome[_StoredExtractionResponse] | None:
            return await self._recover_pending_outcome(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=idempotency_key,
                request_id=current_request_id,
            )

        try:
            result = await self._idempotency.execute(
                owner_id=owner_id,
                operation=IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT,
                resource_id=report_id,
                key=idempotency_key,
                request_payload={
                    "contract_id": contract_id,
                    "report_id": report_id,
                },
                perform=perform,
                replay=_stored_response_from_payload,
                exception_outcome=persist_extract_failure,
                pending_recovery=recover_pending,
                preserve_pending_exception=lambda error: isinstance(
                    error,
                    _PerformanceExtractionRecoveryRequired,
                ),
            )
        except ExternalStorageFailure as error:
            raise ExternalServiceUnavailable() from error

        if result.response.outcome == "FAILED":
            raise PerformanceReportExtractFailed(
                request_id=result.response.request_id,
            )
        if result.response.report is None:
            raise RuntimeError("Successful extraction replay is missing its report.")
        return PerformanceReportExtractionExecution(
            status_code=result.status_code,
            report=result.response.report,
            error_code=None,
            error_message=None,
            request_id=result.response.request_id,
            replayed=result.replayed,
        )

    async def _perform_extraction(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        idempotency_key: UUID,
    ) -> PerformanceReportAccess:
        started_at = self._utc_now()
        try:
            claim = await self._repository.claim_performance_report_extraction(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=attempt_id,
                idempotency_key=idempotency_key,
                started_at=started_at,
                stale_before=started_at - self._stale_after,
            )
        except ExternalStorageFailure as error:
            report, source_document = await self._attempt_state(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
            )
            if _is_completed_attempt(report, source_document, attempt_id=attempt_id):
                assert report is not None
                return report
            if _is_processing_attempt(report, source_document, attempt_id=attempt_id):
                assert report is not None and source_document is not None
                claim = PerformanceExtractionClaim(
                    outcome="CLAIMED",
                    report=report,
                    source_document=source_document,
                )
            else:
                raise ExternalServiceUnavailable() from error
        report, source_document = _claimed_context(claim, attempt_id=attempt_id)

        try:
            extracted = await self._extractor(source_document)
            payload = PerformanceExtractedPayload.model_validate(extracted)
        except ExternalStorageFailure as error:
            await self._record_failure(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=attempt_id,
                document_parse_status=DocumentParseStatus.FAILED,
            )
            raise ExternalServiceUnavailable() from error
        except PerformanceDocumentParseError as error:
            await self._record_failure(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=attempt_id,
                document_parse_status=DocumentParseStatus.FAILED,
            )
            raise PerformanceReportExtractFailed() from error
        except (PerformanceMetricMappingError, ValidationError) as error:
            await self._record_failure(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=attempt_id,
                document_parse_status=DocumentParseStatus.COMPLETED,
            )
            raise PerformanceReportExtractFailed() from error
        except Exception as error:
            # The injected boundary must normally classify Parse and mapping
            # failures with the two exceptions above. Still fail closed for an
            # unclassified timeout/adapter error: no verified Parse completion
            # exists, and abandoning the attempt would let the same key call AI
            # again immediately.
            await self._record_failure(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=attempt_id,
                document_parse_status=DocumentParseStatus.FAILED,
            )
            raise PerformanceReportExtractFailed() from error

        try:
            completed = await self._repository.complete_performance_report_extraction(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=attempt_id,
                extracted_payload=payload,
                completed_at=self._utc_now(),
            )
            completed_report = _applied_report(completed)
            if (
                completed_report.status is not PerformanceReportStatus.EXTRACTED
                or completed_report.extracted_payload != payload
                or completed_report.current_revision_id is not None
                or completed_report.revision_count != 0
                or completed_report.extraction_attempt_id != attempt_id
            ):
                raise RuntimeError("Extraction repository returned an invalid completed report.")
            if (
                completed.source_document is not None
                and completed.source_document.parse_status is not DocumentParseStatus.COMPLETED
            ):
                raise RuntimeError("Completed extraction must mark its source document completed.")
            # Claim context is validated before any external callback.
            if report.id != completed_report.id:
                raise RuntimeError("Extraction completion returned a different report.")
        except (
            ResourceNotFound,
            PerformanceReportExtractionInProgress,
            InvalidStatusTransition,
        ):
            raise
        except Exception as error:
            recovered_report, recovered_document = await self._attempt_state(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
            )
            if _is_completed_attempt(
                recovered_report,
                recovered_document,
                attempt_id=attempt_id,
                expected_payload=payload,
            ):
                assert recovered_report is not None
                return recovered_report
            if _is_terminal_failed_attempt(
                recovered_report,
                recovered_document,
                attempt_id=attempt_id,
            ):
                raise PerformanceReportExtractFailed() from error
            raise _PerformanceExtractionRecoveryRequired(
                "성과 추출 완료 저장 결과를 안전하게 확인할 수 없습니다."
            ) from error
        return completed_report

    async def _record_failure(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        document_parse_status: DocumentParseStatus,
    ) -> None:
        try:
            failed = await self._repository.fail_performance_report_extraction(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=attempt_id,
                document_parse_status=document_parse_status,
                failed_at=self._utc_now(),
            )
            failed_report = _applied_report(failed)
            if (
                failed_report.status is not PerformanceReportStatus.UPLOADED
                or failed_report.extracted_payload is not None
                or failed_report.current_revision_id is not None
                or failed_report.revision_count != 0
                or failed_report.extraction_attempt_id != attempt_id
            ):
                raise RuntimeError("Extraction repository returned an invalid failed report.")
            if (
                failed.source_document is not None
                and failed.source_document.parse_status is not document_parse_status
            ):
                raise RuntimeError("Extraction failure stored the wrong document parse status.")
        except (
            ResourceNotFound,
            PerformanceReportExtractionInProgress,
            InvalidStatusTransition,
        ):
            raise
        except Exception as error:
            recovered_report, recovered_document = await self._attempt_state(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
            )
            if _is_failed_attempt(
                recovered_report,
                recovered_document,
                attempt_id=attempt_id,
                document_parse_status=document_parse_status,
            ):
                return
            raise _PerformanceExtractionRecoveryRequired(
                "성과 추출 실패 상태의 저장 결과를 안전하게 확인할 수 없습니다."
            ) from error

    async def _recover_pending_outcome(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        request_id: str,
    ) -> IdempotentOutcome[_StoredExtractionResponse] | None:
        report, source_document = await self._attempt_state(
            owner_id=owner_id,
            contract_id=contract_id,
            report_id=report_id,
        )
        if _is_completed_attempt(report, source_document, attempt_id=attempt_id):
            assert report is not None
            return _success_outcome(
                _extracted_snapshot(report),
                request_id=request_id,
            )
        if _is_terminal_failed_attempt(report, source_document, attempt_id=attempt_id):
            return _failure_outcome(request_id=request_id)
        # A PROCESSING attempt may still be executing in another request. Never
        # re-run AI or overwrite it merely because the idempotency poll elapsed.
        return None

    async def _attempt_state(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
    ) -> tuple[PerformanceReportAccess | None, DocumentRecord | None]:
        try:
            report = await self._repository.get_owned_performance_report(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
            )
            if report is None:
                return None, None
            source_document = await self._repository.get_owned_performance_source_document(
                owner_id=owner_id,
                contract_id=contract_id,
                document_id=report.source_document_id,
            )
        except ExternalStorageFailure as error:
            raise _PerformanceExtractionRecoveryRequired(
                "성과 추출 상태를 안전하게 확인할 수 없습니다."
            ) from error
        return report, source_document

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Performance extraction timestamps must be timezone-aware.")
        return value.astimezone(UTC)


def _claimed_context(
    claim: PerformanceExtractionClaim,
    *,
    attempt_id: UUID,
) -> tuple[PerformanceReportAccess, DocumentRecord]:
    if claim.outcome == "NOT_FOUND":
        raise ResourceNotFound()
    if claim.outcome == "IN_PROGRESS":
        raise PerformanceReportExtractionInProgress()
    if claim.outcome == "INVALID_STATUS":
        raise InvalidStatusTransition("UPLOADED 리포트만 지표를 추출할 수 있습니다.")
    if claim.outcome not in {"CLAIMED", "RECOVERED"}:
        raise RuntimeError("Unknown performance extraction claim outcome.")
    if claim.report is None or claim.source_document is None:
        raise RuntimeError("Claimed extraction is missing its report or source document.")

    report = claim.report
    document = claim.source_document
    if (
        report.status is not PerformanceReportStatus.UPLOADED
        or report.extracted_payload is not None
        or report.current_revision_id is not None
        or report.revision_count != 0
        or report.extraction_attempt_id != attempt_id
        or report.extraction_started_at is None
    ):
        raise RuntimeError("Extraction repository returned an invalid claim report.")
    if (
        document.id != report.source_document_id
        or document.contract_id != report.contract_id
        or document.type is not DocumentType.PERFORMANCE_REPORT
        or document.parse_status is not DocumentParseStatus.PROCESSING
    ):
        raise RuntimeError("Extraction repository returned an invalid source document.")
    return report, document


def _applied_report(result: PerformanceExtractionApplyResult) -> PerformanceReportAccess:
    if result.outcome == "NOT_FOUND":
        raise ResourceNotFound()
    if result.outcome == "STALE":
        raise PerformanceReportExtractionInProgress()
    if result.outcome == "INVALID_STATUS":
        raise InvalidStatusTransition("현재 리포트 상태에서 추출 결과를 저장할 수 없습니다.")
    if result.outcome != "APPLIED":
        raise RuntimeError("Unknown performance extraction apply outcome.")
    if result.report is None:
        raise RuntimeError("Applied extraction is missing its report.")
    return result.report


def _is_completed_attempt(
    report: PerformanceReportAccess | None,
    source_document: DocumentRecord | None,
    *,
    attempt_id: UUID,
    expected_payload: PerformanceExtractedPayload | None = None,
) -> bool:
    return bool(
        report is not None
        and source_document is not None
        and report.status is PerformanceReportStatus.EXTRACTED
        and report.extracted_payload is not None
        and (expected_payload is None or report.extracted_payload == expected_payload)
        and report.current_revision_id is None
        and report.revision_count == 0
        and report.extraction_attempt_id == attempt_id
        and source_document.id == report.source_document_id
        and source_document.contract_id == report.contract_id
        and source_document.type is DocumentType.PERFORMANCE_REPORT
        and source_document.parse_status is DocumentParseStatus.COMPLETED
    )


def _is_processing_attempt(
    report: PerformanceReportAccess | None,
    source_document: DocumentRecord | None,
    *,
    attempt_id: UUID,
) -> bool:
    return bool(
        report is not None
        and source_document is not None
        and report.status is PerformanceReportStatus.UPLOADED
        and report.extracted_payload is None
        and report.current_revision_id is None
        and report.revision_count == 0
        and report.extraction_attempt_id == attempt_id
        and source_document.id == report.source_document_id
        and source_document.contract_id == report.contract_id
        and source_document.type is DocumentType.PERFORMANCE_REPORT
        and source_document.parse_status is DocumentParseStatus.PROCESSING
    )


def _is_failed_attempt(
    report: PerformanceReportAccess | None,
    source_document: DocumentRecord | None,
    *,
    attempt_id: UUID,
    document_parse_status: DocumentParseStatus,
) -> bool:
    return bool(
        report is not None
        and source_document is not None
        and report.status is PerformanceReportStatus.UPLOADED
        and report.extracted_payload is None
        and report.current_revision_id is None
        and report.revision_count == 0
        and report.extraction_attempt_id == attempt_id
        and source_document.id == report.source_document_id
        and source_document.contract_id == report.contract_id
        and source_document.type is DocumentType.PERFORMANCE_REPORT
        and source_document.parse_status is document_parse_status
    )


def _is_terminal_failed_attempt(
    report: PerformanceReportAccess | None,
    source_document: DocumentRecord | None,
    *,
    attempt_id: UUID,
) -> bool:
    return any(
        _is_failed_attempt(
            report,
            source_document,
            attempt_id=attempt_id,
            document_parse_status=status,
        )
        for status in (DocumentParseStatus.FAILED, DocumentParseStatus.COMPLETED)
    )


def _extracted_snapshot(report: PerformanceReportAccess) -> PerformanceReportExtracted:
    if (
        report.status is not PerformanceReportStatus.EXTRACTED
        or report.extracted_payload is None
        or report.current_revision_id is not None
        or report.revision_count != 0
        or report.created_at is None
        or report.updated_at is None
    ):
        raise _PerformanceExtractionRecoveryRequired(
            "성과 추출 결과의 공개 snapshot이 완전하지 않습니다."
        )
    return PerformanceReportExtracted(
        id=report.id,
        contract_id=report.contract_id,
        period=report.period,
        source_document_id=report.source_document_id,
        status=PerformanceReportStatus.EXTRACTED,
        extracted_payload=report.extracted_payload,
        current_revision=None,
        revision_count=0,
        revisions=[],
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _success_outcome(
    report: PerformanceReportExtracted,
    *,
    request_id: str,
) -> IdempotentOutcome[_StoredExtractionResponse]:
    stored = _StoredExtractionResponse(
        outcome="SUCCESS",
        report=report,
        request_id=request_id,
    )
    return IdempotentOutcome(
        status_code=200,
        response=stored,
        replay_payload=_stored_response_payload(stored),
    )


def _failure_outcome(*, request_id: str) -> IdempotentOutcome[_StoredExtractionResponse]:
    stored = _StoredExtractionResponse(
        outcome="FAILED",
        report=None,
        request_id=request_id,
    )
    return IdempotentOutcome(
        status_code=502,
        response=stored,
        replay_payload=_stored_response_payload(stored),
    )


def _stored_response_payload(response: _StoredExtractionResponse) -> dict[str, Any]:
    if response.outcome == "FAILED":
        return {
            "outcome": "FAILED",
            "error_code": ErrorCode.REPORT_EXTRACT_FAILED.value,
            "request_id": response.request_id,
        }
    if response.report is None:
        raise RuntimeError("Successful extraction is missing its report.")
    return {
        "outcome": "SUCCESS",
        "report": response.report.model_dump(mode="json"),
        "request_id": response.request_id,
    }


def _stored_response_from_payload(payload: dict[str, Any]) -> _StoredExtractionResponse:
    outcome = payload.get("outcome")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("Stored extraction request ID is invalid.")
    if outcome == "FAILED":
        if payload.get("error_code") != ErrorCode.REPORT_EXTRACT_FAILED.value:
            raise ValueError("Stored extraction failure code is invalid.")
        return _StoredExtractionResponse(
            outcome="FAILED",
            report=None,
            request_id=request_id,
        )
    if outcome != "SUCCESS" or not isinstance(payload.get("report"), Mapping):
        raise ValueError("Stored extraction response is invalid.")
    return _StoredExtractionResponse(
        outcome="SUCCESS",
        report=PerformanceReportExtracted.model_validate(payload["report"]),
        request_id=request_id,
    )
