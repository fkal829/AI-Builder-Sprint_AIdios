"""Idempotent private upload orchestration for one monthly performance report."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from app.core.enums import IdempotencyOperation
from app.core.errors import ErrorCode
from app.core.exceptions import (
    ExternalServiceUnavailable,
    ExternalStorageFailure,
    IdempotencyConflict,
    InvalidDocument,
    PerformanceReportPeriodAlreadyExists,
    ResourceNotFound,
)
from app.repositories.documents import DocumentRecord, PrivateStorage
from app.repositories.performance import (
    PerformanceAccessRepository,
    PerformanceReportAccess,
    PerformanceReportUploadRepository,
)
from app.repositories.performance import (
    PerformanceReportUploadResult as PerformanceReportUploadRepositoryResult,
)
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.performance import PerformanceReportCreated
from app.services.documents import validate_document
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.performance import (
    PerformanceAccessGuard,
    performance_upload_idempotency_payload,
)
from app.services.state_machine import InvalidStatusTransition

type _StoredUploadOutcome = Literal[
    "SUCCESS",
    "FAILED",
    "PERIOD_ALREADY_EXISTS",
    "INVALID_STATUS",
    "NOT_FOUND",
]

_UPLOAD_ID_NAMESPACE = UUID("cdce6a82-929f-4af6-ae30-8a88c0fc71b2")


class _PerformanceUploadRecoveryRequired(ExternalStorageFailure):
    """The side-effect state is uncertain and must keep its idempotency reservation."""


@dataclass(frozen=True)
class _StoredUploadResponse:
    outcome: _StoredUploadOutcome
    report: PerformanceReportCreated | None
    request_id: str


@dataclass(frozen=True)
class PerformanceReportUploadExecution:
    status_code: int
    report: PerformanceReportCreated | None
    error_code: ErrorCode | None
    error_message: str | None
    request_id: str
    replayed: bool


class PerformanceReportUploadService:
    """Validate, store, and atomically register a monthly private report."""

    def __init__(
        self,
        *,
        access_repository: PerformanceAccessRepository,
        upload_repository: PerformanceReportUploadRepository,
        storage: PrivateStorage,
        idempotency: IdempotencyService,
        max_size_bytes: int,
        max_pdf_pages: int,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        if max_size_bytes < 1 or max_pdf_pages < 1:
            raise ValueError("성과 리포트 파일 제한은 1 이상이어야 합니다.")
        self._access_repository = access_repository
        self._upload_repository = upload_repository
        self._storage = storage
        self._idempotency = idempotency
        self._guard = PerformanceAccessGuard(access_repository)
        self.max_size_bytes = max_size_bytes
        self.max_pdf_pages = max_pdf_pages
        self._now = now or (lambda: datetime.now(UTC))
        self._id_factory = id_factory

    def _upload_ids(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        idempotency_key: UUID,
    ) -> tuple[UUID, UUID]:
        if self._id_factory is not None:
            return self._id_factory(), self._id_factory()
        identity = f"{owner_id}:{contract_id}:{idempotency_key}"
        return (
            uuid5(_UPLOAD_ID_NAMESPACE, f"{identity}:report"),
            uuid5(_UPLOAD_ID_NAMESPACE, f"{identity}:document"),
        )

    async def upload(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        idempotency_key: UUID,
        period: str,
        declared_content_type: str | None,
        content: bytes,
        request_id: str | None = None,
    ) -> PerformanceReportUploadExecution:
        if len(content) > self.max_size_bytes:
            raise InvalidDocument("업로드 파일은 설정된 최대 크기를 초과할 수 없습니다.")

        # Hide missing and foreign contracts before reserving an idempotency row.
        # Do not apply the write-status/month guard here: a completed replay must
        # remain replayable after the report exists or the Contract status changes.
        try:
            await self._guard.require_contract(
                owner_id=owner_id,
                contract_id=contract_id,
            )
        except ExternalStorageFailure as error:
            raise ExternalServiceUnavailable() from error
        validated = await validate_document(
            document_type=DocumentType.PERFORMANCE_REPORT,
            declared_content_type=declared_content_type,
            content=content,
            max_pdf_pages=self.max_pdf_pages,
        )
        try:
            request_payload = performance_upload_idempotency_payload(
                period=period,
                content=content,
                verified_content_type=validated.content_type,
            )
        except (TypeError, ValueError) as error:
            raise InvalidDocument(str(error)) from error
        current_request_id = request_id or f"req_{idempotency_key.hex}"

        report_id, document_id = self._upload_ids(
            owner_id=owner_id,
            contract_id=contract_id,
            idempotency_key=idempotency_key,
        )
        created_at = self._utc_now()
        storage_path = (
            f"{owner_id}/{contract_id}/performance-reports/{report_id}/"
            f"{document_id}/source.{validated.extension}"
        )
        source_document = DocumentRecord(
            id=document_id,
            contract_id=contract_id,
            type=DocumentType.PERFORMANCE_REPORT,
            parse_status=DocumentParseStatus.PENDING,
            storage_path=storage_path,
            content_type=validated.content_type,
            size_bytes=len(content),
            page_count=validated.page_count,
            created_at=created_at,
        )

        async def perform() -> IdempotentOutcome[_StoredUploadResponse]:
            try:
                report = await self._perform_upload(
                    owner_id=owner_id,
                    report_id=report_id,
                    period=str(request_payload["period"]),
                    source_document=source_document,
                    content=content,
                )
            except _PerformanceUploadRecoveryRequired:
                raise
            except ExternalStorageFailure as error:
                raise ExternalServiceUnavailable() from error
            return _success_outcome(report, request_id=current_request_id)

        def persist_known_failure(
            error: Exception,
        ) -> IdempotentOutcome[_StoredUploadResponse] | None:
            if isinstance(error, _PerformanceUploadRecoveryRequired):
                return None
            return _known_failure_outcome(error, request_id=current_request_id)

        async def recover_pending() -> IdempotentOutcome[_StoredUploadResponse] | None:
            try:
                report = await self._recover_existing_upload(
                    owner_id=owner_id,
                    report_id=report_id,
                    period=str(request_payload["period"]),
                    source_document=source_document,
                    content=content,
                )
                if report is None:
                    report = await self._perform_upload(
                        owner_id=owner_id,
                        report_id=report_id,
                        period=str(request_payload["period"]),
                        source_document=source_document,
                        content=content,
                    )
            except _PerformanceUploadRecoveryRequired:
                raise
            except (ExternalServiceUnavailable, ExternalStorageFailure) as error:
                raise _PerformanceUploadRecoveryRequired(
                    "성과 리포트 업로드 복구 상태를 확인할 수 없습니다."
                ) from error
            except Exception as error:
                failure = _known_failure_outcome(error, request_id=current_request_id)
                if failure is None:
                    raise
                return failure
            return _success_outcome(report, request_id=current_request_id)

        def preserve_pending(error: Exception) -> bool:
            return isinstance(error, _PerformanceUploadRecoveryRequired)

        try:
            result = await self._idempotency.execute(
                owner_id=owner_id,
                operation=IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD,
                resource_id=contract_id,
                key=idempotency_key,
                request_payload=request_payload,
                perform=perform,
                replay=_stored_response_from_payload,
                exception_outcome=persist_known_failure,
                pending_recovery=recover_pending,
                preserve_pending_exception=preserve_pending,
            )
        except ExternalStorageFailure as error:
            raise ExternalServiceUnavailable() from error

        error_code, error_message = _stored_failure_details(result.response.outcome)
        if error_code is None and result.response.report is None:
            raise RuntimeError("성과 리포트 업로드 재생 결과가 없습니다.")
        return PerformanceReportUploadExecution(
            status_code=result.status_code,
            report=result.response.report,
            error_code=error_code,
            error_message=error_message,
            request_id=result.response.request_id,
            replayed=result.replayed,
        )

    async def _perform_upload(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        period: str,
        source_document: DocumentRecord,
        content: bytes,
    ) -> PerformanceReportCreated:
        await self._guard.require_contract(
            owner_id=owner_id,
            contract_id=source_document.contract_id,
            for_write=True,
        )

        await self._upload_or_recover_object(
            path=source_document.storage_path,
            content=content,
            content_type=source_document.content_type,
        )
        result = await self._create_metadata_or_recover(
            owner_id=owner_id,
            report_id=report_id,
            period=period,
            source_document=source_document,
        )
        if result.outcome in {"CREATED", "REPLAYED"}:
            if not _matches_upload(
                result=result,
                report_id=report_id,
                period=period,
                source_document=source_document,
            ):
                raise _PerformanceUploadRecoveryRequired(
                    "성과 리포트 업로드 저장 결과를 복구해야 합니다."
                )
            assert result.report is not None
            return _created_snapshot(result.report)

        if result.outcome == "PERIOD_ALREADY_EXISTS":
            await self._delete_definitive_rejection(source_document.storage_path)
            raise PerformanceReportPeriodAlreadyExists()
        if result.outcome == "INVALID_STATUS":
            await self._delete_definitive_rejection(source_document.storage_path)
            raise InvalidStatusTransition(
                "서명 완료, 이행 중, 재계약 검토 또는 완료 상태의 계약에만 "
                "광고효과 리포트를 업로드할 수 있습니다."
            )
        if result.outcome == "NOT_FOUND":
            await self._delete_definitive_rejection(source_document.storage_path)
            raise ResourceNotFound()
        if result.outcome == "CONFLICT":
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 업로드 저장 충돌을 복구해야 합니다."
            )
        raise _PerformanceUploadRecoveryRequired(
            "알 수 없는 성과 리포트 업로드 결과를 복구해야 합니다."
        )

    async def _upload_or_recover_object(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
    ) -> None:
        try:
            await self._storage.upload_private_object(
                path=path,
                content=content,
                content_type=content_type,
            )
            return
        except ExternalStorageFailure as upload_error:
            try:
                recovered = await self._storage.download_private_object(path=path)
            except ExternalStorageFailure as download_error:
                # With a deterministic path, another same-key execution may still
                # be finishing the upload. Deleting here could remove its object.
                raise _PerformanceUploadRecoveryRequired(
                    "성과 리포트 원본 저장 상태를 복구해야 합니다."
                ) from download_error
            if recovered != content:
                raise _PerformanceUploadRecoveryRequired(
                    "성과 리포트 원본 저장 상태를 복구해야 합니다."
                ) from upload_error

    async def _create_metadata_or_recover(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        period: str,
        source_document: DocumentRecord,
    ) -> PerformanceReportUploadRepositoryResult:
        arguments = {
            "owner_id": owner_id,
            "report_id": report_id,
            "period": period,
            "source_document": source_document,
        }
        try:
            return await self._upload_repository.create_performance_report_upload_with_audit(
                **arguments
            )
        except ExternalStorageFailure as first_error:
            try:
                return await self._upload_repository.create_performance_report_upload_with_audit(
                    **arguments
                )
            except ExternalStorageFailure:
                return await self._recover_committed_metadata(
                    owner_id=owner_id,
                    report_id=report_id,
                    period=period,
                    source_document=source_document,
                    original_error=first_error,
                )

    async def _recover_existing_upload(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        period: str,
        source_document: DocumentRecord,
        content: bytes,
    ) -> PerformanceReportCreated | None:
        try:
            report = await self._access_repository.get_owned_performance_report(
                owner_id=owner_id,
                contract_id=source_document.contract_id,
                report_id=report_id,
            )
            document = await self._access_repository.get_owned_performance_source_document(
                owner_id=owner_id,
                contract_id=source_document.contract_id,
                document_id=source_document.id,
            )
        except ExternalStorageFailure as error:
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 업로드 복구 조회에 실패했습니다."
            ) from error

        if report is None and document is None:
            return None
        recovered = PerformanceReportUploadRepositoryResult(
            outcome="REPLAYED",
            report=report,
            source_document=document,
        )
        if not _matches_upload(
            result=recovered,
            report_id=report_id,
            period=period,
            source_document=source_document,
        ):
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 업로드 복구 결과가 요청과 일치하지 않습니다."
            )
        try:
            stored_content = await self._storage.download_private_object(
                path=source_document.storage_path
            )
        except ExternalStorageFailure as error:
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 원본 복구 확인에 실패했습니다."
            ) from error
        if stored_content != content:
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 원본 복구 결과가 요청과 일치하지 않습니다."
            )
        assert report is not None
        return _created_snapshot(report)

    async def _recover_committed_metadata(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        period: str,
        source_document: DocumentRecord,
        original_error: ExternalStorageFailure,
    ) -> PerformanceReportUploadRepositoryResult:
        try:
            report = await self._access_repository.get_owned_performance_report(
                owner_id=owner_id,
                contract_id=source_document.contract_id,
                report_id=report_id,
            )
            document = await self._access_repository.get_owned_performance_source_document(
                owner_id=owner_id,
                contract_id=source_document.contract_id,
                document_id=source_document.id,
            )
        except ExternalStorageFailure:
            # The transaction may have committed. Never delete an object that a
            # committed Document row could already reference.
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 업로드 커밋 상태를 확인할 수 없습니다."
            ) from original_error

        if report is None and document is None:
            # A transport failure does not prove that the transaction rolled back:
            # an in-flight commit may still become visible after this read. Keep the
            # private object and the idempotency reservation for a safe retry.
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 업로드 커밋 상태를 복구해야 합니다."
            ) from original_error
        recovered = PerformanceReportUploadRepositoryResult(
            outcome="REPLAYED",
            report=report,
            source_document=document,
        )
        if not _matches_upload(
            result=recovered,
            report_id=report_id,
            period=period,
            source_document=source_document,
        ):
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 업로드 커밋 결과가 요청과 일치하지 않습니다."
            ) from original_error
        return recovered

    async def _delete_definitive_rejection(self, path: str) -> None:
        try:
            await self._storage.delete_private_object(path=path)
        except ExternalStorageFailure as error:
            raise _PerformanceUploadRecoveryRequired(
                "성과 리포트 원본 정리 상태를 복구해야 합니다."
            ) from error

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("성과 리포트 업로드 시각은 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)


def _matches_upload(
    *,
    result: PerformanceReportUploadRepositoryResult,
    report_id: UUID,
    period: str,
    source_document: DocumentRecord,
) -> bool:
    report = result.report
    document = result.source_document
    return bool(
        report is not None
        and document is not None
        and report.id == report_id
        and report.contract_id == source_document.contract_id
        and report.period == period
        and report.source_document_id == source_document.id
        and report.created_at is not None
        and document.id == source_document.id
        and document.contract_id == source_document.contract_id
        and document.type is DocumentType.PERFORMANCE_REPORT
        and document.storage_path == source_document.storage_path
        and document.content_type == source_document.content_type
        and document.size_bytes == source_document.size_bytes
        and document.page_count == source_document.page_count
        and document.created_at == report.created_at
    )


def _created_snapshot(report: PerformanceReportAccess) -> PerformanceReportCreated:
    if report.created_at is None:
        raise _PerformanceUploadRecoveryRequired("성과 리포트 생성 시각을 복구해야 합니다.")
    return PerformanceReportCreated(
        id=report.id,
        contract_id=report.contract_id,
        period=report.period,
        source_document_id=report.source_document_id,
        status="UPLOADED",
        extracted_payload=None,
        current_revision=None,
        revision_count=0,
        revisions=[],
        created_at=report.created_at,
        updated_at=report.created_at,
    )


def _success_outcome(
    report: PerformanceReportCreated,
    *,
    request_id: str,
) -> IdempotentOutcome[_StoredUploadResponse]:
    stored = _StoredUploadResponse(
        outcome="SUCCESS",
        report=report,
        request_id=request_id,
    )
    return IdempotentOutcome(
        status_code=201,
        response=stored,
        replay_payload=_stored_response_payload(stored),
    )


def _known_failure_outcome(
    error: Exception,
    *,
    request_id: str,
) -> IdempotentOutcome[_StoredUploadResponse] | None:
    if isinstance(error, ExternalServiceUnavailable):
        outcome: _StoredUploadOutcome = "FAILED"
        status_code = 503
    elif isinstance(error, PerformanceReportPeriodAlreadyExists):
        outcome = "PERIOD_ALREADY_EXISTS"
        status_code = 409
    elif isinstance(error, InvalidStatusTransition):
        outcome = "INVALID_STATUS"
        status_code = 409
    elif isinstance(error, ResourceNotFound):
        outcome = "NOT_FOUND"
        status_code = 404
    else:
        return None
    stored = _StoredUploadResponse(
        outcome=outcome,
        report=None,
        request_id=request_id,
    )
    return IdempotentOutcome(
        status_code=status_code,
        response=stored,
        replay_payload=_stored_response_payload(stored),
    )


def _stored_failure_details(
    outcome: _StoredUploadOutcome,
) -> tuple[ErrorCode | None, str | None]:
    if outcome == "SUCCESS":
        return None, None
    if outcome == "FAILED":
        error = ExternalServiceUnavailable()
        return error.code, error.message
    if outcome == "PERIOD_ALREADY_EXISTS":
        error = PerformanceReportPeriodAlreadyExists()
        return error.code, error.message
    if outcome == "INVALID_STATUS":
        return (
            ErrorCode.INVALID_STATUS_TRANSITION,
            "서명 완료, 이행 중, 재계약 검토 또는 완료 상태의 계약에만 "
            "광고효과 리포트를 업로드할 수 있습니다.",
        )
    if outcome == "NOT_FOUND":
        error = ResourceNotFound()
        return error.code, error.message
    raise RuntimeError("알 수 없는 성과 리포트 업로드 재생 결과입니다.")


def _stored_response_payload(response: _StoredUploadResponse) -> dict[str, object]:
    return {
        "outcome": response.outcome,
        "report": response.report.model_dump(mode="json") if response.report else None,
        "requestId": response.request_id,
    }


def _stored_response_from_payload(payload: dict[str, object]) -> _StoredUploadResponse:
    outcome = payload.get("outcome")
    raw_report = payload.get("report")
    stored_request_id = payload.get("requestId")
    if not isinstance(stored_request_id, str) or not stored_request_id.startswith("req_"):
        raise IdempotencyConflict("저장된 성과 리포트 업로드 응답이 올바르지 않습니다.")
    if outcome == "SUCCESS" and isinstance(raw_report, dict):
        return _StoredUploadResponse(
            outcome="SUCCESS",
            report=PerformanceReportCreated.model_validate(raw_report),
            request_id=stored_request_id,
        )
    if (
        outcome
        in {
            "FAILED",
            "PERIOD_ALREADY_EXISTS",
            "INVALID_STATUS",
            "NOT_FOUND",
        }
        and raw_report is None
    ):
        return _StoredUploadResponse(
            outcome=outcome,
            report=None,
            request_id=stored_request_id,
        )
    raise IdempotencyConflict("저장된 성과 리포트 업로드 응답이 올바르지 않습니다.")
