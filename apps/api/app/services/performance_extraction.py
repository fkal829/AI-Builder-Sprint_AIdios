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
from app.schemas.performance import PerformanceExtractedPayload
from app.services.idempotency import (
    IdempotencyService,
    IdempotentOutcome,
    IdempotentResult,
)
from app.services.state_machine import InvalidStatusTransition

PERFORMANCE_EXTRACTION_STALE_AFTER = timedelta(minutes=15)

type PerformanceExtractor = Callable[[DocumentRecord], Awaitable[object]]
type _StoredOutcome = Literal["SUCCESS", "FAILED"]


class PerformanceDocumentParseError(RuntimeError):
    """The injected extractor could not parse the source document."""


class PerformanceMetricMappingError(RuntimeError):
    """Solar mapping failed before a strict metric payload was produced."""


@dataclass(frozen=True)
class _StoredExtractionResponse:
    outcome: _StoredOutcome
    report: PerformanceReportAccess | None


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
    ) -> IdempotentResult[PerformanceReportAccess]:
        """Run at most one external extraction for the scoped idempotency key.

        A successful response and a terminal ``REPORT_EXTRACT_FAILED`` response are
        persisted for replay. Admission conflicts are not persisted, allowing the
        caller to try again after the active attempt has finished or become stale.
        """

        async def perform() -> IdempotentOutcome[_StoredExtractionResponse]:
            report = await self._perform_extraction(
                owner_id=owner_id,
                contract_id=contract_id,
                report_id=report_id,
                attempt_id=idempotency_key,
                idempotency_key=idempotency_key,
            )
            stored = _StoredExtractionResponse(outcome="SUCCESS", report=report)
            return IdempotentOutcome(
                status_code=200,
                response=stored,
                replay_payload=_stored_response_payload(stored),
            )

        def persist_extract_failure(
            error: Exception,
        ) -> IdempotentOutcome[_StoredExtractionResponse] | None:
            if not isinstance(error, PerformanceReportExtractFailed):
                return None
            stored = _StoredExtractionResponse(outcome="FAILED", report=None)
            return IdempotentOutcome(
                status_code=error.status_code,
                response=stored,
                replay_payload=_stored_response_payload(stored),
            )

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
        )
        if result.response.outcome == "FAILED":
            raise PerformanceReportExtractFailed()
        if result.response.report is None:
            raise RuntimeError("Successful extraction replay is missing its report.")
        return IdempotentResult(
            status_code=result.status_code,
            response=result.response.report,
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
        claim = await self._repository.claim_performance_report_extraction(
            owner_id=owner_id,
            contract_id=contract_id,
            report_id=report_id,
            attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            started_at=started_at,
            stale_before=started_at - self._stale_after,
        )
        report, source_document = _claimed_context(claim, attempt_id=attempt_id)

        try:
            extracted = await self._extractor(source_document)
            payload = PerformanceExtractedPayload.model_validate(extracted)
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
        except Exception as error:
            # External extraction already ran. Persist a replayable terminal
            # response instead of abandoning the key and running AI again.
            raise PerformanceReportExtractFailed() from error
        try:
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
                and completed.source_document.parse_status
                is not DocumentParseStatus.COMPLETED
            ):
                raise RuntimeError(
                    "Completed extraction must mark its source document completed."
                )
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
            raise PerformanceReportExtractFailed() from error
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
        except Exception as error:
            raise PerformanceReportExtractFailed() from error
        try:
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
            raise PerformanceReportExtractFailed() from error

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


def _stored_response_payload(response: _StoredExtractionResponse) -> dict[str, Any]:
    if response.outcome == "FAILED":
        return {
            "outcome": "FAILED",
            "error_code": ErrorCode.REPORT_EXTRACT_FAILED.value,
        }
    if response.report is None:
        raise RuntimeError("Successful extraction is missing its report.")
    return {
        "outcome": "SUCCESS",
        "report": _report_replay_payload(response.report),
    }


def _stored_response_from_payload(payload: dict[str, Any]) -> _StoredExtractionResponse:
    outcome = payload.get("outcome")
    if outcome == "FAILED":
        if payload.get("error_code") != ErrorCode.REPORT_EXTRACT_FAILED.value:
            raise ValueError("Stored extraction failure code is invalid.")
        return _StoredExtractionResponse(outcome="FAILED", report=None)
    if outcome != "SUCCESS" or not isinstance(payload.get("report"), Mapping):
        raise ValueError("Stored extraction response is invalid.")
    return _StoredExtractionResponse(
        outcome="SUCCESS",
        report=_report_from_replay_payload(payload["report"]),
    )


def _report_replay_payload(report: PerformanceReportAccess) -> dict[str, Any]:
    return {
        "id": str(report.id),
        "contract_id": str(report.contract_id),
        "period": report.period,
        "source_document_id": str(report.source_document_id),
        "status": report.status.value,
        "extracted_payload": (
            report.extracted_payload.model_dump(mode="json")
            if report.extracted_payload is not None
            else None
        ),
        "current_revision_id": (
            str(report.current_revision_id) if report.current_revision_id is not None else None
        ),
        "revision_count": report.revision_count,
        "extraction_attempt_id": (
            str(report.extraction_attempt_id)
            if report.extraction_attempt_id is not None
            else None
        ),
        "extraction_started_at": _datetime_payload(report.extraction_started_at),
        "created_at": _datetime_payload(report.created_at),
        "updated_at": _datetime_payload(report.updated_at),
    }


def _report_from_replay_payload(payload: Mapping[str, Any]) -> PerformanceReportAccess:
    extracted = payload.get("extracted_payload")
    return PerformanceReportAccess(
        id=UUID(str(payload["id"])),
        contract_id=UUID(str(payload["contract_id"])),
        period=str(payload["period"]),
        source_document_id=UUID(str(payload["source_document_id"])),
        status=PerformanceReportStatus(str(payload["status"])),
        extracted_payload=(
            PerformanceExtractedPayload.model_validate(extracted)
            if extracted is not None
            else None
        ),
        current_revision_id=(
            UUID(str(payload["current_revision_id"]))
            if payload.get("current_revision_id") is not None
            else None
        ),
        revision_count=int(payload["revision_count"]),
        extraction_attempt_id=(
            UUID(str(payload["extraction_attempt_id"]))
            if payload.get("extraction_attempt_id") is not None
            else None
        ),
        extraction_started_at=_datetime_from_payload(payload.get("extraction_started_at")),
        created_at=_datetime_from_payload(payload.get("created_at")),
        updated_at=_datetime_from_payload(payload.get("updated_at")),
    )


def _datetime_payload(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_from_payload(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Stored extraction timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)
