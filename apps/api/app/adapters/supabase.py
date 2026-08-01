import asyncio
import hmac
import logging
import re
import secrets
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Literal
from uuid import UUID, uuid4

from supabase import Client, create_client

from app.core.enums import (
    AdjustmentRequestStatus,
    AdjustmentResolution,
    AdjustmentResponseDecision,
    AgreementClauseCategory,
    AgreementClauseDisposition,
    AgreementClauseOutcome,
    AnalysisStatus,
    ContractStatus,
    ExtractedField,
    ExtractedSourceType,
    IdempotencyOperation,
    InternalSignatureStatus,
    ModusignStatus,
    ObligationStatus,
    PerformanceReportStatus,
    PublicTokenScope,
    RenewalDecisionType,
    ReviewItemStatus,
    ReviewSignalType,
    SuggestionChoice,
    VerificationStatus,
)
from app.core.errors import ErrorCode
from app.core.exceptions import ExternalStorageFailure, InvalidDocument
from app.domain.obligations import build_representative_obligation
from app.repositories.adjustments import (
    AdjustmentDetailRecord,
    AdjustmentRequestItemRecord,
    AdjustmentRequestRecord,
    AdjustmentResponseRecord,
    DocumentClauseForAdjustment,
    FinalClauseRecord,
    ManualReviewItemRecord,
    PublicAdjustmentRecord,
    ReviewItemForAdjustment,
)
from app.repositories.agreements import AgreementCreationContext, AgreementRecord
from app.repositories.analysis import AnalysisTaskRecord, QueuedAnalysisJob
from app.repositories.contracts import (
    AuditEventRecord,
    ContractDeleteOutcome,
    ContractRecord,
    RenewalDecisionSaveOutcome,
    RenewalDecisionSaveResult,
)
from app.repositories.dashboard import DASHBOARD_SIGNAL_TIE_BREAK, DashboardRecord
from app.repositories.documents import DocumentRecord
from app.repositories.idempotency import IdempotencyClaim, IdempotencyRecord
from app.repositories.obligations import (
    EvidenceLinkCreateOutcome,
    EvidenceLinkCreateResult,
    EvidenceReviewOutcome,
    EvidenceReviewResult,
    EvidenceSubmissionOutcome,
    ObligationRecord,
)
from app.repositories.performance import (
    PerformanceContractAccess,
    PerformanceExtractionApplyResult,
    PerformanceExtractionClaim,
    PerformanceReportAccess,
    PerformanceReportConfirmResult,
    PerformanceReportUploadResult,
)
from app.repositories.public_tokens import PublicTokenRecord
from app.repositories.review_items import (
    ReviewItemSelectionOutcome,
    ReviewItemSelectionResult,
)
from app.repositories.revised_contracts import RevisedContractContext
from app.repositories.signatures import SignatureRecord
from app.repositories.webhooks import ModusignWebhookReceipt
from app.schemas.agreements import Agreement
from app.schemas.analysis import Analysis, ReviewItem
from app.schemas.contracts import ContractCreate, RenewalDecision
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.performance import (
    PerformanceExtractedPayload,
    PerformanceFlag,
    PerformanceInquiryDraft,
    PerformanceReport,
    PerformanceReportRevision,
)
from app.schemas.revised_contracts import RevisedContractReview, RevisedContractReviewStatus
from app.schemas.signatures import Signature
from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermInput


@dataclass(frozen=True)
class MockAuditEvent:
    id: UUID
    contract_id: UUID
    event_type: str
    actor_type: str
    summary: str | None
    created_at: datetime
    payload: dict[str, str] | None = None


@dataclass(frozen=True)
class MockSignedAccess:
    token: str
    path: str
    expires_at: datetime
    expires_in_seconds: int
    access_url: str


@dataclass(frozen=True)
class MockPrivateObject:
    content: bytes
    content_type: str


@dataclass(frozen=True)
class MockObligation:
    id: UUID
    contract_id: UUID
    title: str
    due_date: date
    assignee: str
    evidence_type: str
    source_document_id: UUID
    source_page: int
    source_text: str
    confidence: float
    status: ObligationStatus
    created_at: datetime
    updated_at: datetime
    evidence_url: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    payment_condition_met: bool = False


@dataclass(frozen=True)
class MockModusignWebhookEvent:
    deduplication_key: str
    event_id: str | None
    event_type: str
    document_id: str
    received_at: datetime
    processed_at: datetime | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


logger = logging.getLogger(__name__)

_DISCARDABLE_CONTRACT_STATUSES = {
    ContractStatus.DRAFT,
    ContractStatus.ANALYZING,
    ContractStatus.REVIEW_REQUIRED,
    ContractStatus.NEGOTIATING,
}


class SupabaseAdapter:
    """Supabase Auth, PostgreSQL and private Storage boundary."""

    def __init__(
        self,
        *,
        mode: Literal["mock", "live"],
        url: str,
        service_role_key: str,
        bucket: str,
        demo_owner_id: UUID,
        demo_contract_id: UUID,
        demo_bearer_token: str,
        mock_storage_access_base_url: str = ("http://localhost:8000/api/v1/_mock/storage"),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.mode = mode
        self.bucket = bucket
        self._demo_owner_id = demo_owner_id
        self._demo_bearer_token = demo_bearer_token
        self._mock_storage_access_base_url = mock_storage_access_base_url.rstrip("/")
        self._clock = clock
        self._client: Client | None = None
        self._mock_lock = asyncio.Lock()
        self._mock_owned_contracts = {(demo_owner_id, demo_contract_id)}
        self._mock_contracts: dict[UUID, ContractRecord] = {}
        self._mock_objects: dict[str, bytes] = {}
        self._mock_object_content_types: dict[str, str] = {}
        self._mock_documents: dict[UUID, DocumentRecord] = {}
        self._mock_performance_reports: dict[UUID, PerformanceReportAccess] = {}
        self._mock_performance_report_revisions: dict[UUID, list[PerformanceReportRevision]] = {}
        self._mock_understood_terms: dict[UUID, UnderstoodTerm] = {}
        self._mock_renewal_decisions: dict[UUID, RenewalDecision] = {}
        self._mock_audit_events: list[MockAuditEvent] = []
        self._mock_signed_accesses: dict[str, MockSignedAccess] = {}
        self._mock_public_tokens: dict[str, PublicTokenRecord] = {}
        self._mock_idempotency: dict[
            tuple[UUID, IdempotencyOperation, UUID, UUID], IdempotencyRecord
        ] = {}
        self._mock_analysis_tasks: dict[UUID, AnalysisTaskRecord] = {}
        self._mock_obligations: dict[UUID, MockObligation] = {}
        self._mock_review_items: dict[UUID, ReviewItemForAdjustment] = {}
        self._mock_review_item_details: dict[UUID, ReviewItem] = {}
        self._mock_adjustment_requests: dict[UUID, AdjustmentRequestRecord] = {}
        self._mock_adjustment_responses: dict[UUID, tuple[AdjustmentResponseRecord, ...]] = {}
        self._mock_final_clauses: dict[UUID, tuple[FinalClauseRecord, ...]] = {}
        self._mock_agreements: dict[UUID, AgreementRecord] = {}
        self._mock_revised_contract_reviews: dict[UUID, RevisedContractReview] = {}
        self._mock_signatures: dict[UUID, SignatureRecord] = {}
        self._mock_modusign_webhook_events: dict[str, MockModusignWebhookEvent] = {}
        if mode == "live":
            self._client = create_client(url, service_role_key)

    @property
    def mock_objects(self) -> dict[str, bytes]:
        return dict(self._mock_objects)

    @property
    def mock_documents(self) -> dict[UUID, DocumentRecord]:
        return dict(self._mock_documents)

    @property
    def mock_performance_reports(self) -> dict[UUID, PerformanceReportAccess]:
        return dict(self._mock_performance_reports)

    @property
    def mock_performance_report_revisions(self) -> dict[UUID, list[PerformanceReportRevision]]:
        return {key: list(value) for key, value in self._mock_performance_report_revisions.items()}

    @property
    def mock_understood_terms(self) -> dict[UUID, UnderstoodTerm]:
        return dict(self._mock_understood_terms)

    @property
    def mock_renewal_decisions(self) -> dict[UUID, RenewalDecision]:
        return dict(self._mock_renewal_decisions)

    @property
    def mock_audit_events(self) -> tuple[MockAuditEvent, ...]:
        return tuple(self._mock_audit_events)

    @property
    def mock_signed_accesses(self) -> tuple[MockSignedAccess, ...]:
        return tuple(self._mock_signed_accesses.values())

    @property
    def mock_contracts(self) -> dict[UUID, ContractRecord]:
        return dict(self._mock_contracts)

    @property
    def mock_public_tokens(self) -> dict[str, PublicTokenRecord]:
        return dict(self._mock_public_tokens)

    @property
    def mock_idempotency_records(self) -> tuple[IdempotencyRecord, ...]:
        return tuple(self._mock_idempotency.values())

    @property
    def mock_analysis_tasks(self) -> dict[UUID, AnalysisTaskRecord]:
        return dict(self._mock_analysis_tasks)

    @property
    def mock_revised_contract_reviews(self) -> dict[UUID, RevisedContractReview]:
        return dict(self._mock_revised_contract_reviews)

    @property
    def mock_obligations(self) -> dict[UUID, MockObligation]:
        return dict(self._mock_obligations)

    @property
    def mock_review_items(self) -> dict[UUID, ReviewItemForAdjustment]:
        return dict(self._mock_review_items)

    @property
    def mock_review_item_details(self) -> dict[UUID, ReviewItem]:
        return dict(self._mock_review_item_details)

    @property
    def mock_adjustment_requests(self) -> dict[UUID, AdjustmentRequestRecord]:
        return dict(self._mock_adjustment_requests)

    @property
    def mock_adjustment_responses(
        self,
    ) -> dict[UUID, tuple[AdjustmentResponseRecord, ...]]:
        return dict(self._mock_adjustment_responses)

    @property
    def mock_agreements(self) -> dict[UUID, AgreementRecord]:
        return dict(self._mock_agreements)

    @property
    def mock_signatures(self) -> dict[UUID, SignatureRecord]:
        return dict(self._mock_signatures)

    @property
    def mock_modusign_webhook_events(self) -> dict[str, MockModusignWebhookEvent]:
        return dict(self._mock_modusign_webhook_events)

    async def authenticate_owner(self, token: str) -> UUID | None:
        if self.mode == "mock":
            if hmac.compare_digest(token, self._demo_bearer_token):
                return self._demo_owner_id
            return None
        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(client.auth.get_user, token)
        except Exception:
            return None
        if response.user is None:
            return None
        try:
            return UUID(str(response.user.id))
        except ValueError:
            return None

    async def is_contract_owned(self, *, owner_id: UUID, contract_id: UUID) -> bool:
        if self.mode == "mock":
            return (owner_id, contract_id) in self._mock_owned_contracts
        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("contracts")
                    .select("id")
                    .eq("id", str(contract_id))
                    .eq("owner_id", str(owner_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("계약 소유권 조회에 실패했습니다.") from error
        return bool(response.data)

    async def upload_private_object(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
    ) -> None:
        if self.mode == "mock":
            async with self._mock_lock:
                if path in self._mock_objects:
                    raise ExternalStorageFailure("같은 Storage 경로가 이미 존재합니다.")
                self._mock_objects[path] = content
                self._mock_object_content_types[path] = content_type
            return
        client = self._require_live_client()
        upload = partial(
            client.storage.from_(self.bucket).upload,
            path=path,
            file=content,
            file_options={
                "cache-control": "0",
                "content-type": content_type,
                "upsert": "false",
            },
        )
        try:
            await asyncio.to_thread(upload)
        except Exception as error:
            raise ExternalStorageFailure("비공개 문서 저장에 실패했습니다.") from error

    async def delete_private_object(self, *, path: str) -> None:
        if self.mode == "mock":
            async with self._mock_lock:
                self._mock_objects.pop(path, None)
                self._mock_object_content_types.pop(path, None)
            return
        client = self._require_live_client()
        try:
            await asyncio.to_thread(client.storage.from_(self.bucket).remove, [path])
        except Exception as error:
            raise ExternalStorageFailure("업로드 롤백에 실패했습니다.") from error

    async def download_private_object(self, *, path: str) -> bytes:
        if self.mode == "mock":
            async with self._mock_lock:
                content = self._mock_objects.get(path)
                if content is None:
                    raise ExternalStorageFailure("비공개 문서를 찾을 수 없습니다.")
                return content
        client = self._require_live_client()
        try:
            content = await asyncio.to_thread(
                client.storage.from_(self.bucket).download,
                path,
            )
        except Exception as error:
            raise ExternalStorageFailure("비공개 문서를 읽지 못했습니다.") from error
        if not isinstance(content, bytes):
            raise ExternalStorageFailure("비공개 문서 응답이 올바르지 않습니다.")
        return content

    async def create_document_with_audit(
        self,
        *,
        owner_id: UUID,
        record: DocumentRecord,
    ) -> DocumentRecord | None:
        if record.type is DocumentType.PERFORMANCE_REPORT:
            raise InvalidDocument("광고효과 리포트는 전용 업로드 API에서만 생성할 수 있습니다.")
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, record.contract_id) not in self._mock_owned_contracts:
                    return None
                self._mock_documents[record.id] = record
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=record.contract_id,
                        event_type="DOCUMENT_UPLOADED",
                        actor_type="OWNER",
                        summary="계약 문서를 업로드했습니다.",
                        created_at=record.created_at,
                    )
                )
            return record

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_document_id": str(record.id),
            "p_contract_id": str(record.contract_id),
            "p_document_type": record.type.value,
            "p_parse_status": record.parse_status.value,
            "p_storage_path": record.storage_path,
            "p_content_type": record.content_type,
            "p_size_bytes": record.size_bytes,
            "p_page_count": record.page_count,
            "p_created_at": record.created_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("create_document_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("문서 메타데이터 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return self._document_record_from_row(row)

    async def get_owned_document(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_id: UUID,
    ) -> DocumentRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                document = self._mock_documents.get(document_id)
                if document is None or document.contract_id != contract_id:
                    return None
                return document

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("documents")
                    .select(
                        "id,contract_id,type,parse_status,storage_path,"
                        "content_type,size_bytes,page_count,created_at,"
                        "contracts!inner(owner_id)"
                    )
                    .eq("id", str(document_id))
                    .eq("contract_id", str(contract_id))
                    .eq("contracts.owner_id", str(owner_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("문서 소유권 조회에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return self._document_record_from_row(row)

    async def get_latest_owned_document(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_type: DocumentType,
    ) -> DocumentRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                candidates = [
                    document
                    for document in self._mock_documents.values()
                    if document.contract_id == contract_id and document.type == document_type
                ]
                if not candidates:
                    return None
                return max(candidates, key=lambda item: (item.created_at, str(item.id)))

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("documents")
                    .select(
                        "id,contract_id,type,parse_status,storage_path,"
                        "content_type,size_bytes,page_count,created_at,"
                        "contracts!inner(owner_id)"
                    )
                    .eq("contract_id", str(contract_id))
                    .eq("type", document_type.value)
                    .eq("contracts.owner_id", str(owner_id))
                    .order("created_at", desc=True)
                    .order("id", desc=True)
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("최신 계약 문서 조회에 실패했습니다.") from error
        if not response.data:
            return None
        return self._document_record_from_row(response.data[0])

    async def get_owned_performance_contract(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> PerformanceContractAccess | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                contract = self._mock_contracts.get(contract_id)
                if contract is None or contract.owner_id != owner_id:
                    return None
                return PerformanceContractAccess(
                    id=contract.id,
                    owner_id=contract.owner_id,
                    status=contract.status,
                )

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("contracts")
                    .select("id,owner_id,status")
                    .eq("id", str(contract_id))
                    .eq("owner_id", str(owner_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("광고효과 계약 소유권 조회에 실패했습니다.") from error
        if not response.data:
            return None
        try:
            row = response.data[0]
            return PerformanceContractAccess(
                id=UUID(str(row["id"])),
                owner_id=UUID(str(row["owner_id"])),
                status=ContractStatus(row["status"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "광고효과 계약 소유권 조회 결과가 올바르지 않습니다."
            ) from error

    async def get_owned_performance_report(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
    ) -> PerformanceReportAccess | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                contract = self._mock_contracts.get(contract_id)
                report = self._mock_performance_reports.get(report_id)
                if (
                    contract is None
                    or contract.owner_id != owner_id
                    or report is None
                    or report.contract_id != contract_id
                ):
                    return None
                return report

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("performance_reports")
                    .select(
                        "id,contract_id,period,source_document_id,status,"
                        "extracted_payload,current_revision_id,revision_count,"
                        "extraction_attempt_id,extraction_started_at,created_at,updated_at,"
                        "contracts!inner(owner_id)"
                    )
                    .eq("id", str(report_id))
                    .eq("contract_id", str(contract_id))
                    .eq("contracts.owner_id", str(owner_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("광고효과 리포트 소유권 조회에 실패했습니다.") from error
        if not response.data:
            return None
        try:
            return _performance_report_access_from_row(response.data[0])
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "광고효과 리포트 소유권 조회 결과가 올바르지 않습니다."
            ) from error

    async def get_owned_performance_source_document(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_id: UUID,
    ) -> DocumentRecord | None:
        document = await self.get_owned_document(
            owner_id=owner_id,
            contract_id=contract_id,
            document_id=document_id,
        )
        if document is None or document.type is not DocumentType.PERFORMANCE_REPORT:
            return None
        return document

    async def has_performance_report_for_period(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        period: str,
    ) -> bool:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                if (
                    (owner_id, contract_id) not in self._mock_owned_contracts
                    or contract is None
                    or contract.owner_id != owner_id
                ):
                    return False
                return any(
                    report.contract_id == contract_id and report.period == period
                    for report in self._mock_performance_reports.values()
                )

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("performance_reports")
                    .select("id,contracts!inner(owner_id)")
                    .eq("contract_id", str(contract_id))
                    .eq("period", period)
                    .eq("contracts.owner_id", str(owner_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("광고효과 리포트 월 중복 조회에 실패했습니다.") from error
        return bool(response.data)

    async def get_owned_performance_report_for_period(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        period: str,
    ) -> PerformanceReportAccess | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                if (
                    (owner_id, contract_id) not in self._mock_owned_contracts
                    or contract is None
                    or contract.owner_id != owner_id
                ):
                    return None
                return next(
                    (
                        report
                        for report in self._mock_performance_reports.values()
                        if report.contract_id == contract_id and report.period == period
                    ),
                    None,
                )

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("performance_reports")
                    .select(
                        "id,contract_id,period,source_document_id,status,"
                        "extracted_payload,current_revision_id,revision_count,"
                        "extraction_attempt_id,extraction_started_at,created_at,updated_at,"
                        "contracts!inner(owner_id)"
                    )
                    .eq("contract_id", str(contract_id))
                    .eq("period", period)
                    .eq("contracts.owner_id", str(owner_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("광고효과 리포트 월별 조회에 실패했습니다.") from error
        if not response.data:
            return None
        try:
            return _performance_report_access_from_row(response.data[0])
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "광고효과 리포트 월별 조회 결과가 올바르지 않습니다."
            ) from error

    async def list_owned_performance_reports(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> list[PerformanceReportAccess] | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                if (
                    (owner_id, contract_id) not in self._mock_owned_contracts
                    or contract is None
                    or contract.owner_id != owner_id
                ):
                    return None
                return [
                    report
                    for report in self._mock_performance_reports.values()
                    if report.contract_id == contract_id
                ]

        if not await self.is_contract_owned(owner_id=owner_id, contract_id=contract_id):
            return None
        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("performance_reports")
                    .select(
                        "id,contract_id,period,source_document_id,status,"
                        "extracted_payload,current_revision_id,revision_count,"
                        "extraction_attempt_id,extraction_started_at,created_at,updated_at"
                    )
                    .eq("contract_id", str(contract_id))
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("광고효과 리포트 목록 조회에 실패했습니다.") from error
        try:
            return [_performance_report_access_from_row(row) for row in response.data or []]
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "광고효과 리포트 목록 조회 결과가 올바르지 않습니다."
            ) from error

    async def create_performance_report_upload_with_audit(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        period: str,
        source_document: DocumentRecord,
    ) -> PerformanceReportUploadResult:
        """Atomically append upload metadata and its non-sensitive audit event."""

        if source_document.type is not DocumentType.PERFORMANCE_REPORT:
            raise ValueError("성과 리포트 원본은 PERFORMANCE_REPORT Document여야 합니다.")
        if source_document.parse_status is not DocumentParseStatus.PENDING:
            raise ValueError("새 성과 리포트 Document는 PENDING으로 시작해야 합니다.")
        if source_document.created_at.tzinfo is None:
            raise ValueError("성과 리포트 생성 시각은 시간대 정보를 포함해야 합니다.")
        if re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", period) is None:
            raise ValueError("성과 리포트 월은 YYYY-MM 형식이어야 합니다.")

        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(source_document.contract_id)
                if (
                    (owner_id, source_document.contract_id) not in self._mock_owned_contracts
                    or contract is None
                    or contract.owner_id != owner_id
                ):
                    return PerformanceReportUploadResult(outcome="NOT_FOUND")

                existing_report = self._mock_performance_reports.get(report_id)
                if existing_report is not None:
                    existing_document = self._mock_documents.get(existing_report.source_document_id)
                    if _performance_upload_is_replay(
                        report=existing_report,
                        source_document=existing_document,
                        report_id=report_id,
                        period=period,
                        requested_document=source_document,
                    ):
                        return PerformanceReportUploadResult(
                            outcome="REPLAYED",
                            report=existing_report,
                            source_document=existing_document,
                        )
                    return PerformanceReportUploadResult(outcome="CONFLICT")

                if source_document.id in self._mock_documents:
                    return PerformanceReportUploadResult(outcome="CONFLICT")
                if contract.status not in {
                    ContractStatus.SIGNED,
                    ContractStatus.IN_PROGRESS,
                    ContractStatus.RENEWAL_DUE,
                    ContractStatus.COMPLETED,
                }:
                    return PerformanceReportUploadResult(outcome="INVALID_STATUS")
                if any(
                    report.contract_id == source_document.contract_id and report.period == period
                    for report in self._mock_performance_reports.values()
                ):
                    return PerformanceReportUploadResult(outcome="PERIOD_ALREADY_EXISTS")

                report = PerformanceReportAccess(
                    id=report_id,
                    contract_id=source_document.contract_id,
                    period=period,
                    source_document_id=source_document.id,
                    status=PerformanceReportStatus.UPLOADED,
                    created_at=source_document.created_at,
                    updated_at=source_document.created_at,
                )
                event = MockAuditEvent(
                    id=uuid4(),
                    contract_id=source_document.contract_id,
                    event_type="PERFORMANCE_REPORT_UPLOADED",
                    actor_type="OWNER",
                    summary="광고효과 리포트를 업로드했습니다.",
                    created_at=source_document.created_at,
                    payload={},
                )
                self._mock_documents[source_document.id] = source_document
                self._mock_performance_reports[report_id] = report
                self._mock_audit_events.append(event)
                return PerformanceReportUploadResult(
                    outcome="CREATED",
                    report=report,
                    source_document=source_document,
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_document_id": str(source_document.id),
            "p_report_id": str(report_id),
            "p_contract_id": str(source_document.contract_id),
            "p_period": period,
            "p_storage_path": source_document.storage_path,
            "p_content_type": source_document.content_type,
            "p_size_bytes": source_document.size_bytes,
            "p_page_count": source_document.page_count,
            "p_created_at": source_document.created_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "create_performance_report_upload_with_audit",
                    params,
                ).execute()
            )
            result = _performance_upload_result_from_payload(_rpc_json_payload(response.data))
        except ExternalStorageFailure:
            raise
        except Exception as error:
            raise ExternalStorageFailure(
                "성과 리포트 업로드 메타데이터 저장에 실패했습니다."
            ) from error

        if result.outcome in {"CREATED", "REPLAYED"}:
            if result.report is None or not _performance_upload_is_replay(
                report=result.report,
                source_document=result.source_document,
                report_id=report_id,
                period=period,
                requested_document=source_document,
            ):
                raise ExternalStorageFailure(
                    "성과 리포트 업로드 저장 결과가 요청과 일치하지 않습니다."
                )
        return result

    async def claim_performance_report_extraction(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        idempotency_key: UUID,
        started_at: datetime,
        stale_before: datetime,
    ) -> PerformanceExtractionClaim:
        if started_at.tzinfo is None or stale_before.tzinfo is None:
            raise ValueError("추출 attempt 시각은 시간대 정보를 포함해야 합니다.")
        if stale_before > started_at:
            raise ValueError("stale 기준 시각은 attempt 시작 시각보다 늦을 수 없습니다.")
        if attempt_id != idempotency_key:
            raise ValueError("추출 attempt ID는 현재 멱등 키와 같아야 합니다.")
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                report = self._mock_performance_reports.get(report_id)
                if (
                    (owner_id, contract_id) not in self._mock_owned_contracts
                    or contract is None
                    or contract.owner_id != owner_id
                    or report is None
                    or report.contract_id != contract_id
                ):
                    return PerformanceExtractionClaim(outcome="NOT_FOUND")
                document = self._mock_documents.get(report.source_document_id)
                if (
                    document is None
                    or document.contract_id != contract_id
                    or document.type is not DocumentType.PERFORMANCE_REPORT
                ):
                    return PerformanceExtractionClaim(outcome="NOT_FOUND")
                if (
                    contract.status
                    not in {
                        ContractStatus.SIGNED,
                        ContractStatus.IN_PROGRESS,
                        ContractStatus.RENEWAL_DUE,
                        ContractStatus.COMPLETED,
                    }
                    or report.status is not PerformanceReportStatus.UPLOADED
                ):
                    return PerformanceExtractionClaim(outcome="INVALID_STATUS")

                recovered = False
                if document.parse_status is DocumentParseStatus.PROCESSING:
                    if report.extraction_attempt_id == attempt_id:
                        return PerformanceExtractionClaim(
                            outcome="CLAIMED",
                            report=report,
                            source_document=document,
                        )
                    if (
                        report.extraction_attempt_id is None
                        or report.extraction_started_at is None
                        or report.extraction_started_at > stale_before
                    ):
                        return PerformanceExtractionClaim(
                            outcome="IN_PROGRESS",
                            report=report,
                            source_document=document,
                        )
                    recovered = True

                created_at = report.created_at or document.created_at
                if started_at < created_at or (
                    report.updated_at is not None and started_at < report.updated_at
                ):
                    raise ValueError("추출 attempt는 리포트의 마지막 수정 전에 시작할 수 없습니다.")
                if recovered:
                    stale_keys = [
                        record_key
                        for record_key, record in self._mock_idempotency.items()
                        if record.owner_id == owner_id
                        and record.operation is IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT
                        and record.resource_id == report_id
                        and record.key != idempotency_key
                        and record.response_status is None
                    ]
                    for record_key in stale_keys:
                        self._mock_idempotency.pop(record_key, None)
                    self._mock_audit_events.append(
                        MockAuditEvent(
                            id=uuid4(),
                            contract_id=contract_id,
                            event_type="PERFORMANCE_REPORT_EXTRACTION_RECOVERED",
                            actor_type="OWNER",
                            summary=(
                                "15분 이상 지연된 광고효과 리포트 추출을 명시적으로 재시도했습니다."
                            ),
                            created_at=started_at,
                            payload={
                                "report_id": str(report_id),
                                "previous_attempt_id": str(report.extraction_attempt_id),
                                "attempt_id": str(attempt_id),
                            },
                        )
                    )

                claimed_report = replace(
                    report,
                    extraction_attempt_id=attempt_id,
                    extraction_started_at=started_at,
                    created_at=created_at,
                    updated_at=started_at,
                )
                claimed_document = replace(
                    document,
                    parse_status=DocumentParseStatus.PROCESSING,
                )
                self._mock_performance_reports[report_id] = claimed_report
                self._mock_documents[document.id] = claimed_document
                return PerformanceExtractionClaim(
                    outcome="RECOVERED" if recovered else "CLAIMED",
                    report=claimed_report,
                    source_document=claimed_document,
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_report_id": str(report_id),
            "p_attempt_id": str(attempt_id),
            "p_idempotency_key": str(idempotency_key),
            "p_started_at": started_at.isoformat(),
            "p_stale_before": stale_before.isoformat(),
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await asyncio.to_thread(
                    lambda: client.rpc(
                        "claim_performance_report_extraction",
                        params,
                    ).execute()
                )
                payload = _rpc_json_payload(response.data)
                return _performance_extraction_claim_from_payload(payload)
            except ExternalStorageFailure:
                raise
            except Exception as error:
                last_error = error
        assert last_error is not None
        raise ExternalStorageFailure("광고효과 추출 작업 점유에 실패했습니다.") from last_error

    async def complete_performance_report_extraction(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        extracted_payload: PerformanceExtractedPayload,
        completed_at: datetime,
    ) -> PerformanceExtractionApplyResult:
        if completed_at.tzinfo is None:
            raise ValueError("추출 완료 시각은 시간대 정보를 포함해야 합니다.")
        if self.mode == "mock":
            async with self._mock_lock:
                owned = self._mock_performance_extraction_rows(
                    owner_id=owner_id,
                    contract_id=contract_id,
                    report_id=report_id,
                )
                if owned is None:
                    return PerformanceExtractionApplyResult(outcome="NOT_FOUND")
                contract, report, document = owned
                if report.extraction_attempt_id != attempt_id:
                    return PerformanceExtractionApplyResult(outcome="STALE")
                if (
                    report.status is PerformanceReportStatus.EXTRACTED
                    and report.extracted_payload == extracted_payload
                    and document.parse_status is DocumentParseStatus.COMPLETED
                ):
                    return PerformanceExtractionApplyResult(
                        outcome="APPLIED",
                        report=report,
                        source_document=document,
                    )
                if (
                    contract.status
                    not in {
                        ContractStatus.SIGNED,
                        ContractStatus.IN_PROGRESS,
                        ContractStatus.RENEWAL_DUE,
                        ContractStatus.COMPLETED,
                    }
                    or report.status is not PerformanceReportStatus.UPLOADED
                ):
                    return PerformanceExtractionApplyResult(outcome="INVALID_STATUS")
                if document.parse_status is not DocumentParseStatus.PROCESSING:
                    return PerformanceExtractionApplyResult(outcome="INVALID_STATUS")
                if (
                    report.extraction_started_at is None
                    or completed_at < report.extraction_started_at
                ):
                    raise ValueError("추출 완료 시각은 attempt 시작 전일 수 없습니다.")

                completed_report = replace(
                    report,
                    status=PerformanceReportStatus.EXTRACTED,
                    extracted_payload=extracted_payload,
                    updated_at=completed_at,
                )
                completed_document = replace(
                    document,
                    parse_status=DocumentParseStatus.COMPLETED,
                )
                self._mock_performance_reports[report_id] = completed_report
                self._mock_documents[document.id] = completed_document
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type="PERFORMANCE_REPORT_EXTRACTED",
                        actor_type="SYSTEM",
                        summary="광고효과 리포트의 지표 후보와 근거를 추출했습니다.",
                        created_at=completed_at,
                        payload={
                            "report_id": str(report_id),
                            "attempt_id": str(attempt_id),
                        },
                    )
                )
                return PerformanceExtractionApplyResult(
                    outcome="APPLIED",
                    report=completed_report,
                    source_document=completed_document,
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_report_id": str(report_id),
            "p_attempt_id": str(attempt_id),
            "p_extracted_payload": extracted_payload.model_dump(mode="json"),
            "p_completed_at": completed_at.isoformat(),
        }
        last_error = None
        for _ in range(2):
            try:
                response = await asyncio.to_thread(
                    lambda: client.rpc(
                        "complete_performance_report_extraction",
                        params,
                    ).execute()
                )
                payload = _rpc_json_payload(response.data)
                return _performance_extraction_apply_result_from_payload(payload)
            except ExternalStorageFailure:
                raise
            except Exception as error:
                last_error = error
        assert last_error is not None
        raise ExternalStorageFailure("광고효과 추출 결과 저장에 실패했습니다.") from last_error

    async def fail_performance_report_extraction(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        document_parse_status: DocumentParseStatus,
        failed_at: datetime,
    ) -> PerformanceExtractionApplyResult:
        if document_parse_status not in {
            DocumentParseStatus.FAILED,
            DocumentParseStatus.COMPLETED,
        }:
            raise ValueError("추출 실패 상태는 FAILED 또는 COMPLETED여야 합니다.")
        if failed_at.tzinfo is None:
            raise ValueError("추출 실패 시각은 시간대 정보를 포함해야 합니다.")

        if self.mode == "mock":
            async with self._mock_lock:
                owned = self._mock_performance_extraction_rows(
                    owner_id=owner_id,
                    contract_id=contract_id,
                    report_id=report_id,
                )
                if owned is None:
                    return PerformanceExtractionApplyResult(outcome="NOT_FOUND")
                contract, report, document = owned
                if report.extraction_attempt_id != attempt_id:
                    return PerformanceExtractionApplyResult(outcome="STALE")
                if (
                    contract.status
                    not in {
                        ContractStatus.SIGNED,
                        ContractStatus.IN_PROGRESS,
                        ContractStatus.RENEWAL_DUE,
                        ContractStatus.COMPLETED,
                    }
                    or report.status is not PerformanceReportStatus.UPLOADED
                ):
                    return PerformanceExtractionApplyResult(outcome="INVALID_STATUS")
                if (
                    report.extracted_payload is None
                    and report.current_revision_id is None
                    and report.revision_count == 0
                    and document.parse_status is document_parse_status
                ):
                    return PerformanceExtractionApplyResult(
                        outcome="APPLIED",
                        report=report,
                        source_document=document,
                    )
                if document.parse_status is not DocumentParseStatus.PROCESSING:
                    return PerformanceExtractionApplyResult(outcome="INVALID_STATUS")
                if report.extraction_started_at is None or failed_at < report.extraction_started_at:
                    raise ValueError("추출 실패 시각은 attempt 시작 전일 수 없습니다.")

                failed_report = replace(report, updated_at=failed_at)
                failed_document = replace(
                    document,
                    parse_status=document_parse_status,
                )
                self._mock_performance_reports[report_id] = failed_report
                self._mock_documents[document.id] = failed_document
                return PerformanceExtractionApplyResult(
                    outcome="APPLIED",
                    report=failed_report,
                    source_document=failed_document,
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_report_id": str(report_id),
            "p_attempt_id": str(attempt_id),
            "p_document_parse_status": document_parse_status.value,
            "p_failed_at": failed_at.isoformat(),
        }
        last_error = None
        for _ in range(2):
            try:
                response = await asyncio.to_thread(
                    lambda: client.rpc(
                        "fail_performance_report_extraction",
                        params,
                    ).execute()
                )
                payload = _rpc_json_payload(response.data)
                return _performance_extraction_apply_result_from_payload(payload)
            except ExternalStorageFailure:
                raise
            except Exception as error:
                last_error = error
        assert last_error is not None
        raise ExternalStorageFailure("광고효과 추출 실패 상태 저장에 실패했습니다.") from last_error

    def _mock_performance_extraction_rows(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
    ) -> tuple[ContractRecord, PerformanceReportAccess, DocumentRecord] | None:
        contract = self._mock_contracts.get(contract_id)
        report = self._mock_performance_reports.get(report_id)
        if (
            (owner_id, contract_id) not in self._mock_owned_contracts
            or contract is None
            or contract.owner_id != owner_id
            or report is None
            or report.contract_id != contract_id
        ):
            return None
        document = self._mock_documents.get(report.source_document_id)
        if (
            document is None
            or document.contract_id != contract_id
            or document.type is not DocumentType.PERFORMANCE_REPORT
        ):
            return None
        return contract, report, document

    async def get_report(self, *, report_id: UUID) -> PerformanceReport | None:
        if self.mode == "mock":
            async with self._mock_lock:
                access = self._mock_performance_reports.get(report_id)
                if access is None:
                    return None
                revisions = self._mock_performance_report_revisions.get(report_id, [])
                return _performance_report_from_access(access, revisions)

        client = self._require_live_client()
        try:
            report_response = await asyncio.to_thread(
                lambda: (
                    client.table("performance_reports")
                    .select(
                        "id,contract_id,period,source_document_id,status,"
                        "extracted_payload,current_revision_id,revision_count,"
                        "created_at,updated_at"
                    )
                    .eq("id", str(report_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("광고효과 리포트 조회에 실패했습니다.") from error
        if not report_response.data:
            return None
        report_row = report_response.data[0]

        try:
            (
                revision_rows,
                flags_by_revision,
                basis_by_flag,
                drafts_by_flag,
            ) = await self._live_performance_revision_rows(client, report_id=report_id)
            return _performance_report_from_rows(
                report_row=report_row,
                revision_rows=revision_rows,
                flags_by_revision=flags_by_revision,
                basis_by_flag=basis_by_flag,
                drafts_by_flag=drafts_by_flag,
            )
        except ExternalStorageFailure:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "광고효과 리포트 조회 결과가 올바르지 않습니다."
            ) from error

    async def get_owned_contract_performance_reports(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> list[PerformanceReport] | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                if (
                    (owner_id, contract_id) not in self._mock_owned_contracts
                    or contract is None
                    or contract.owner_id != owner_id
                ):
                    return None
                access_rows = sorted(
                    (
                        report
                        for report in self._mock_performance_reports.values()
                        if report.contract_id == contract_id
                    ),
                    key=lambda report: (report.period, str(report.id)),
                )
                return [
                    _performance_report_from_access(
                        access,
                        self._mock_performance_report_revisions.get(access.id, []),
                    )
                    for access in access_rows
                ]

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "get_owned_contract_performance_snapshot",
                    {
                        "p_owner_id": str(owner_id),
                        "p_contract_id": str(contract_id),
                    },
                ).execute()
            )
            payload = _rpc_json_payload(response.data)
            return _owned_contract_performance_reports_from_payload(
                payload,
                contract_id=contract_id,
            )
        except ExternalStorageFailure:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "계약별 광고효과 snapshot 조회 결과가 올바르지 않습니다."
            ) from error
        except Exception as error:
            raise ExternalStorageFailure("계약별 광고효과 snapshot 조회에 실패했습니다.") from error

    async def _live_performance_revision_rows(
        self,
        client: Client,
        *,
        report_id: UUID,
    ) -> tuple[list[dict], dict[str, list[dict]], dict[str, list[dict]], dict[str, dict]]:
        try:
            revisions_response = await asyncio.to_thread(
                lambda: (
                    client.table("performance_report_revisions")
                    .select(
                        "id,report_id,version,status,confirmed_payload,engagement_rate,"
                        "corrected_from_revision_id,correction_reason,confirmed_at"
                    )
                    .eq("report_id", str(report_id))
                    .order("version")
                    .execute()
                )
            )
            revision_rows: list[dict] = revisions_response.data or []
            revision_ids = [row["id"] for row in revision_rows]
            flags_by_revision: dict[str, list[dict]] = {}
            basis_by_flag: dict[str, list[dict]] = {}
            drafts_by_flag: dict[str, dict] = {}
            if not revision_ids:
                return revision_rows, flags_by_revision, basis_by_flag, drafts_by_flag

            flags_response = await asyncio.to_thread(
                lambda: (
                    client.table("performance_flags")
                    .select("*")
                    .in_("report_revision_id", revision_ids)
                    .execute()
                )
            )
            flag_rows: list[dict] = flags_response.data or []
            for row in flag_rows:
                flags_by_revision.setdefault(str(row["report_revision_id"]), []).append(row)
            flag_ids = [row["id"] for row in flag_rows]
            if flag_ids:
                basis_response = await asyncio.to_thread(
                    lambda: (
                        client.table("performance_flag_basis_terms")
                        .select("*")
                        .in_("flag_id", flag_ids)
                        .execute()
                    )
                )
                for row in basis_response.data or []:
                    basis_by_flag.setdefault(str(row["flag_id"]), []).append(row)
                drafts_response = await asyncio.to_thread(
                    lambda: (
                        client.table("performance_inquiry_drafts")
                        .select("*")
                        .in_("flag_id", flag_ids)
                        .execute()
                    )
                )
                for row in drafts_response.data or []:
                    drafts_by_flag[str(row["flag_id"])] = row
            return revision_rows, flags_by_revision, basis_by_flag, drafts_by_flag
        except Exception as error:
            raise ExternalStorageFailure(
                "광고효과 리포트 확정 이력 조회에 실패했습니다."
            ) from error

    async def confirm_performance_report_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        expected_revision: int,
        expected_comparison_revision_id: UUID | None,
        revision: PerformanceReportRevision,
    ) -> PerformanceReportConfirmResult:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                report = self._mock_performance_reports.get(report_id)
                if (
                    (owner_id, contract_id) not in self._mock_owned_contracts
                    or contract is None
                    or contract.owner_id != owner_id
                    or report is None
                    or report.contract_id != contract_id
                ):
                    return PerformanceReportConfirmResult(outcome="NOT_FOUND")
                if contract.status not in {
                    ContractStatus.SIGNED,
                    ContractStatus.IN_PROGRESS,
                    ContractStatus.RENEWAL_DUE,
                    ContractStatus.COMPLETED,
                }:
                    return PerformanceReportConfirmResult(outcome="CONTRACT_INVALID_STATUS")
                if report.status is PerformanceReportStatus.UPLOADED:
                    return PerformanceReportConfirmResult(outcome="REPORT_INVALID_STATUS")
                if report.revision_count != expected_revision:
                    return PerformanceReportConfirmResult(outcome="REVISION_CONFLICT")

                previous_period = _previous_performance_period(report.period)
                previous_report = next(
                    (
                        other
                        for other in self._mock_performance_reports.values()
                        if other.contract_id == contract_id
                        and other.period == previous_period
                        and other.status
                        in {PerformanceReportStatus.CONFIRMED, PerformanceReportStatus.FLAGGED}
                    ),
                    None,
                )
                current_comparison_revision_id = (
                    previous_report.current_revision_id if previous_report is not None else None
                )
                if current_comparison_revision_id != expected_comparison_revision_id:
                    return PerformanceReportConfirmResult(outcome="COMPARISON_REVISION_CONFLICT")

                later_exists = any(
                    other.contract_id == contract_id
                    and other.status
                    in {PerformanceReportStatus.CONFIRMED, PerformanceReportStatus.FLAGGED}
                    and other.period > report.period
                    for other in self._mock_performance_reports.values()
                )
                if later_exists:
                    return PerformanceReportConfirmResult(
                        outcome=(
                            "PERIOD_ORDER_CONFLICT"
                            if expected_revision == 0
                            else "CORRECTION_DEPENDENCY_EXISTS"
                        )
                    )

                history = [*self._mock_performance_report_revisions.get(report_id, []), revision]
                self._mock_performance_report_revisions[report_id] = history
                updated_report = replace(
                    report,
                    status=revision.status,
                    current_revision_id=revision.id,
                    revision_count=len(history),
                    updated_at=revision.confirmed_at,
                )
                self._mock_performance_reports[report_id] = updated_report
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type=(
                            f"PERFORMANCE_REPORT_{revision.status.value}"
                            if revision.version == 1
                            else "PERFORMANCE_REPORT_CORRECTED"
                        ),
                        actor_type="OWNER",
                        summary=(
                            "광고효과 리포트를 확정했습니다."
                            if revision.version == 1
                            else "광고효과 리포트를 정정했습니다."
                        ),
                        created_at=revision.confirmed_at,
                    )
                )
                return PerformanceReportConfirmResult(
                    outcome="CONFIRMED",
                    report=_performance_report_from_access(updated_report, history),
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_report_id": str(report_id),
            "p_expected_revision": expected_revision,
            "p_expected_comparison_revision_id": (
                str(expected_comparison_revision_id)
                if expected_comparison_revision_id is not None
                else None
            ),
            "p_revision_id": str(revision.id),
            "p_status": revision.status.value,
            "p_confirmed_payload": revision.confirmed_payload.model_dump(mode="json"),
            "p_engagement_rate": (
                str(revision.engagement_rate) if revision.engagement_rate is not None else None
            ),
            "p_corrected_from_revision_id": (
                str(revision.corrected_from_revision_id)
                if revision.corrected_from_revision_id is not None
                else None
            ),
            "p_correction_reason": revision.correction_reason,
            "p_confirmed_at": revision.confirmed_at.isoformat(),
            "p_flags": [_performance_flag_to_payload(flag) for flag in revision.flags],
            "p_inquiry_drafts": [
                {
                    "id": str(draft.id),
                    "flag_id": str(draft.flag_id),
                    "text": draft.text,
                    "template_version": draft.template_version,
                }
                for draft in revision.inquiry_drafts
            ],
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("confirm_performance_report_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("광고효과 리포트 확정 저장에 실패했습니다.") from error
        payload = _rpc_json_payload(response.data)
        try:
            return _performance_confirm_result_from_payload(
                payload,
                contract_id=contract_id,
                report_id=report_id,
                revision=revision,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "광고효과 리포트 확정 snapshot이 올바르지 않습니다."
            ) from error

    async def create_signed_access_url(
        self,
        *,
        path: str,
        expires_in_seconds: int,
    ) -> str:
        if self.mode == "mock":
            token = secrets.token_urlsafe(24)
            access_url = f"{self._mock_storage_access_base_url}/{token}"
            expires_at = self._clock() + timedelta(seconds=expires_in_seconds)
            signed_access = MockSignedAccess(
                token=token,
                path=path,
                expires_at=expires_at,
                expires_in_seconds=expires_in_seconds,
                access_url=access_url,
            )
            async with self._mock_lock:
                if path not in self._mock_objects:
                    raise ExternalStorageFailure("비공개 문서를 찾을 수 없습니다.")
                self._mock_signed_accesses[token] = signed_access
            return access_url

        client = self._require_live_client()
        try:
            result = await asyncio.to_thread(
                client.storage.from_(self.bucket).create_signed_url,
                path,
                expires_in_seconds,
            )
        except Exception as error:
            raise ExternalStorageFailure("원문 접근 URL 발급에 실패했습니다.") from error
        if not isinstance(result, dict):
            raise ExternalStorageFailure("원문 접근 URL 발급 결과가 올바르지 않습니다.")
        access_url = result.get("signedURL") or result.get("signedUrl")
        if not isinstance(access_url, str) or not access_url:
            raise ExternalStorageFailure("원문 접근 URL 발급 결과가 올바르지 않습니다.")
        return access_url

    async def get_mock_signed_object(self, *, token: str) -> MockPrivateObject | None:
        if self.mode != "mock":
            return None
        async with self._mock_lock:
            access = self._mock_signed_accesses.get(token)
            if access is None:
                return None
            if access.expires_at <= self._clock():
                self._mock_signed_accesses.pop(token, None)
                return None
            content = self._mock_objects.get(access.path)
            content_type = self._mock_object_content_types.get(access.path)
            if content is None or content_type is None:
                return None
            return MockPrivateObject(
                content=content,
                content_type=content_type,
            )

    async def save_understood_term_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: UnderstoodTermInput,
    ) -> UnderstoodTerm | None:
        understood_term = UnderstoodTerm(
            contract_id=contract_id,
            **payload.model_dump(),
        )
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                existing = self._mock_understood_terms.get(contract_id)
                if existing == understood_term:
                    return existing
                self._mock_understood_terms[contract_id] = understood_term
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type="UNDERSTOOD_TERMS_SAVED",
                        actor_type="OWNER",
                        summary="사용자 이해조건을 저장했습니다.",
                        created_at=self._clock(),
                    )
                )
            return understood_term

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_duration_text": payload.duration_text,
            "p_monthly_amount": payload.monthly_amount,
            "p_total_amount": payload.total_amount,
            "p_refund_text": payload.refund_text,
            "p_termination_text": payload.termination_text,
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("save_understood_term_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("사용자 이해조건 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return UnderstoodTerm.model_validate(row)

    async def get_understood_term(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> UnderstoodTerm | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                return self._mock_understood_terms.get(contract_id)

        if not await self.is_contract_owned(owner_id=owner_id, contract_id=contract_id):
            return None
        return await self._get_understood_term_for_owned_contract(contract_id=contract_id)

    async def _get_understood_term_for_owned_contract(
        self,
        *,
        contract_id: UUID,
    ) -> UnderstoodTerm | None:
        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("understood_terms")
                    .select(
                        "contract_id,duration_text,monthly_amount,total_amount,"
                        "refund_text,termination_text,source_type"
                    )
                    .eq("contract_id", str(contract_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("사용자 이해조건 조회에 실패했습니다.") from error
        if not response.data:
            return None
        return UnderstoodTerm.model_validate(response.data[0])

    async def _get_renewal_decision_for_owned_contract(
        self,
        *,
        contract_id: UUID,
    ) -> RenewalDecision | None:
        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("renewal_decisions")
                    .select("contract_id,decision,decided_at,revisit_review_item_ids")
                    .eq("contract_id", str(contract_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("재계약 의사 조회에 실패했습니다.") from error
        if not response.data:
            return None
        return RenewalDecision.model_validate(response.data[0])

    @staticmethod
    def _document_record_from_row(row) -> DocumentRecord:
        return DocumentRecord(
            id=UUID(str(row["id"])),
            contract_id=UUID(str(row["contract_id"])),
            type=DocumentType(row["type"]),
            parse_status=DocumentParseStatus(row["parse_status"]),
            storage_path=row["storage_path"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            page_count=row["page_count"],
            created_at=_parse_datetime(row["created_at"]),
        )

    async def create(
        self,
        *,
        owner_id: UUID,
        payload: ContractCreate,
        record: ContractRecord,
    ) -> ContractRecord:
        """Create a DRAFT contract and its creation audit event atomically."""

        if self.mode == "mock":
            async with self._mock_lock:
                self._mock_contracts[record.id] = record
                self._mock_owned_contracts.add((owner_id, record.id))
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=record.id,
                        event_type="CONTRACT_CREATED",
                        actor_type="OWNER",
                        summary="계약을 생성했습니다.",
                        created_at=record.created_at,
                    )
                )
            return record

        client = self._require_live_client()
        params = {
            "p_contract_id": str(record.id),
            "p_owner_id": str(owner_id),
            "p_title": payload.title,
            "p_counterparty_name": payload.counterparty_name,
            "p_created_at": record.created_at.isoformat(),
            "p_summary": "계약을 생성했습니다.",
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("create_contract_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("계약 생성 저장에 실패했습니다.") from error
        if not response.data:
            raise ExternalStorageFailure("계약 생성 결과를 확인할 수 없습니다.")
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _contract_record_from_row(row, owner_id=owner_id)

    async def get(self, *, owner_id: UUID, contract_id: UUID) -> ContractRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                record = self._mock_contracts.get(contract_id)
                if record is None:
                    return None
                return replace(
                    record,
                    understood_term=self._mock_understood_terms.get(contract_id),
                    renewal_decision=self._mock_renewal_decisions.get(contract_id),
                )

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("contracts")
                    .select("*")
                    .eq("id", str(contract_id))
                    .eq("owner_id", str(owner_id))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("계약 조회에 실패했습니다.") from error
        if not response.data:
            return None
        record = _contract_record_from_row(response.data[0], owner_id=owner_id)
        understood_term = await self._get_understood_term_for_owned_contract(
            contract_id=contract_id,
        )
        renewal_decision = await self._get_renewal_decision_for_owned_contract(
            contract_id=contract_id,
        )
        return replace(
            record,
            understood_term=understood_term,
            renewal_decision=renewal_decision,
        )

    async def list(self, *, owner_id: UUID) -> Sequence[ContractRecord]:
        if self.mode == "mock":
            async with self._mock_lock:
                return [
                    record
                    for record in self._mock_contracts.values()
                    if record.owner_id == owner_id
                ]

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("contracts").select("*").eq("owner_id", str(owner_id)).execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("계약 목록 조회에 실패했습니다.") from error
        return [_contract_record_from_row(row, owner_id=owner_id) for row in response.data or []]

    async def delete_discardable(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        deleted_at: datetime,
    ) -> ContractDeleteOutcome:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                if contract is None or contract.owner_id != owner_id:
                    return ContractDeleteOutcome.NOT_FOUND

                requests = [
                    request
                    for request in self._mock_adjustment_requests.values()
                    if request.contract_id == contract_id
                ]
                has_signature = any(
                    record.signature.contract_id == contract_id
                    for record in self._mock_signatures.values()
                )
                has_advanced_record = (
                    any(
                        record.agreement.contract_id == contract_id
                        for record in self._mock_agreements.values()
                    )
                    or any(
                        review.contract_id == contract_id
                        for review in self._mock_revised_contract_reviews.values()
                    )
                    or any(
                        report.contract_id == contract_id
                        for report in self._mock_performance_reports.values()
                    )
                )
                if (
                    contract.status not in _DISCARDABLE_CONTRACT_STATUSES
                    or any(
                        request.status is not AdjustmentRequestStatus.DRAFT
                        for request in requests
                    )
                    or has_signature
                    or has_advanced_record
                ):
                    return ContractDeleteOutcome.PROTECTED

                document_ids = {
                    document.id
                    for document in self._mock_documents.values()
                    if document.contract_id == contract_id
                }
                storage_paths = {
                    document.storage_path
                    for document in self._mock_documents.values()
                    if document.id in document_ids
                }
                request_ids = {request.id for request in requests}
                obligation_ids = {
                    obligation.id
                    for obligation in self._mock_obligations.values()
                    if obligation.contract_id == contract_id
                }
                resource_ids = {contract_id, *request_ids, *obligation_ids}

                self._mock_documents = {
                    key: value
                    for key, value in self._mock_documents.items()
                    if key not in document_ids
                }
                for path in storage_paths:
                    self._mock_objects.pop(path, None)
                    self._mock_object_content_types.pop(path, None)
                self._mock_signed_accesses = {
                    key: value
                    for key, value in self._mock_signed_accesses.items()
                    if value.path not in storage_paths
                }
                self._mock_analysis_tasks = {
                    key: value
                    for key, value in self._mock_analysis_tasks.items()
                    if value.contract_id != contract_id
                }
                self._mock_obligations = {
                    key: value
                    for key, value in self._mock_obligations.items()
                    if value.contract_id != contract_id
                }
                self._mock_review_items = {
                    key: value
                    for key, value in self._mock_review_items.items()
                    if value.contract_id != contract_id
                }
                self._mock_review_item_details = {
                    key: value
                    for key, value in self._mock_review_item_details.items()
                    if value.contract_id != contract_id
                }
                self._mock_adjustment_requests = {
                    key: value
                    for key, value in self._mock_adjustment_requests.items()
                    if key not in request_ids
                }
                self._mock_adjustment_responses = {
                    key: value
                    for key, value in self._mock_adjustment_responses.items()
                    if key not in request_ids
                }
                self._mock_final_clauses = {
                    key: value
                    for key, value in self._mock_final_clauses.items()
                    if key not in request_ids
                }
                self._mock_public_tokens = {
                    key: value
                    for key, value in self._mock_public_tokens.items()
                    if value.resource_id not in resource_ids
                }
                self._mock_idempotency = {
                    key: value
                    for key, value in self._mock_idempotency.items()
                    if key[2] not in resource_ids
                }
                self._mock_audit_events = [
                    event for event in self._mock_audit_events if event.contract_id != contract_id
                ]
                self._mock_understood_terms.pop(contract_id, None)
                self._mock_renewal_decisions.pop(contract_id, None)
                self._mock_owned_contracts.discard((owner_id, contract_id))
                self._mock_contracts.pop(contract_id, None)
                return ContractDeleteOutcome.DELETED

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_deleted_at": deleted_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("delete_discardable_contract", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("계약 삭제에 실패했습니다.") from error
        row = response.data
        if isinstance(row, list):
            row = row[0] if len(row) == 1 else None
        if not isinstance(row, dict):
            raise ExternalStorageFailure("계약 삭제 결과가 올바르지 않습니다.")
        try:
            outcome = ContractDeleteOutcome(str(row["outcome"]))
            storage_paths = row.get("storage_paths", [])
            if not isinstance(storage_paths, list) or not all(
                isinstance(path, str) and path for path in storage_paths
            ):
                raise ValueError("invalid storage paths")
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure("계약 삭제 결과가 올바르지 않습니다.") from error

        if outcome is not ContractDeleteOutcome.DELETED:
            return outcome

        cleanup_succeeded = True
        for path in storage_paths:
            try:
                await self.delete_private_object(path=path)
            except ExternalStorageFailure:
                cleanup_succeeded = False
                logger.warning(
                    "Deleted contract has a pending private storage cleanup.",
                    extra={"contract_id": str(contract_id)},
                )
        if cleanup_succeeded:
            try:
                await asyncio.to_thread(
                    lambda: client.rpc(
                        "mark_contract_storage_cleaned",
                        {
                            "p_owner_id": str(owner_id),
                            "p_contract_id": str(contract_id),
                            "p_cleaned_at": self._clock().isoformat(),
                        },
                    ).execute()
                )
            except Exception:
                logger.warning(
                    "Contract storage cleanup marker could not be persisted.",
                    extra={"contract_id": str(contract_id)},
                )
        return outcome

    async def get_dashboard(
        self,
        *,
        owner_id: UUID,
        today: date,
    ) -> DashboardRecord:
        if self.mode == "mock":
            async with self._mock_lock:
                return self._get_mock_dashboard(owner_id=owner_id, today=today)

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_today": today.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("get_owner_dashboard", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("대시보드 집계 조회에 실패했습니다.") from error
        row = response.data
        if isinstance(row, list):
            row = row[0] if len(row) == 1 else None
        if not isinstance(row, dict):
            raise ExternalStorageFailure("대시보드 집계 결과가 올바르지 않습니다.")
        try:
            return _dashboard_record_from_row(row)
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure("대시보드 집계 결과가 올바르지 않습니다.") from error

    def _get_mock_dashboard(
        self,
        *,
        owner_id: UUID,
        today: date,
    ) -> DashboardRecord:
        contracts = {
            contract.id: contract
            for contract in self._mock_contracts.values()
            if contract.owner_id == owner_id
        }
        contract_ids = set(contracts)
        status_overrides = {item.id: item.status for item in self._mock_review_items.values()}
        unresolved_items = [
            item
            for item in self._mock_review_item_details.values()
            if item.contract_id in contract_ids
            and status_overrides.get(item.id, item.status)
            in {
                ReviewItemStatus.UNREVIEWED,
                ReviewItemStatus.SELECTED,
                ReviewItemStatus.SENT,
            }
        ]
        signal_counts = Counter(item.type for item in unresolved_items)
        most_common_signal = None
        if signal_counts:
            highest_count = max(signal_counts.values())
            most_common_signal = next(
                signal
                for signal in DASHBOARD_SIGNAL_TIE_BREAK
                if signal_counts[signal] == highest_count
            )

        owned_requests = {
            request.id: request
            for request in self._mock_adjustment_requests.values()
            if request.contract_id in contract_ids
        }

        def owned_review_item_id(
            *,
            request_id: UUID,
            review_item_id: UUID,
        ) -> UUID | None:
            request = owned_requests.get(request_id)
            review_item = self._mock_review_items.get(review_item_id)
            if (
                request is None
                or review_item is None
                or review_item.contract_id != request.contract_id
            ):
                return None
            return review_item_id

        requested_item_ids = {
            review_item_id
            for request in owned_requests.values()
            if request.status != AdjustmentRequestStatus.DRAFT
            for item in request.items
            if (
                review_item_id := owned_review_item_id(
                    request_id=request.id,
                    review_item_id=item.review_item_id,
                )
            )
            is not None
        }
        agreed_item_ids = {
            review_item_id
            for request_id, clauses in self._mock_final_clauses.items()
            for clause in clauses
            if clause.resolution
            in {
                AdjustmentResolution.ACCEPT_REQUEST,
                AdjustmentResolution.ACCEPT_COUNTERPROPOSAL,
            }
            and (
                review_item_id := owned_review_item_id(
                    request_id=request_id,
                    review_item_id=clause.review_item_id,
                )
            )
            is not None
        }
        rejected_item_ids = {
            review_item_id
            for request_id, responses in self._mock_adjustment_responses.items()
            for response in responses
            if response.decision == AdjustmentResponseDecision.REJECT
            and (
                review_item_id := owned_review_item_id(
                    request_id=request_id,
                    review_item_id=response.review_item_id,
                )
            )
            is not None
        }
        rejected_item_ids.update(
            review_item_id
            for request_id, clauses in self._mock_final_clauses.items()
            for clause in clauses
            if clause.resolution == AdjustmentResolution.KEEP_ORIGINAL
            and (
                review_item_id := owned_review_item_id(
                    request_id=request_id,
                    review_item_id=clause.review_item_id,
                )
            )
            is not None
        )

        obligations = [
            obligation
            for obligation in self._mock_obligations.values()
            if obligation.contract_id in contract_ids
        ]
        committed_statuses = {
            ContractStatus.SIGNED,
            ContractStatus.IN_PROGRESS,
            ContractStatus.RENEWAL_DUE,
            ContractStatus.COMPLETED,
        }
        approved_contract_ids = {
            obligation.contract_id
            for obligation in obligations
            if obligation.status == ObligationStatus.APPROVED
        }
        return DashboardRecord(
            total=len(contracts),
            signing=sum(
                contract.status == ContractStatus.SIGNING for contract in contracts.values()
            ),
            in_progress=sum(
                contract.status
                in {
                    ContractStatus.IN_PROGRESS,
                    ContractStatus.RENEWAL_DUE,
                }
                for contract in contracts.values()
            ),
            completed=sum(
                contract.status == ContractStatus.COMPLETED for contract in contracts.values()
            ),
            expiring_soon=sum(
                _contract_expires_soon(contract=contract, today=today)
                for contract in contracts.values()
            ),
            unresolved_signals=len(unresolved_items),
            adjustment_requested_clauses=len(requested_item_ids),
            adjustment_agreed_clauses=len(agreed_item_ids),
            adjustment_rejected_clauses=len(rejected_item_ids),
            obligation_pending=sum(
                obligation.status == ObligationStatus.PENDING for obligation in obligations
            ),
            obligation_submitted=sum(
                obligation.status == ObligationStatus.SUBMITTED for obligation in obligations
            ),
            obligation_approved=sum(
                obligation.status == ObligationStatus.APPROVED for obligation in obligations
            ),
            total_committed=sum(
                contract.total_amount or 0
                for contract in contracts.values()
                if contract.status in committed_statuses
            ),
            payment_condition_met_amount=sum(
                contracts[contract_id].total_amount or 0 for contract_id in approved_contract_ids
            ),
            most_common_signal=most_common_signal,
        )

    async def list_owned_obligations(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> Sequence[ObligationRecord] | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                obligation = self._mock_obligations.get(contract_id)
                return [] if obligation is None else [_obligation_record_from_mock(obligation)]

        if not await self.is_contract_owned(owner_id=owner_id, contract_id=contract_id):
            return None
        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("obligations")
                    .select(
                        "id,contract_id,title,due_date,assignee,evidence_type,"
                        "source_document_id,source_page,source_text,confidence,"
                        "evidence_url,status,submitted_at,reviewed_at,"
                        "payment_condition_met"
                    )
                    .eq("contract_id", str(contract_id))
                    .order("due_date")
                    .order("id")
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("이행 항목 목록 조회에 실패했습니다.") from error
        return [_obligation_record_from_row(row) for row in response.data or []]

    async def create_obligation_evidence_link_idempotent(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        obligation_id: UUID,
        idempotency_key: UUID,
        request_hash: str,
        public_token: PublicTokenRecord,
    ) -> EvidenceLinkCreateResult:
        if (
            public_token.scope != PublicTokenScope.OBLIGATION_EVIDENCE
            or public_token.resource_id != obligation_id
            or public_token.expires_at <= public_token.created_at
            or len(request_hash) != 64
        ):
            raise ValueError("증빙 제출 공개 토큰 정보가 올바르지 않습니다.")

        if self.mode == "mock":
            record_key = (
                owner_id,
                IdempotencyOperation.EVIDENCE_LINK_CREATE,
                obligation_id,
                idempotency_key,
            )
            async with self._mock_lock:
                existing = self._mock_idempotency.get(record_key)
                if existing is not None:
                    if existing.request_hash != request_hash:
                        return EvidenceLinkCreateResult(
                            outcome=EvidenceLinkCreateOutcome.IDEMPOTENCY_CONFLICT
                        )
                    if existing.response_payload is None:
                        return EvidenceLinkCreateResult(
                            outcome=EvidenceLinkCreateOutcome.IDEMPOTENCY_PENDING
                        )
                    return EvidenceLinkCreateResult(
                        outcome=EvidenceLinkCreateOutcome.REPLAY,
                        token_id=UUID(str(existing.response_payload["token_id"])),
                        expires_at=_parse_datetime(existing.response_payload["expires_at"]),
                    )
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return EvidenceLinkCreateResult(outcome=EvidenceLinkCreateOutcome.NOT_FOUND)
                obligation = self._mock_obligations.get(contract_id)
                if obligation is None or obligation.id != obligation_id:
                    return EvidenceLinkCreateResult(outcome=EvidenceLinkCreateOutcome.NOT_FOUND)
                contract = self._mock_contracts.get(contract_id)
                if (
                    contract is None
                    or contract.status not in {ContractStatus.SIGNED, ContractStatus.IN_PROGRESS}
                    or obligation.status != ObligationStatus.PENDING
                ):
                    return EvidenceLinkCreateResult(
                        outcome=EvidenceLinkCreateOutcome.INVALID_STATUS_TRANSITION
                    )
                if public_token.token_hash in self._mock_public_tokens:
                    raise ExternalStorageFailure("증빙 제출 링크 저장에 실패했습니다.")
                replay_payload = {
                    "token_id": str(public_token.id),
                    "expires_at": public_token.expires_at.isoformat(),
                }
                self._mock_idempotency[record_key] = IdempotencyRecord(
                    owner_id=owner_id,
                    operation=IdempotencyOperation.EVIDENCE_LINK_CREATE,
                    resource_id=obligation_id,
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=201,
                    response_payload=replay_payload,
                    created_at=public_token.created_at,
                )
                self._mock_public_tokens[public_token.token_hash] = public_token
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type="EVIDENCE_LINK_CREATED",
                        actor_type="OWNER",
                        summary="산출물 증빙 제출 링크를 생성했습니다.",
                        created_at=public_token.created_at,
                    )
                )
                return EvidenceLinkCreateResult(
                    outcome=EvidenceLinkCreateOutcome.CREATED,
                    token_id=public_token.id,
                    expires_at=public_token.expires_at,
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_obligation_id": str(obligation_id),
            "p_idempotency_key": str(idempotency_key),
            "p_request_hash": request_hash,
            "p_public_token_id": str(public_token.id),
            "p_token_hash": public_token.token_hash,
            "p_token_scope": public_token.scope.value,
            "p_token_resource_id": str(public_token.resource_id),
            "p_token_expires_at": public_token.expires_at.isoformat(),
            "p_token_created_at": public_token.created_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "create_obligation_evidence_link_idempotent",
                    params,
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("증빙 제출 링크 저장에 실패했습니다.") from error
        payload = response.data[0] if isinstance(response.data, list) else response.data
        if not isinstance(payload, dict):
            raise ExternalStorageFailure("증빙 제출 링크 저장 결과를 확인할 수 없습니다.")
        try:
            outcome = EvidenceLinkCreateOutcome(payload["outcome"])
            token_id = payload.get("token_id")
            expires_at = payload.get("expires_at")
            return EvidenceLinkCreateResult(
                outcome=outcome,
                token_id=UUID(str(token_id)) if token_id is not None else None,
                expires_at=(_parse_datetime(expires_at) if expires_at is not None else None),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "증빙 제출 링크 저장 결과를 확인할 수 없습니다."
            ) from error

    async def submit_obligation_evidence_with_audit(
        self,
        *,
        public_token: PublicTokenRecord,
        evidence_url: str,
        submitted_at: datetime,
    ) -> EvidenceSubmissionOutcome:
        if public_token.scope != PublicTokenScope.OBLIGATION_EVIDENCE:
            return EvidenceSubmissionOutcome.NOT_FOUND

        if self.mode == "mock":
            async with self._mock_lock:
                stored_token = self._mock_public_tokens.get(public_token.token_hash)
                if (
                    stored_token is None
                    or stored_token.id != public_token.id
                    or stored_token.scope != PublicTokenScope.OBLIGATION_EVIDENCE
                    or stored_token.resource_id != public_token.resource_id
                    or stored_token.revoked_at is not None
                ):
                    return EvidenceSubmissionOutcome.NOT_FOUND
                if stored_token.expires_at <= submitted_at:
                    return EvidenceSubmissionOutcome.EXPIRED
                obligation = next(
                    (
                        item
                        for item in self._mock_obligations.values()
                        if item.id == stored_token.resource_id
                    ),
                    None,
                )
                if obligation is None:
                    return EvidenceSubmissionOutcome.NOT_FOUND
                if obligation.status != ObligationStatus.PENDING:
                    return EvidenceSubmissionOutcome.INVALID_STATUS_TRANSITION
                self._mock_obligations[obligation.contract_id] = replace(
                    obligation,
                    evidence_url=evidence_url,
                    status=ObligationStatus.SUBMITTED,
                    submitted_at=submitted_at,
                    reviewed_at=None,
                    payment_condition_met=False,
                    updated_at=submitted_at,
                )
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=obligation.contract_id,
                        event_type="EVIDENCE_SUBMITTED",
                        actor_type="AGENCY",
                        summary="대행사가 산출물 증빙 URL을 제출했습니다.",
                        created_at=submitted_at,
                    )
                )
                return EvidenceSubmissionOutcome.SUBMITTED

        client = self._require_live_client()
        params = {
            "p_public_token_id": str(public_token.id),
            "p_token_hash": public_token.token_hash,
            "p_obligation_id": str(public_token.resource_id),
            "p_evidence_url": evidence_url,
            "p_submitted_at": submitted_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "submit_obligation_evidence_with_audit",
                    params,
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("증빙 URL 제출 저장에 실패했습니다.") from error
        payload = response.data[0] if isinstance(response.data, list) else response.data
        try:
            return EvidenceSubmissionOutcome(payload)
        except (TypeError, ValueError) as error:
            raise ExternalStorageFailure("증빙 URL 제출 저장 결과를 확인할 수 없습니다.") from error

    async def review_obligation_evidence_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        obligation_id: UUID,
        decision: ObligationStatus,
        reviewed_at: datetime,
    ) -> EvidenceReviewResult:
        if decision not in {ObligationStatus.APPROVED, ObligationStatus.DISPUTED}:
            raise ValueError("증빙 검토 결정은 APPROVED 또는 DISPUTED여야 합니다.")

        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return EvidenceReviewResult(
                        outcome=EvidenceReviewOutcome.NOT_FOUND,
                        obligation=None,
                    )
                obligation = self._mock_obligations.get(contract_id)
                if obligation is None or obligation.id != obligation_id:
                    return EvidenceReviewResult(
                        outcome=EvidenceReviewOutcome.NOT_FOUND,
                        obligation=None,
                    )
                if obligation.status != ObligationStatus.SUBMITTED:
                    return EvidenceReviewResult(
                        outcome=EvidenceReviewOutcome.INVALID_STATUS_TRANSITION,
                        obligation=_obligation_record_from_mock(obligation),
                    )

                reviewed = replace(
                    obligation,
                    status=decision,
                    reviewed_at=reviewed_at,
                    payment_condition_met=decision == ObligationStatus.APPROVED,
                    updated_at=reviewed_at,
                )
                self._mock_obligations[contract_id] = reviewed
                event_type = (
                    "EVIDENCE_APPROVED"
                    if decision == ObligationStatus.APPROVED
                    else "EVIDENCE_DISPUTED"
                )
                summary = (
                    "소유자가 산출물 증빙을 승인했습니다."
                    if decision == ObligationStatus.APPROVED
                    else "소유자가 산출물 증빙에 이의를 제기했습니다."
                )
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type=event_type,
                        actor_type="OWNER",
                        summary=summary,
                        created_at=reviewed_at,
                    )
                )
                return EvidenceReviewResult(
                    outcome=EvidenceReviewOutcome.REVIEWED,
                    obligation=_obligation_record_from_mock(reviewed),
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_obligation_id": str(obligation_id),
            "p_decision": decision.value,
            "p_reviewed_at": reviewed_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "review_obligation_evidence_with_audit",
                    params,
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("증빙 검토 저장에 실패했습니다.") from error
        payload = response.data[0] if isinstance(response.data, list) else response.data
        if not isinstance(payload, dict):
            raise ExternalStorageFailure("증빙 검토 저장 결과를 확인할 수 없습니다.")
        try:
            outcome = EvidenceReviewOutcome(payload["outcome"])
            obligation_payload = payload.get("obligation")
            return EvidenceReviewResult(
                outcome=outcome,
                obligation=(
                    _obligation_record_from_row(obligation_payload)
                    if isinstance(obligation_payload, dict)
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure("증빙 검토 저장 결과를 확인할 수 없습니다.") from error

    async def list_audit_events(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> Sequence[AuditEventRecord] | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                return [
                    AuditEventRecord(
                        id=event.id,
                        contract_id=event.contract_id,
                        event_type=event.event_type,
                        actor_type=event.actor_type,
                        summary=event.summary,
                        created_at=event.created_at,
                    )
                    for event in self._mock_audit_events
                    if event.contract_id == contract_id
                ]

        if not await self.is_contract_owned(owner_id=owner_id, contract_id=contract_id):
            return None
        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("audit_events")
                    .select("id,contract_id,event_type,actor_type,summary,created_at")
                    .eq("contract_id", str(contract_id))
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("계약 감사 타임라인 조회에 실패했습니다.") from error
        return [_audit_event_record_from_row(row) for row in response.data or []]

    async def save_renewal_decision_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        decision: RenewalDecisionType,
        today: date,
        decided_at: datetime,
    ) -> RenewalDecisionSaveResult:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                if contract is None or (owner_id, contract_id) not in self._mock_owned_contracts:
                    return RenewalDecisionSaveResult(
                        outcome=RenewalDecisionSaveOutcome.NOT_FOUND,
                        decision=None,
                    )
                if not _is_contract_in_renewal_review_window(contract, today=today):
                    return RenewalDecisionSaveResult(
                        outcome=RenewalDecisionSaveOutcome.OUTSIDE_REVIEW_WINDOW,
                        decision=None,
                    )

                existing = self._mock_renewal_decisions.get(contract_id)
                if existing is not None and existing.decision == decision:
                    return RenewalDecisionSaveResult(
                        outcome=RenewalDecisionSaveOutcome.UNCHANGED,
                        decision=existing,
                    )

                revisit_review_item_ids: list[UUID] = []
                if decision == RenewalDecisionType.RENEW_WITH_CHANGES:
                    revisit_ids = {
                        item.id
                        for item in self._mock_review_items.values()
                        if item.contract_id == contract_id
                        and item.status == ReviewItemStatus.KEPT_ORIGINAL
                    }
                    for request_id, responses in self._mock_adjustment_responses.items():
                        request = self._mock_adjustment_requests.get(request_id)
                        if request is None or request.contract_id != contract_id:
                            continue
                        revisit_ids.update(
                            response.review_item_id
                            for response in responses
                            if response.decision == AdjustmentResponseDecision.REJECT
                        )
                    revisit_review_item_ids = sorted(revisit_ids, key=str)

                saved = RenewalDecision(
                    contract_id=contract_id,
                    decision=decision,
                    decided_at=decided_at,
                    revisit_review_item_ids=revisit_review_item_ids,
                )
                self._mock_renewal_decisions[contract_id] = saved
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type="RENEWAL_DECISION_SAVED",
                        actor_type="OWNER",
                        summary="만료·재계약 의사를 저장했습니다.",
                        created_at=decided_at,
                    )
                )
                return RenewalDecisionSaveResult(
                    outcome=RenewalDecisionSaveOutcome.SAVED,
                    decision=saved,
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_decision": decision.value,
            "p_today": today.isoformat(),
            "p_decided_at": decided_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "save_renewal_decision_with_audit",
                    params,
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("재계약 의사 저장에 실패했습니다.") from error
        payload = response.data[0] if isinstance(response.data, list) else response.data
        if not isinstance(payload, dict):
            raise ExternalStorageFailure("재계약 의사 저장 결과를 확인할 수 없습니다.")
        outcome = RenewalDecisionSaveOutcome(payload["outcome"])
        decision_payload = payload.get("decision")
        return RenewalDecisionSaveResult(
            outcome=outcome,
            decision=(
                RenewalDecision.model_validate(decision_payload)
                if isinstance(decision_payload, dict)
                else None
            ),
        )

    async def create_public_token(self, *, record: PublicTokenRecord) -> PublicTokenRecord:
        if self.mode == "mock":
            async with self._mock_lock:
                if record.token_hash in self._mock_public_tokens:
                    raise ExternalStorageFailure("공개 토큰 저장에 실패했습니다.")
                self._mock_public_tokens[record.token_hash] = record
            return record

        client = self._require_live_client()
        payload = {
            "id": str(record.id),
            "token_hash": record.token_hash,
            "scope": record.scope.value,
            "resource_id": str(record.resource_id),
            "expires_at": record.expires_at.isoformat(),
            "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
            "created_at": record.created_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.table("public_tokens").insert(payload).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("공개 토큰 저장에 실패했습니다.") from error
        if not response.data:
            raise ExternalStorageFailure("공개 토큰 저장 결과를 확인할 수 없습니다.")
        return _public_token_record_from_row(response.data[0])

    async def get_public_token_by_hash(self, *, token_hash: str) -> PublicTokenRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                return self._mock_public_tokens.get(token_hash)

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("public_tokens")
                    .select("id,token_hash,scope,resource_id,expires_at,revoked_at,created_at")
                    .eq("token_hash", token_hash)
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("공개 토큰 조회에 실패했습니다.") from error
        if not response.data:
            return None
        return _public_token_record_from_row(response.data[0])

    async def claim_idempotency(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_hash: str,
        created_at: datetime,
    ) -> IdempotencyClaim:
        if self.mode == "mock":
            record_key = (owner_id, operation, resource_id, key)
            async with self._mock_lock:
                record = self._mock_idempotency.get(record_key)
                if record is None:
                    record = IdempotencyRecord(
                        owner_id=owner_id,
                        operation=operation,
                        resource_id=resource_id,
                        key=key,
                        request_hash=request_hash,
                        response_status=None,
                        response_payload=None,
                        created_at=created_at,
                    )
                    self._mock_idempotency[record_key] = record
                    return IdempotencyClaim(outcome="NEW", record=record)
                if record.request_hash != request_hash:
                    return IdempotencyClaim(outcome="CONFLICT", record=record)
                outcome = "REPLAY" if record.response_status is not None else "PENDING"
                return IdempotencyClaim(outcome=outcome, record=record)

        client = self._require_live_client()
        params = _idempotency_params(
            owner_id=owner_id,
            operation=operation,
            resource_id=resource_id,
            key=key,
            request_hash=request_hash,
            created_at=created_at,
        )
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("claim_idempotency", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("멱등성 키 저장에 실패했습니다.") from error
        if not response.data:
            raise ExternalStorageFailure("멱등성 키 저장 결과를 확인할 수 없습니다.")
        payload = response.data[0] if isinstance(response.data, list) else response.data
        record_data = payload.get("record")
        return IdempotencyClaim(
            outcome=payload["outcome"],
            record=_idempotency_record_from_row(record_data) if record_data else None,
        )

    async def get_idempotency(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
    ) -> IdempotencyRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                return self._mock_idempotency.get((owner_id, operation, resource_id, key))

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("idempotency_records")
                    .select("*")
                    .eq("owner_id", str(owner_id))
                    .eq("operation", operation.value)
                    .eq("resource_id", str(resource_id))
                    .eq("idempotency_key", str(key))
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("멱등성 키 조회에 실패했습니다.") from error
        if not response.data:
            return None
        return _idempotency_record_from_row(response.data[0])

    async def complete_idempotency(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_hash: str,
        response_status: int,
        response_payload: dict[str, object],
    ) -> IdempotencyRecord:
        if self.mode == "mock":
            record_key = (owner_id, operation, resource_id, key)
            async with self._mock_lock:
                record = self._mock_idempotency.get(record_key)
                if record is None or record.request_hash != request_hash:
                    raise ExternalStorageFailure("멱등성 키 저장 상태가 변경되었습니다.")
                if record.response_status is not None:
                    if (
                        record.response_status == response_status
                        and record.response_payload == response_payload
                    ):
                        return record
                    raise ExternalStorageFailure("완료된 멱등성 응답은 변경할 수 없습니다.")
                completed = IdempotencyRecord(
                    owner_id=record.owner_id,
                    operation=record.operation,
                    resource_id=record.resource_id,
                    key=record.key,
                    request_hash=record.request_hash,
                    response_status=response_status,
                    response_payload=dict(response_payload),
                    created_at=record.created_at,
                )
                self._mock_idempotency[record_key] = completed
                return completed

        client = self._require_live_client()
        params = _idempotency_params(
            owner_id=owner_id,
            operation=operation,
            resource_id=resource_id,
            key=key,
            request_hash=request_hash,
        ) | {
            "p_response_status": response_status,
            "p_response_payload": response_payload,
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("complete_idempotency", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("멱등성 응답 저장에 실패했습니다.") from error
        if not response.data:
            raise ExternalStorageFailure("멱등성 응답 저장 결과를 확인할 수 없습니다.")
        payload = response.data[0] if isinstance(response.data, list) else response.data
        return _idempotency_record_from_row(payload)

    async def abandon_idempotency(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_hash: str,
    ) -> None:
        if self.mode == "mock":
            record_key = (owner_id, operation, resource_id, key)
            async with self._mock_lock:
                record = self._mock_idempotency.get(record_key)
                if record is not None and record.request_hash == request_hash:
                    self._mock_idempotency.pop(record_key, None)
            return

        client = self._require_live_client()
        params = _idempotency_params(
            owner_id=owner_id,
            operation=operation,
            resource_id=resource_id,
            key=key,
            request_hash=request_hash,
        )
        try:
            await asyncio.to_thread(lambda: client.rpc("abandon_idempotency", params).execute())
        except Exception as error:
            raise ExternalStorageFailure("멱등성 예약 정리에 실패했습니다.") from error

    async def fail_stale_processing_analysis_jobs(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[AnalysisTaskRecord, ...]:
        if stale_before.tzinfo is None:
            raise ValueError("stale_before must be timezone-aware.")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")

        if self.mode == "mock":
            async with self._mock_lock:
                candidates = sorted(
                    (
                        task
                        for task in self._mock_analysis_tasks.values()
                        if task.status == AnalysisStatus.PROCESSING
                        and task.updated_at <= stale_before
                    ),
                    key=lambda item: (item.updated_at, str(item.id)),
                )[:limit]
                now = self._clock()
                failed_tasks: list[AnalysisTaskRecord] = []
                for candidate in candidates:
                    current = self._mock_analysis_tasks.get(candidate.id)
                    if (
                        current is None
                        or current.status != AnalysisStatus.PROCESSING
                        or current.updated_at > stale_before
                    ):
                        continue
                    failed = replace(
                        current,
                        status=AnalysisStatus.FAILED,
                        error_code=ErrorCode.DOCUMENT_PARSE_FAILED,
                        result=None,
                        updated_at=now,
                    )
                    self._mock_analysis_tasks[current.id] = failed
                    for document_id in (
                        current.document_id,
                        *current.supporting_document_ids,
                    ):
                        document = self._mock_documents.get(document_id)
                        if document is not None:
                            self._mock_documents[document_id] = replace(
                                document,
                                parse_status=DocumentParseStatus.FAILED,
                            )
                    self._mock_audit_events.append(
                        MockAuditEvent(
                            id=uuid4(),
                            contract_id=current.contract_id,
                            event_type="ANALYSIS_FAILED",
                            actor_type="SYSTEM",
                            summary="처리 제한 시간을 초과한 계약 분석을 실패 처리했습니다.",
                            created_at=now,
                        )
                    )
                    failed_tasks.append(failed)
                return tuple(failed_tasks)

        client = self._require_live_client()
        params = {
            "p_stale_before": stale_before.isoformat(),
            "p_limit": limit,
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "fail_stale_processing_analysis_jobs",
                    params,
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure(
                "처리 제한 시간을 초과한 분석 작업 정리에 실패했습니다."
            ) from error
        rows = response.data or []
        if not isinstance(rows, list):
            raise ExternalStorageFailure(
                "처리 제한 시간을 초과한 분석 작업 결과가 올바르지 않습니다."
            )
        try:
            return tuple(_analysis_task_record_from_row(row) for row in rows)
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "처리 제한 시간을 초과한 분석 작업 결과가 올바르지 않습니다."
            ) from error

    async def list_stale_queued_analysis_jobs(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[QueuedAnalysisJob, ...]:
        if stale_before.tzinfo is None:
            raise ValueError("stale_before must be timezone-aware.")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")

        if self.mode == "mock":
            async with self._mock_lock:
                jobs = [
                    QueuedAnalysisJob(
                        owner_id=contract.owner_id,
                        task_id=task.id,
                        created_at=task.created_at,
                    )
                    for task in self._mock_analysis_tasks.values()
                    if task.status == AnalysisStatus.QUEUED
                    and task.created_at <= stale_before
                    and (contract := self._mock_contracts.get(task.contract_id)) is not None
                ]
                jobs.sort(key=lambda item: (item.created_at, str(item.task_id)))
                return tuple(jobs[:limit])

        client = self._require_live_client()
        params = {
            "p_stale_before": stale_before.isoformat(),
            "p_limit": limit,
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("list_stale_queued_analysis_jobs", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("대기 중인 분석 작업 조회에 실패했습니다.") from error
        rows = response.data or []
        if not isinstance(rows, list):
            raise ExternalStorageFailure("대기 중인 분석 작업 조회 결과가 올바르지 않습니다.")
        try:
            return tuple(
                QueuedAnalysisJob(
                    owner_id=UUID(str(row["owner_id"])),
                    task_id=UUID(str(row["task_id"])),
                    created_at=_parse_datetime(row["created_at"]),
                )
                for row in rows
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalStorageFailure(
                "대기 중인 분석 작업 조회 결과가 올바르지 않습니다."
            ) from error

    async def get_latest_analysis_task(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> AnalysisTaskRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                candidates = [
                    task
                    for task in self._mock_analysis_tasks.values()
                    if task.contract_id == contract_id
                ]
                if not candidates:
                    return None
                return max(candidates, key=lambda item: (item.created_at, str(item.id)))

        if not await self.is_contract_owned(owner_id=owner_id, contract_id=contract_id):
            return None
        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("analysis_tasks")
                    .select("*")
                    .eq("contract_id", str(contract_id))
                    .order("created_at", desc=True)
                    .order("id", desc=True)
                    .limit(1)
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("최근 분석 작업 조회에 실패했습니다.") from error
        if not response.data:
            return None
        return _analysis_task_record_from_row(response.data[0])

    async def start_analysis_with_audit(
        self,
        *,
        owner_id: UUID,
        task: AnalysisTaskRecord,
        restart: bool,
    ) -> AnalysisTaskRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(task.contract_id)
                if contract is None or contract.owner_id != owner_id:
                    return None
                active = any(
                    item.contract_id == task.contract_id
                    and item.status in {AnalysisStatus.QUEUED, AnalysisStatus.PROCESSING}
                    for item in self._mock_analysis_tasks.values()
                )
                if active:
                    return None
                if restart:
                    latest = max(
                        (
                            item
                            for item in self._mock_analysis_tasks.values()
                            if item.contract_id == task.contract_id
                        ),
                        key=lambda item: (item.created_at, str(item.id)),
                        default=None,
                    )
                    if (
                        contract.status != ContractStatus.ANALYZING
                        or latest is None
                        or latest.status != AnalysisStatus.FAILED
                    ):
                        return None
                    event_type = "ANALYSIS_RESTARTED"
                    summary = "실패한 계약 분석을 다시 접수했습니다."
                else:
                    if contract.status != ContractStatus.DRAFT:
                        return None
                    event_type = "ANALYSIS_STARTED"
                    summary = "계약 분석을 접수했습니다."

                self._mock_contracts[task.contract_id] = replace(
                    contract,
                    status=ContractStatus.ANALYZING,
                    updated_at=task.created_at,
                )
                self._mock_analysis_tasks[task.id] = task
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=task.contract_id,
                        event_type=event_type,
                        actor_type="OWNER",
                        summary=summary,
                        created_at=task.created_at,
                    )
                )
                return task

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_task_id": str(task.id),
            "p_contract_id": str(task.contract_id),
            "p_document_id": str(task.document_id),
            "p_supporting_document_ids": [
                str(document_id) for document_id in task.supporting_document_ids
            ],
            "p_restart": restart,
            "p_created_at": task.created_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("start_analysis_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("분석 작업 접수에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _analysis_task_record_from_row(row)

    async def mark_analysis_processing(
        self,
        *,
        task_id: UUID,
    ) -> AnalysisTaskRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                task = self._mock_analysis_tasks.get(task_id)
                if task is None or task.status != AnalysisStatus.QUEUED:
                    return None
                processing = replace(
                    task,
                    status=AnalysisStatus.PROCESSING,
                    attempt_count=1,
                    updated_at=self._clock(),
                )
                self._mock_analysis_tasks[task_id] = processing
                return processing

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "mark_analysis_processing",
                    {"p_task_id": str(task_id)},
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("분석 처리 상태 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _analysis_task_record_from_row(row)

    async def complete_analysis_with_audit(
        self,
        *,
        task_id: UUID,
        attempt_count: int,
        result: Analysis,
    ) -> AnalysisTaskRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                task = self._mock_analysis_tasks.get(task_id)
                if task is None or task.status != AnalysisStatus.PROCESSING:
                    return None
                contract = self._mock_contracts.get(task.contract_id)
                if contract is None or contract.status != ContractStatus.ANALYZING:
                    return None
                now = self._clock()
                completed = replace(
                    task,
                    status=AnalysisStatus.COMPLETED,
                    attempt_count=attempt_count,
                    error_code=None,
                    result=result,
                    updated_at=now,
                )
                self._mock_analysis_tasks[task_id] = completed
                for review_item in result.review_items:
                    self._set_mock_review_item(
                        review_item,
                        updated_at=now,
                        mirror_analysis_result=False,
                    )
                promoted_contract = _promote_verified_canonical_values(
                    contract=contract,
                    result=result,
                )
                self._mock_contracts[task.contract_id] = replace(
                    promoted_contract,
                    status=ContractStatus.REVIEW_REQUIRED,
                    updated_at=now,
                )
                obligation = _representative_obligation(result=result, now=now)
                if obligation is not None and obligation.contract_id not in self._mock_obligations:
                    self._mock_obligations[obligation.contract_id] = obligation
                    self._mock_audit_events.append(
                        MockAuditEvent(
                            id=uuid4(),
                            contract_id=task.contract_id,
                            event_type="OBLIGATION_CREATED",
                            actor_type="SYSTEM",
                            summary="대표 산출물 이행 항목을 생성했습니다.",
                            created_at=now,
                        )
                    )
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=task.contract_id,
                        event_type="ANALYSIS_COMPLETED",
                        actor_type="SYSTEM",
                        summary="계약 분석을 완료했습니다.",
                        created_at=now,
                    )
                )
                return completed

        client = self._require_live_client()
        params = {
            "p_task_id": str(task_id),
            "p_attempt_count": attempt_count,
            "p_result": result.model_dump(mode="json"),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("complete_analysis_result_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("분석 완료 결과 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _analysis_task_record_from_row(row)

    async def fail_analysis_with_audit(
        self,
        *,
        task_id: UUID,
        attempt_count: int,
        error_code: ErrorCode,
    ) -> AnalysisTaskRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                task = self._mock_analysis_tasks.get(task_id)
                if task is None or task.status != AnalysisStatus.PROCESSING:
                    return None
                now = self._clock()
                failed = replace(
                    task,
                    status=AnalysisStatus.FAILED,
                    attempt_count=attempt_count,
                    error_code=error_code,
                    result=None,
                    updated_at=now,
                )
                self._mock_analysis_tasks[task_id] = failed
                for document_id in (task.document_id, *task.supporting_document_ids):
                    document = self._mock_documents.get(document_id)
                    if document is not None:
                        self._mock_documents[document_id] = replace(
                            document,
                            parse_status=DocumentParseStatus.FAILED,
                        )
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=task.contract_id,
                        event_type="ANALYSIS_FAILED",
                        actor_type="SYSTEM",
                        summary="계약 분석에 실패했습니다.",
                        created_at=now,
                    )
                )
                return failed

        client = self._require_live_client()
        params = {
            "p_task_id": str(task_id),
            "p_attempt_count": attempt_count,
            "p_error_code": error_code.value,
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("fail_analysis_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("분석 실패 상태 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _analysis_task_record_from_row(row)

    async def update_review_item_selection_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        item_id: UUID,
        user_choice: SuggestionChoice,
        target_status: ReviewItemStatus,
        updated_at: datetime,
    ) -> ReviewItemSelectionResult:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return ReviewItemSelectionResult(
                        outcome=ReviewItemSelectionOutcome.NOT_FOUND,
                        item=None,
                    )
                item = self._mock_review_item_details.get(item_id)
                if item is None or item.contract_id != contract_id:
                    return ReviewItemSelectionResult(
                        outcome=ReviewItemSelectionOutcome.NOT_FOUND,
                        item=None,
                    )
                if item.status not in {
                    ReviewItemStatus.UNREVIEWED,
                    ReviewItemStatus.SELECTED,
                }:
                    return ReviewItemSelectionResult(
                        outcome=ReviewItemSelectionOutcome.INVALID_STATUS_TRANSITION,
                        item=item,
                    )
                expected_status = (
                    ReviewItemStatus.RESOLVED
                    if user_choice == SuggestionChoice.ACCEPT
                    else ReviewItemStatus.SELECTED
                )
                if target_status != expected_status:
                    raise ValueError("검토 항목 선택과 대상 상태가 일치하지 않습니다.")
                if item.user_choice == user_choice and item.status == target_status:
                    return ReviewItemSelectionResult(
                        outcome=ReviewItemSelectionOutcome.UNCHANGED,
                        item=item,
                    )

                updated = ReviewItem.model_validate(
                    item.model_dump()
                    | {
                        "user_choice": user_choice,
                        "status": target_status,
                    }
                )
                self._set_mock_review_item(updated, updated_at=updated_at)
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type="REVIEW_ITEM_SELECTION_UPDATED",
                        actor_type="OWNER",
                        summary="검토 항목 선택을 변경했습니다.",
                        created_at=updated_at,
                    )
                )
                return ReviewItemSelectionResult(
                    outcome=ReviewItemSelectionOutcome.UPDATED,
                    item=updated,
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_item_id": str(item_id),
            "p_user_choice": user_choice.value,
            "p_target_status": target_status.value,
            "p_updated_at": updated_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "update_review_item_selection_with_audit",
                    params,
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("검토 항목 선택 저장에 실패했습니다.") from error
        payload = response.data[0] if isinstance(response.data, list) else response.data
        if not isinstance(payload, dict):
            raise ExternalStorageFailure("검토 항목 선택 저장 결과를 확인할 수 없습니다.")
        outcome = ReviewItemSelectionOutcome(payload["outcome"])
        item_payload = payload.get("item")
        return ReviewItemSelectionResult(
            outcome=outcome,
            item=_review_item_from_row(item_payload) if isinstance(item_payload, dict) else None,
        )

    async def list_review_items_for_adjustment(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        review_item_ids: Sequence[UUID],
    ) -> Sequence[ReviewItemForAdjustment] | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                return [
                    item
                    for item_id in review_item_ids
                    if (item := self._mock_review_items.get(item_id)) is not None
                    and item.contract_id == contract_id
                ]

        client = self._require_live_client()
        if not await self.is_contract_owned(owner_id=owner_id, contract_id=contract_id):
            return None
        try:
            response = await asyncio.to_thread(
                lambda: (
                    client.table("review_items")
                    .select(
                        "id,contract_id,status,user_choice,"
                        "suggestion_compromise,suggestion_request,category,original_text"
                    )
                    .eq("contract_id", str(contract_id))
                    .in_("id", [str(item_id) for item_id in review_item_ids])
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("검토 항목 조회에 실패했습니다.") from error
        return [_review_item_for_adjustment_from_row(row) for row in response.data or []]

    async def list_document_clauses_for_adjustment(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_clause_ids: Sequence[UUID],
    ) -> Sequence[DocumentClauseForAdjustment] | None:
        if not document_clause_ids:
            return []
        task = await self.get_latest_analysis_task(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if task is None:
            return None
        if task.status != AnalysisStatus.COMPLETED or task.result is None:
            return []
        requested = set(document_clause_ids)
        return [
            DocumentClauseForAdjustment(
                id=clause.id,
                analysis_task_id=task.id,
                document_id=clause.document_id,
                source_page=clause.source_page,
                source_text=clause.source_text,
                source_confidence=clause.confidence,
            )
            for clause in task.result.document_clauses
            if clause.id in requested
        ]

    async def create_adjustment_draft_with_audit(
        self,
        *,
        owner_id: UUID,
        record: AdjustmentRequestRecord,
        manual_review_items: tuple[ManualReviewItemRecord, ...],
    ) -> AdjustmentRequestRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, record.contract_id) not in self._mock_owned_contracts:
                    return None
                for item in manual_review_items:
                    self._mock_review_items[item.id] = ReviewItemForAdjustment(
                        id=item.id,
                        contract_id=item.contract_id,
                        status=ReviewItemStatus.SELECTED,
                        user_choice=SuggestionChoice.REQUEST,
                        suggestion_compromise=item.request_text,
                        suggestion_request=item.request_text,
                        category=AgreementClauseCategory.OTHER,
                        original_text=item.source_text,
                    )
                self._mock_adjustment_requests[record.id] = record
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=record.contract_id,
                        event_type="ADJUSTMENT_DRAFT_CREATED",
                        actor_type="OWNER",
                        summary="조정 요청 초안을 생성했습니다.",
                        created_at=record.created_at,
                    )
                )
                return record

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_adjustment_request_id": str(record.id),
            "p_contract_id": str(record.contract_id),
            "p_expires_in_hours": record.expires_in_hours,
            "p_items": [
                {
                    "review_item_id": str(item.review_item_id),
                    "user_choice": item.user_choice.value,
                    "request_text": item.request_text,
                }
                for item in record.items
            ],
            "p_manual_items": [
                {
                    "review_item_id": str(item.id),
                    "document_clause_id": str(item.document_clause_id),
                }
                for item in manual_review_items
            ],
            "p_created_at": record.created_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("create_adjustment_draft_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("조정 요청 초안 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _adjustment_request_record_from_row(row)

    async def get_owned_adjustment_request(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
    ) -> AdjustmentRequestRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                record = self._mock_adjustment_requests.get(adjustment_request_id)
                return record if record and record.contract_id == contract_id else None

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_adjustment_request_id": str(adjustment_request_id),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("get_owned_adjustment_request", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("조정 요청 조회에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _adjustment_request_record_from_row(row)

    async def get_owned_adjustment_detail(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
    ) -> AdjustmentDetailRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                request = self._mock_adjustment_requests.get(adjustment_request_id)
                if request is None or request.contract_id != contract_id:
                    return None
                return AdjustmentDetailRecord(
                    request=request,
                    responses=self._mock_adjustment_responses.get(request.id, ()),
                )

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_adjustment_request_id": str(adjustment_request_id),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("get_owned_adjustment_detail", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("조정 요청 상세 조회에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _adjustment_detail_record_from_row(row)

    async def get_public_adjustment_request(
        self,
        *,
        adjustment_request_id: UUID,
    ) -> PublicAdjustmentRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                request = self._mock_adjustment_requests.get(adjustment_request_id)
                if request is None:
                    return None
                contract = self._mock_contracts.get(request.contract_id)
                if contract is None:
                    return None
                return PublicAdjustmentRecord(
                    contract_title=contract.title,
                    request=request,
                )

        client = self._require_live_client()
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc(
                    "get_public_adjustment_request",
                    {"p_adjustment_request_id": str(adjustment_request_id)},
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("공개 조정 요청 조회에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _public_adjustment_record_from_row(row)

    async def open_public_adjustment_request(
        self,
        *,
        adjustment_request_id: UUID,
        opened_at: datetime,
    ) -> AdjustmentRequestRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                request = self._mock_adjustment_requests.get(adjustment_request_id)
                if request is None:
                    return None
                if request.status == AdjustmentRequestStatus.SENT:
                    opened = replace(
                        request,
                        status=AdjustmentRequestStatus.OPENED,
                        opened_at=opened_at,
                        updated_at=opened_at,
                    )
                    self._mock_adjustment_requests[request.id] = opened
                    self._mock_audit_events.append(
                        MockAuditEvent(
                            id=uuid4(),
                            contract_id=request.contract_id,
                            event_type="ADJUSTMENT_OPENED",
                            actor_type="AGENCY",
                            summary="대행사가 조정 요청을 열람했습니다.",
                            created_at=opened_at,
                        )
                    )
                    return opened
                if request.status in {
                    AdjustmentRequestStatus.OPENED,
                    AdjustmentRequestStatus.RESPONDED,
                    AdjustmentRequestStatus.CONFIRMED,
                }:
                    return request if request.opened_at is not None else None
                return None

        client = self._require_live_client()
        params = {
            "p_adjustment_request_id": str(adjustment_request_id),
            "p_opened_at": opened_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("open_public_adjustment_request", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("공개 조정 요청 열람 기록에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _adjustment_request_record_from_row(row)

    async def submit_public_adjustment_responses(
        self,
        *,
        adjustment_request_id: UUID,
        responses: tuple[AdjustmentResponseRecord, ...],
        responded_at: datetime,
    ) -> AdjustmentRequestRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                request = self._mock_adjustment_requests.get(adjustment_request_id)
                if request is None or request.status not in {
                    AdjustmentRequestStatus.SENT,
                    AdjustmentRequestStatus.OPENED,
                }:
                    return None
                expected_ids = {item.review_item_id for item in request.items}
                if {response.review_item_id for response in responses} != expected_ids:
                    return None
                opened_at = request.opened_at or responded_at
                submitted = replace(
                    request,
                    status=AdjustmentRequestStatus.RESPONDED,
                    opened_at=opened_at,
                    responded_at=responded_at,
                    updated_at=responded_at,
                )
                self._mock_adjustment_requests[request.id] = submitted
                self._mock_adjustment_responses[request.id] = responses
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=request.contract_id,
                        event_type="ADJUSTMENT_RESPONDED",
                        actor_type="AGENCY",
                        summary="대행사가 조정 요청에 응답했습니다.",
                        created_at=responded_at,
                    )
                )
                return submitted

        client = self._require_live_client()
        params = {
            "p_adjustment_request_id": str(adjustment_request_id),
            "p_responded_at": responded_at.isoformat(),
            "p_responses": [
                {
                    "review_item_id": str(response.review_item_id),
                    "decision": response.decision.value,
                    "counter_text": response.counter_text,
                    "reason": response.reason,
                }
                for response in responses
            ],
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("submit_public_adjustment_responses", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("공개 조정 응답 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _adjustment_request_record_from_row(row)

    async def confirm_adjustment_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
        resolutions: tuple[tuple[UUID, AdjustmentResolution], ...],
        confirmed_at: datetime,
    ) -> AdjustmentRequestRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                request = self._mock_adjustment_requests.get(adjustment_request_id)
                contract = self._mock_contracts.get(contract_id)
                responses = self._mock_adjustment_responses.get(adjustment_request_id, ())
                if (
                    request is None
                    or request.contract_id != contract_id
                    or request.status != AdjustmentRequestStatus.RESPONDED
                    or contract is None
                    or contract.status != ContractStatus.NEGOTIATING
                ):
                    return None
                expected_ids = {item.review_item_id for item in request.items}
                if {item_id for item_id, _resolution in resolutions} != expected_ids:
                    return None
                response_by_id = {response.review_item_id: response for response in responses}
                if set(response_by_id) != expected_ids:
                    return None
                item_by_id = {item.review_item_id: item for item in request.items}
                final_clauses: list[FinalClauseRecord] = []
                for item_id, resolution in resolutions:
                    response = response_by_id[item_id]
                    item = item_by_id[item_id]
                    if resolution == AdjustmentResolution.ACCEPT_REQUEST:
                        if response.decision != AdjustmentResponseDecision.ACCEPT:
                            return None
                        final_clauses.append(
                            FinalClauseRecord(
                                review_item_id=item_id,
                                category=item.category,
                                resolution=resolution,
                                outcome=AgreementClauseOutcome.AGREED.value,
                                disposition=AgreementClauseDisposition.AGREED.value,
                                before_text=item.before_text,
                                after_text=item.request_text,
                                reason=None,
                            )
                        )
                    elif resolution == AdjustmentResolution.ACCEPT_COUNTERPROPOSAL:
                        if (
                            response.decision != AdjustmentResponseDecision.COUNTER
                            or response.counter_text is None
                        ):
                            return None
                        final_clauses.append(
                            FinalClauseRecord(
                                review_item_id=item_id,
                                category=item.category,
                                resolution=resolution,
                                outcome=AgreementClauseOutcome.AGREED.value,
                                disposition=AgreementClauseDisposition.AGREED.value,
                                before_text=item.before_text,
                                after_text=response.counter_text,
                                reason=None,
                            )
                        )
                    else:
                        final_clauses.append(
                            FinalClauseRecord(
                                review_item_id=item_id,
                                category=item.category,
                                resolution=resolution,
                                outcome=AgreementClauseOutcome.KEPT_ORIGINAL.value,
                                disposition=(
                                    AgreementClauseDisposition.REJECTED.value
                                    if response.decision == AdjustmentResponseDecision.REJECT
                                    else AgreementClauseDisposition.WITHDRAWN.value
                                ),
                                before_text=item.before_text,
                                after_text=item.before_text,
                                reason=(
                                    response.reason
                                    if response.decision == AdjustmentResponseDecision.REJECT
                                    else "소상공인이 원계약 유지를 선택했습니다."
                                ),
                            )
                        )
                review_items = [self._mock_review_items.get(item_id) for item_id in expected_ids]
                if any(
                    item is None or item.status != ReviewItemStatus.SENT for item in review_items
                ):
                    return None
                self._mock_adjustment_requests[request.id] = replace(
                    request,
                    status=AdjustmentRequestStatus.CONFIRMED,
                    updated_at=confirmed_at,
                )
                for clause in final_clauses:
                    review_item = self._mock_review_items[clause.review_item_id]
                    self._mock_review_items[clause.review_item_id] = replace(
                        review_item,
                        status=(
                            ReviewItemStatus.RESOLVED
                            if clause.outcome == AgreementClauseOutcome.AGREED.value
                            else ReviewItemStatus.KEPT_ORIGINAL
                        ),
                    )
                self._mock_final_clauses[request.id] = tuple(final_clauses)
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type="ADJUSTMENT_CONFIRMED",
                        actor_type="OWNER",
                        summary="조정 결과를 확정했습니다.",
                        created_at=confirmed_at,
                    )
                )
                return self._mock_adjustment_requests[request.id]

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_adjustment_request_id": str(adjustment_request_id),
            "p_confirmed_at": confirmed_at.isoformat(),
            "p_confirmed_items": [
                {"review_item_id": str(item_id), "resolution": resolution.value}
                for item_id, resolution in resolutions
            ],
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("confirm_adjustment_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("조정 결과 확정 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _adjustment_request_record_from_row(row)

    async def get_revised_contract_context(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
    ) -> RevisedContractContext | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                request = self._mock_adjustment_requests.get(adjustment_request_id)
                clauses = self._mock_final_clauses.get(adjustment_request_id, ())
                if (
                    contract is None
                    or contract.owner_id != owner_id
                    or contract.status != ContractStatus.NEGOTIATING
                    or request is None
                    or request.contract_id != contract_id
                    or request.status != AdjustmentRequestStatus.CONFIRMED
                    or not clauses
                ):
                    return None
                return RevisedContractContext(
                    contract_title=contract.title,
                    final_clauses=clauses,
                )
        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_adjustment_request_id": str(adjustment_request_id),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("get_revised_contract_context", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("수정 계약서 대조 문맥 조회에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return RevisedContractContext(
            contract_title=str(row["contract_title"]),
            final_clauses=tuple(
                FinalClauseRecord(
                    review_item_id=UUID(str(item["review_item_id"])),
                    category=AgreementClauseCategory(item["category"]),
                    resolution=AdjustmentResolution(item["resolution"]),
                    outcome=str(item["outcome"]),
                    disposition=str(item["disposition"]),
                    before_text=str(item["before_text"]),
                    after_text=str(item["after_text"]),
                    reason=item.get("reason"),
                )
                for item in row.get("final_clauses", [])
            ),
        )

    async def create_revised_contract_review_with_audit(
        self,
        *,
        owner_id: UUID,
        review: RevisedContractReview,
    ) -> RevisedContractReview | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(review.contract_id)
                if (
                    contract is None
                    or contract.owner_id != owner_id
                    or contract.status != ContractStatus.NEGOTIATING
                ):
                    return None
                self._mock_revised_contract_reviews[review.id] = review
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=review.contract_id,
                        event_type="REVISED_CONTRACT_REVIEW_CREATED",
                        actor_type="OWNER",
                        summary="수정 계약서 대조를 생성했습니다.",
                        created_at=review.created_at,
                    )
                )
                return review
        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_review": review.model_dump(mode="json"),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("create_revised_contract_review_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("수정 계약서 대조 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return RevisedContractReview.model_validate(row)

    async def get_latest_owned_revised_contract_review(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> RevisedContractReview | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                if contract is None or contract.owner_id != owner_id:
                    return None
                reviews = [
                    review
                    for review in self._mock_revised_contract_reviews.values()
                    if review.contract_id == contract_id
                ]
                return (
                    max(reviews, key=lambda item: (item.created_at, item.id)) if reviews else None
                )
        client = self._require_live_client()
        params = {"p_owner_id": str(owner_id), "p_contract_id": str(contract_id)}
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("get_latest_owned_revised_contract_review", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("수정 계약서 대조 조회에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return RevisedContractReview.model_validate(row)

    async def confirm_revised_contract_review_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        review_id: UUID,
        confirmed_review_item_ids: tuple[UUID, ...],
        confirmed_at: datetime,
    ) -> RevisedContractReview | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                review = self._mock_revised_contract_reviews.get(review_id)
                latest = max(
                    (
                        item
                        for item in self._mock_revised_contract_reviews.values()
                        if item.contract_id == contract_id
                    ),
                    key=lambda item: (item.created_at, item.id),
                    default=None,
                )
                expected_ids = {item.review_item_id for item in review.items} if review else set()
                if (
                    contract is None
                    or contract.owner_id != owner_id
                    or contract.status != ContractStatus.NEGOTIATING
                    or review is None
                    or review.status != RevisedContractReviewStatus.REVIEW_REQUIRED
                    or latest is None
                    or latest.id != review_id
                    or set(confirmed_review_item_ids) != expected_ids
                    or len(confirmed_review_item_ids) != len(expected_ids)
                ):
                    return None
                confirmed = review.model_copy(
                    update={
                        "status": RevisedContractReviewStatus.CONFIRMED,
                        "items": [
                            item.model_copy(update={"owner_confirmed": True})
                            for item in review.items
                        ],
                        "confirmed_at": confirmed_at,
                    }
                )
                self._mock_revised_contract_reviews[review_id] = confirmed
                self._mock_contracts[contract_id] = replace(
                    contract,
                    status=ContractStatus.READY_TO_SIGN,
                    updated_at=confirmed_at,
                )
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type="REVISED_CONTRACT_CONFIRMED",
                        actor_type="OWNER",
                        summary="수정 계약서 대조 결과를 확인했습니다.",
                        created_at=confirmed_at,
                    )
                )
                return confirmed
        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_review_id": str(review_id),
            "p_confirmed_review_item_ids": [str(item) for item in confirmed_review_item_ids],
            "p_confirmed_at": confirmed_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("confirm_revised_contract_review_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("수정 계약서 확인 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return RevisedContractReview.model_validate(row)

    async def get_agreement_creation_context(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> AgreementCreationContext | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                contract = self._mock_contracts.get(contract_id)
                if contract is None:
                    return None
                requests = [
                    request
                    for request in self._mock_adjustment_requests.values()
                    if request.contract_id == contract_id
                    and request.status == AdjustmentRequestStatus.CONFIRMED
                ]
                if len(requests) != 1:
                    return None
                request = requests[0]
                documents = sorted(
                    (
                        document
                        for document in self._mock_documents.values()
                        if document.contract_id == contract_id
                        and document.type == DocumentType.CONTRACT
                    ),
                    key=lambda document: (document.created_at, str(document.id)),
                    reverse=True,
                )
                return AgreementCreationContext(
                    contract=contract,
                    original_document_id=documents[0].id if documents else None,
                    adjustment_request_id=request.id,
                    final_clauses=self._mock_final_clauses.get(request.id, ()),
                )

        client = self._require_live_client()
        params = {"p_owner_id": str(owner_id), "p_contract_id": str(contract_id)}
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("get_agreement_creation_context", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("합의서 생성 정보를 조회하지 못했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _agreement_creation_context_from_row(row, owner_id=owner_id)

    async def create_agreement_with_audit(
        self,
        *,
        owner_id: UUID,
        record: AgreementRecord,
    ) -> AgreementRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(record.agreement.contract_id)
                if (
                    contract is None
                    or contract.owner_id != owner_id
                    or contract.status != ContractStatus.READY_TO_SIGN
                    or record.agreement.contract_id in self._mock_agreements
                ):
                    return None
                self._mock_agreements[record.agreement.contract_id] = record
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=record.agreement.contract_id,
                        event_type="AGREEMENT_CREATED",
                        actor_type="OWNER",
                        summary="변경·확인 합의서를 생성했습니다.",
                        created_at=record.created_at,
                    )
                )
                return record

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(record.agreement.contract_id),
            "p_agreement_id": str(record.agreement.id),
            "p_adjustment_request_id": str(record.adjustment_request_id),
            "p_agreement": record.agreement.model_dump(mode="json"),
            "p_pdf_storage_path": record.pdf_storage_path,
            "p_pdf_sha256": record.pdf_sha256,
            "p_pdf_size_bytes": record.pdf_size_bytes,
            "p_pdf_page_count": record.pdf_page_count,
            "p_created_at": record.created_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("create_rendered_agreement_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("합의서 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _agreement_record_from_row(row)

    async def get_owned_agreement(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> AgreementRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                return self._mock_agreements.get(contract_id)

        client = self._require_live_client()
        params = {"p_owner_id": str(owner_id), "p_contract_id": str(contract_id)}
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("get_owned_agreement", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("합의서 조회에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _agreement_record_from_row(row)

    async def prepare_embedded_signature_draft(
        self,
        *,
        owner_id: UUID,
        signature_id: UUID,
        contract_id: UUID,
        revised_contract_review_id: UUID | None,
        document_id: UUID | None,
        document_sha256: str | None,
        agreement_id: UUID | None,
        agreement_version: int | None,
        idempotency_key: UUID,
        requested_at: datetime,
    ) -> SignatureRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                agreement = self._mock_agreements.get(contract_id)
                revision = (
                    self._mock_revised_contract_reviews.get(revised_contract_review_id)
                    if revised_contract_review_id is not None
                    else None
                )
                previous_failed = next(
                    (
                        record
                        for record in self._mock_signatures.values()
                        if record.signature.contract_id == contract_id
                        and record.signature.status == InternalSignatureStatus.FAILED
                        and record.idempotency_key == idempotency_key
                    ),
                    None,
                )
                if previous_failed is not None:
                    return previous_failed
                active_statuses = {
                    InternalSignatureStatus.REQUEST_READY,
                    InternalSignatureStatus.REQUESTING,
                    InternalSignatureStatus.EDITING,
                    InternalSignatureStatus.SIGNING,
                }
                valid_revision = (
                    revision is not None
                    and revision.contract_id == contract_id
                    and revision.status == RevisedContractReviewStatus.CONFIRMED
                    and revision.document_id == document_id
                    and revision.document_sha256 == document_sha256
                )
                valid_legacy_agreement = (
                    revised_contract_review_id is None
                    and agreement is not None
                    and agreement.agreement.id == agreement_id
                    and agreement.agreement.version == agreement_version
                )
                if (
                    contract is None
                    or contract.owner_id != owner_id
                    or contract.status != ContractStatus.READY_TO_SIGN
                    or not (valid_revision or valid_legacy_agreement)
                    or any(
                        record.signature.contract_id == contract_id
                        and record.signature.status in active_statuses
                        for record in self._mock_signatures.values()
                    )
                ):
                    return None
                record = SignatureRecord(
                    signature=Signature(
                        id=signature_id,
                        contract_id=contract_id,
                        status=InternalSignatureStatus.REQUESTING,
                        requested_at=requested_at,
                    ),
                    revised_contract_review_id=revised_contract_review_id,
                    document_id=document_id,
                    document_sha256=document_sha256,
                    agreement_id=agreement_id,
                    agreement_version=agreement_version,
                    idempotency_key=idempotency_key,
                )
                self._mock_signatures[signature_id] = record
                return record

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_signature_id": str(signature_id),
            "p_contract_id": str(contract_id),
            "p_revised_contract_review_id": (
                str(revised_contract_review_id) if revised_contract_review_id else None
            ),
            "p_document_id": str(document_id) if document_id else None,
            "p_document_sha256": document_sha256,
            "p_agreement_id": str(agreement_id) if agreement_id else None,
            "p_agreement_version": agreement_version,
            "p_idempotency_key": str(idempotency_key),
            "p_requested_at": requested_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("prepare_embedded_signature_draft", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("Unable to prepare the signature request.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _signature_record_from_row(row)

    async def complete_embedded_signature_draft(
        self,
        *,
        owner_id: UUID,
        signature_id: UUID,
        modusign_draft_id: str,
    ) -> SignatureRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                record = self._mock_signatures.get(signature_id)
                if record is None or record.signature.status != InternalSignatureStatus.REQUESTING:
                    return None
                contract = self._mock_contracts.get(record.signature.contract_id)
                if contract is None or contract.owner_id != owner_id:
                    return None
                self._mock_signatures[signature_id] = replace(
                    record,
                    signature=record.signature.model_copy(
                        update={
                            "status": InternalSignatureStatus.EDITING,
                            "modusign_draft_id": modusign_draft_id,
                            "modusign_status": ModusignStatus.DRAFT,
                        }
                    ),
                )
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract.id,
                        event_type="SIGNATURE_DRAFT_CREATED",
                        actor_type="OWNER",
                        summary="Embedded signature draft was created.",
                        created_at=self._clock(),
                    )
                )
                return self._mock_signatures[signature_id]

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_signature_id": str(signature_id),
            "p_modusign_draft_id": modusign_draft_id,
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("complete_embedded_signature_draft", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("Unable to save the signature request.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _signature_record_from_row(row)

    async def fail_embedded_signature_draft(
        self,
        *,
        owner_id: UUID,
        signature_id: UUID,
        completed_at: datetime,
    ) -> SignatureRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                record = self._mock_signatures.get(signature_id)
                if record is None or record.signature.status != InternalSignatureStatus.REQUESTING:
                    return None
                contract = self._mock_contracts.get(record.signature.contract_id)
                if contract is None or contract.owner_id != owner_id:
                    return None
                failed = replace(
                    record,
                    signature=record.signature.model_copy(
                        update={
                            "status": InternalSignatureStatus.FAILED,
                            "completed_at": completed_at,
                        }
                    ),
                )
                self._mock_signatures[signature_id] = failed
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract.id,
                        event_type="SIGNATURE_FAILED",
                        actor_type="SYSTEM",
                        summary="Signature request creation failed.",
                        created_at=completed_at,
                    )
                )
                return failed

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_signature_id": str(signature_id),
            "p_completed_at": completed_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("fail_embedded_signature_draft", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure(
                "Unable to record the signature request failure."
            ) from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _signature_record_from_row(row)

    async def get_latest_owned_signature(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> SignatureRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                records = [
                    record
                    for record in self._mock_signatures.values()
                    if record.signature.contract_id == contract_id
                ]
                if not records:
                    return None
                return max(records, key=lambda record: record.signature.requested_at)

        client = self._require_live_client()
        params = {"p_owner_id": str(owner_id), "p_contract_id": str(contract_id)}
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("get_latest_owned_signature", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("Unable to retrieve the signature status.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _signature_record_from_row(row)

    async def record_modusign_webhook_event(
        self,
        *,
        receipt: ModusignWebhookReceipt,
    ) -> bool:
        if self.mode == "mock":
            async with self._mock_lock:
                if receipt.deduplication_key in self._mock_modusign_webhook_events:
                    return False
                self._mock_modusign_webhook_events[receipt.deduplication_key] = (
                    MockModusignWebhookEvent(
                        deduplication_key=receipt.deduplication_key,
                        event_id=receipt.event_id,
                        event_type=receipt.event_type,
                        document_id=receipt.document_id,
                        received_at=receipt.received_at,
                    )
                )
                return True

        client = self._require_live_client()
        params = {
            "p_deduplication_key": receipt.deduplication_key,
            "p_event_id": receipt.event_id,
            "p_event_type": receipt.event_type,
            "p_document_id": receipt.document_id,
            "p_received_at": receipt.received_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("record_modusign_webhook_event", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("Unable to persist the webhook event.") from error
        return bool(response.data)

    async def mark_modusign_webhook_processed(
        self,
        *,
        deduplication_key: str,
        processed_at: datetime,
    ) -> None:
        if self.mode == "mock":
            async with self._mock_lock:
                event = self._mock_modusign_webhook_events.get(deduplication_key)
                if event is not None and event.processed_at is None:
                    self._mock_modusign_webhook_events[deduplication_key] = replace(
                        event,
                        processed_at=processed_at,
                    )
            return

        client = self._require_live_client()
        params = {
            "p_deduplication_key": deduplication_key,
            "p_processed_at": processed_at.isoformat(),
        }
        try:
            await asyncio.to_thread(
                lambda: client.rpc("mark_modusign_webhook_processed", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("Unable to record webhook processing.") from error

    async def apply_modusign_document_status(
        self,
        *,
        signature_id: UUID,
        document_id: str,
        event_key: str,
        status: ModusignStatus,
        processed_at: datetime,
    ) -> bool:
        if self.mode == "mock":
            async with self._mock_lock:
                record = self._mock_signatures.get(signature_id)
                if record is None:
                    return False
                signature = record.signature
                contract = self._mock_contracts.get(signature.contract_id)
                if contract is None or signature.status in {
                    InternalSignatureStatus.COMPLETED,
                    InternalSignatureStatus.ABORTED,
                    InternalSignatureStatus.FAILED,
                }:
                    return False
                if signature.modusign_document_id not in (None, document_id):
                    return False

                signature_update = {
                    "modusign_document_id": document_id,
                    "modusign_status": status,
                    "last_event_id": event_key,
                }
                audit_event: str | None = None
                target_contract_status = contract.status
                if status == ModusignStatus.ON_GOING:
                    if (
                        signature.status == InternalSignatureStatus.EDITING
                        and contract.status == ContractStatus.READY_TO_SIGN
                    ):
                        signature_update["status"] = InternalSignatureStatus.SIGNING
                        target_contract_status = ContractStatus.SIGNING
                        audit_event = "SIGNATURE_STARTED"
                    elif signature.status != InternalSignatureStatus.SIGNING:
                        return False
                elif status == ModusignStatus.COMPLETED:
                    if signature.status not in {
                        InternalSignatureStatus.EDITING,
                        InternalSignatureStatus.SIGNING,
                    } or contract.status not in {
                        ContractStatus.READY_TO_SIGN,
                        ContractStatus.SIGNING,
                    }:
                        return False
                    signature_update["status"] = InternalSignatureStatus.COMPLETED
                    signature_update["completed_at"] = processed_at
                    target_contract_status = ContractStatus.SIGNED
                    audit_event = "SIGNATURE_COMPLETED"
                elif status in {ModusignStatus.ABORTED, ModusignStatus.PROCESSING_FAILED}:
                    if signature.status not in {
                        InternalSignatureStatus.EDITING,
                        InternalSignatureStatus.SIGNING,
                    }:
                        return False
                    signature_update["status"] = (
                        InternalSignatureStatus.ABORTED
                        if status == ModusignStatus.ABORTED
                        else InternalSignatureStatus.FAILED
                    )
                    signature_update["completed_at"] = processed_at
                    if contract.status == ContractStatus.SIGNING:
                        target_contract_status = ContractStatus.READY_TO_SIGN
                    audit_event = (
                        "SIGNATURE_ABORTED"
                        if status == ModusignStatus.ABORTED
                        else "SIGNATURE_FAILED"
                    )
                elif (
                    status
                    not in {
                        ModusignStatus.DRAFT,
                        ModusignStatus.SCHEDULED,
                        ModusignStatus.ON_PROCESSING,
                    }
                    or signature.status != InternalSignatureStatus.EDITING
                ):
                    return False

                self._mock_signatures[signature_id] = replace(
                    record,
                    signature=signature.model_copy(update=signature_update),
                )
                if target_contract_status != contract.status:
                    self._mock_contracts[contract.id] = replace(
                        contract,
                        status=target_contract_status,
                    )
                if audit_event is not None:
                    self._mock_audit_events.append(
                        MockAuditEvent(
                            id=uuid4(),
                            contract_id=contract.id,
                            event_type=audit_event,
                            actor_type="SYSTEM",
                            summary="Modusign document status was reconciled.",
                            created_at=processed_at,
                        )
                    )
                return True

        client = self._require_live_client()
        params = {
            "p_signature_id": str(signature_id),
            "p_modusign_document_id": document_id,
            "p_last_event_id": event_key,
            "p_modusign_status": status.value,
            "p_processed_at": processed_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("apply_modusign_document_status", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("Unable to reconcile the signature status.") from error
        return bool(response.data)

    async def send_adjustment_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
        sent_at: datetime,
        public_token: PublicTokenRecord,
    ) -> AdjustmentRequestRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return None
                record = self._mock_adjustment_requests.get(adjustment_request_id)
                contract = self._mock_contracts.get(contract_id)
                if (
                    record is None
                    or record.contract_id != contract_id
                    or record.status != AdjustmentRequestStatus.DRAFT
                    or contract is None
                    or contract.status != ContractStatus.REVIEW_REQUIRED
                    or any(
                        item.contract_id == contract_id and item.sent_at is not None
                        for item in self._mock_adjustment_requests.values()
                    )
                ):
                    return None
                review_item_ids = {item.review_item_id for item in record.items}
                review_items = [self._mock_review_items.get(item_id) for item_id in review_item_ids]
                if any(
                    item is None
                    or item.status != ReviewItemStatus.SELECTED
                    or item.user_choice
                    not in {SuggestionChoice.COMPROMISE, SuggestionChoice.REQUEST}
                    for item in review_items
                ):
                    return None
                expires_at = sent_at + timedelta(hours=record.expires_in_hours)
                sent = replace(
                    record,
                    status=AdjustmentRequestStatus.SENT,
                    sent_at=sent_at,
                    expires_at=expires_at,
                    updated_at=sent_at,
                )
                self._mock_adjustment_requests[record.id] = sent
                for review_item in review_items:
                    assert review_item is not None
                    frozen = replace(
                        review_item,
                        status=ReviewItemStatus.SENT,
                    )
                    self._mock_review_items[review_item.id] = frozen
                    detail = self._mock_review_item_details.get(review_item.id)
                    if detail is not None:
                        sent_detail = ReviewItem.model_validate(
                            detail.model_dump()
                            | {
                                "status": ReviewItemStatus.SENT,
                            }
                        )
                        self._set_mock_review_item(sent_detail, updated_at=sent_at)
                self._mock_contracts[contract_id] = replace(
                    contract,
                    status=ContractStatus.NEGOTIATING,
                    updated_at=sent_at,
                )
                self._mock_public_tokens[public_token.token_hash] = public_token
                self._mock_audit_events.append(
                    MockAuditEvent(
                        id=uuid4(),
                        contract_id=contract_id,
                        event_type="ADJUSTMENT_SENT",
                        actor_type="OWNER",
                        summary="조정 요청을 발송했습니다.",
                        created_at=sent_at,
                    )
                )
                return sent

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_adjustment_request_id": str(adjustment_request_id),
            "p_sent_at": sent_at.isoformat(),
            "p_public_token_id": str(public_token.id),
            "p_token_hash": public_token.token_hash,
            "p_token_scope": public_token.scope.value,
            "p_token_resource_id": str(public_token.resource_id),
            "p_token_expires_at": public_token.expires_at.isoformat(),
            "p_token_created_at": public_token.created_at.isoformat(),
        }
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("send_adjustment_with_audit", params).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("조정 요청 발송 저장에 실패했습니다.") from error
        if not response.data:
            return None
        row = response.data[0] if isinstance(response.data, list) else response.data
        return _adjustment_request_record_from_row(row)

    def _set_mock_review_item(
        self,
        item: ReviewItem,
        *,
        updated_at: datetime,
        mirror_analysis_result: bool = True,
    ) -> None:
        self._mock_review_item_details[item.id] = item
        self._mock_review_items[item.id] = _review_item_for_adjustment(item)
        if not mirror_analysis_result:
            return
        for task_id, task in tuple(self._mock_analysis_tasks.items()):
            if task.result is None:
                continue
            if not any(review_item.id == item.id for review_item in task.result.review_items):
                continue
            mirrored_result = Analysis(
                contract_id=task.result.contract_id,
                document_clauses=task.result.document_clauses,
                extracted_terms=task.result.extracted_terms,
                review_items=[
                    item if review_item.id == item.id else review_item
                    for review_item in task.result.review_items
                ],
            )
            self._mock_analysis_tasks[task_id] = replace(
                task,
                result=mirrored_result,
                updated_at=updated_at,
            )
            return

    def _require_live_client(self) -> Client:
        if self._client is None:
            raise RuntimeError("Supabase live client가 초기화되지 않았습니다.")
        return self._client


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _contract_expires_soon(
    *,
    contract: ContractRecord,
    today: date,
) -> bool:
    expiry_d_day = (contract.end_date - today).days if contract.end_date else None
    termination_notice_d_day = (
        (contract.termination_notice_date - today).days
        if contract.termination_notice_date
        else None
    )
    auto_renewal_d_day = (
        expiry_d_day if contract.renewal_type == "AUTO" and contract.end_date is not None else None
    )
    return any(
        value is not None and 0 <= value <= upper_bound
        for value, upper_bound in (
            (expiry_d_day, 30),
            (termination_notice_d_day, 14),
            (auto_renewal_d_day, 7),
        )
    )


def _dashboard_record_from_row(row: dict) -> DashboardRecord:
    signal = row.get("most_common_signal")
    return DashboardRecord(
        total=int(row["total"]),
        signing=int(row["signing"]),
        in_progress=int(row["in_progress"]),
        completed=int(row["completed"]),
        expiring_soon=int(row["expiring_soon"]),
        unresolved_signals=int(row["unresolved_signals"]),
        adjustment_requested_clauses=int(row["adjustment_requested_clauses"]),
        adjustment_agreed_clauses=int(row["adjustment_agreed_clauses"]),
        adjustment_rejected_clauses=int(row["adjustment_rejected_clauses"]),
        obligation_pending=int(row["obligation_pending"]),
        obligation_submitted=int(row["obligation_submitted"]),
        obligation_approved=int(row["obligation_approved"]),
        total_committed=int(row["total_committed"]),
        payment_condition_met_amount=int(row["payment_condition_met_amount"]),
        most_common_signal=ReviewSignalType(signal) if signal is not None else None,
    )


def _parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _obligation_record_from_mock(obligation: MockObligation) -> ObligationRecord:
    return ObligationRecord(
        id=obligation.id,
        contract_id=obligation.contract_id,
        title=obligation.title,
        due_date=obligation.due_date,
        assignee=obligation.assignee,
        evidence_type=obligation.evidence_type,
        source_document_id=obligation.source_document_id,
        source_page=obligation.source_page,
        source_text=obligation.source_text,
        confidence=obligation.confidence,
        evidence_url=obligation.evidence_url,
        status=obligation.status,
        submitted_at=obligation.submitted_at,
        reviewed_at=obligation.reviewed_at,
        payment_condition_met=obligation.payment_condition_met,
    )


def _obligation_record_from_row(row: dict) -> ObligationRecord:
    due_date = _parse_date(row["due_date"])
    if due_date is None:
        raise ValueError("이행 항목 기한이 없습니다.")
    return ObligationRecord(
        id=UUID(str(row["id"])),
        contract_id=UUID(str(row["contract_id"])),
        title=row["title"],
        due_date=due_date,
        assignee=row["assignee"],
        evidence_type=row["evidence_type"],
        source_document_id=UUID(str(row["source_document_id"])),
        source_page=int(row["source_page"]),
        source_text=row["source_text"],
        confidence=float(row["confidence"]),
        evidence_url=row.get("evidence_url"),
        status=ObligationStatus(row["status"]),
        submitted_at=(
            _parse_datetime(row["submitted_at"]) if row.get("submitted_at") is not None else None
        ),
        reviewed_at=(
            _parse_datetime(row["reviewed_at"]) if row.get("reviewed_at") is not None else None
        ),
        payment_condition_met=bool(row["payment_condition_met"]),
    )


def _promote_verified_canonical_values(
    *,
    contract: ContractRecord,
    result: Analysis,
) -> ContractRecord:
    field_mapping = {
        ExtractedField.CONTRACT_SIGNED_DATE: "signed_date",
        ExtractedField.CONTRACT_START_DATE: "start_date",
        ExtractedField.CONTRACT_END_DATE: "end_date",
        ExtractedField.TERMINATION_NOTICE_DATE: "termination_notice_date",
        ExtractedField.CONTRACT_RENEWAL_TYPE: "renewal_type",
        ExtractedField.CONTRACT_TOTAL_AMOUNT: "total_amount",
    }
    updates: dict[str, date | str | int] = {}
    for field, attribute in field_mapping.items():
        if getattr(contract, attribute) is not None:
            continue
        candidates = [
            term
            for term in result.extracted_terms
            if term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT
            and term.field == field
            and term.verification_status == VerificationStatus.VERIFIED
        ]
        if len(candidates) != 1:
            continue
        value = candidates[0].value
        if field in {
            ExtractedField.CONTRACT_SIGNED_DATE,
            ExtractedField.CONTRACT_START_DATE,
            ExtractedField.CONTRACT_END_DATE,
            ExtractedField.TERMINATION_NOTICE_DATE,
        }:
            value = date.fromisoformat(str(value))
        elif field == ExtractedField.CONTRACT_RENEWAL_TYPE:
            if value not in {"AUTO", "MANUAL", "NONE"}:
                continue
        elif not isinstance(value, int) or isinstance(value, bool):
            continue
        updates[attribute] = value
    return replace(contract, **updates) if updates else contract


def _representative_obligation(
    *,
    result: Analysis,
    now: datetime,
) -> MockObligation | None:
    draft = build_representative_obligation(
        contract_id=result.contract_id,
        terms=result.extracted_terms,
    )
    if draft is None:
        return None
    return MockObligation(
        id=uuid4(),
        contract_id=draft.contract_id,
        title=draft.title,
        due_date=draft.due_date,
        assignee="AGENCY",
        evidence_type="URL",
        source_document_id=draft.source_document_id,
        source_page=draft.source_page,
        source_text=draft.source_text,
        confidence=draft.confidence,
        status=ObligationStatus.PENDING,
        created_at=now,
        updated_at=now,
    )


def _contract_record_from_row(row: dict, *, owner_id: UUID) -> ContractRecord:
    understood_term = row.get("understood_term")
    renewal_decision = row.get("renewal_decision")
    return ContractRecord(
        id=UUID(str(row["id"])),
        owner_id=UUID(str(row.get("owner_id", owner_id))),
        title=row["title"],
        counterparty_name=row["counterparty_name"],
        status=ContractStatus(row["status"]),
        signed_date=_parse_date(row.get("signed_date")),
        start_date=_parse_date(row.get("start_date")),
        end_date=_parse_date(row.get("end_date")),
        termination_notice_date=_parse_date(row.get("termination_notice_date")),
        renewal_type=row.get("renewal_type"),
        total_amount=int(row["total_amount"]) if row.get("total_amount") is not None else None,
        understood_term=(
            UnderstoodTerm.model_validate(understood_term) if understood_term is not None else None
        ),
        renewal_decision=(
            RenewalDecision.model_validate(renewal_decision)
            if renewal_decision is not None
            else None
        ),
        modusign_document_id=row.get("modusign_document_id"),
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _is_contract_in_renewal_review_window(
    contract: ContractRecord,
    *,
    today: date,
) -> bool:
    expiry_d_day = (contract.end_date - today).days if contract.end_date else None
    termination_notice_d_day = (
        (contract.termination_notice_date - today).days
        if contract.termination_notice_date
        else None
    )
    auto_renewal_d_day = (
        expiry_d_day if contract.renewal_type == "AUTO" and contract.end_date else None
    )
    return any(
        d_day is not None and 0 <= d_day <= upper_bound
        for d_day, upper_bound in (
            (expiry_d_day, 30),
            (termination_notice_d_day, 14),
            (auto_renewal_d_day, 7),
        )
    )


def _audit_event_record_from_row(row: dict) -> AuditEventRecord:
    return AuditEventRecord(
        id=UUID(str(row["id"])),
        contract_id=UUID(str(row["contract_id"])),
        event_type=row["event_type"],
        actor_type=row["actor_type"],
        summary=row.get("summary"),
        created_at=_parse_datetime(row["created_at"]),
    )


def _public_token_record_from_row(row: dict) -> PublicTokenRecord:
    return PublicTokenRecord(
        id=UUID(str(row["id"])),
        token_hash=row["token_hash"],
        scope=PublicTokenScope(row["scope"]),
        resource_id=UUID(str(row["resource_id"])),
        expires_at=_parse_datetime(row["expires_at"]),
        revoked_at=_parse_datetime(row["revoked_at"]) if row.get("revoked_at") else None,
        created_at=_parse_datetime(row["created_at"]),
    )


def _idempotency_params(
    *,
    owner_id: UUID,
    operation: IdempotencyOperation,
    resource_id: UUID,
    key: UUID,
    request_hash: str,
    created_at: datetime | None = None,
) -> dict[str, object]:
    params: dict[str, object] = {
        "p_owner_id": str(owner_id),
        "p_operation": operation.value,
        "p_resource_id": str(resource_id),
        "p_idempotency_key": str(key),
        "p_request_hash": request_hash,
    }
    if created_at is not None:
        params["p_created_at"] = created_at.isoformat()
    return params


def _idempotency_record_from_row(row: dict) -> IdempotencyRecord:
    return IdempotencyRecord(
        owner_id=UUID(str(row["owner_id"])),
        operation=IdempotencyOperation(row["operation"]),
        resource_id=UUID(str(row["resource_id"])),
        key=UUID(str(row["idempotency_key"])),
        request_hash=row["request_hash"],
        response_status=row.get("response_status"),
        response_payload=row.get("response_payload"),
        created_at=_parse_datetime(row["created_at"]),
    )


def _performance_report_access_from_row(row: dict) -> PerformanceReportAccess:
    extracted_payload = row.get("extracted_payload")
    return PerformanceReportAccess(
        id=UUID(str(row["id"])),
        contract_id=UUID(str(row["contract_id"])),
        period=str(row["period"]),
        source_document_id=UUID(str(row["source_document_id"])),
        status=PerformanceReportStatus(row["status"]),
        extracted_payload=(
            PerformanceExtractedPayload.model_validate(extracted_payload)
            if extracted_payload is not None
            else None
        ),
        current_revision_id=(
            UUID(str(row["current_revision_id"]))
            if row.get("current_revision_id") is not None
            else None
        ),
        revision_count=int(row.get("revision_count", 0)),
        extraction_attempt_id=(
            UUID(str(row["extraction_attempt_id"]))
            if row.get("extraction_attempt_id") is not None
            else None
        ),
        extraction_started_at=(
            _parse_datetime(row["extraction_started_at"])
            if row.get("extraction_started_at") is not None
            else None
        ),
        created_at=(
            _parse_datetime(row["created_at"]) if row.get("created_at") is not None else None
        ),
        updated_at=(
            _parse_datetime(row["updated_at"]) if row.get("updated_at") is not None else None
        ),
    )


def _performance_report_from_access(
    access: PerformanceReportAccess,
    revisions: list[PerformanceReportRevision],
) -> PerformanceReport:
    ordered = sorted(revisions, key=lambda revision: revision.version)
    current_revision = ordered[-1] if ordered else None
    if access.revision_count != len(ordered):
        raise ValueError("성과 리포트 revision_count가 저장된 revision 수와 다릅니다.")
    if (access.current_revision_id is None) != (current_revision is None):
        raise ValueError("성과 리포트 현재 revision projection이 저장 이력과 다릅니다.")
    if current_revision is not None and access.current_revision_id != current_revision.id:
        raise ValueError("성과 리포트 current_revision_id가 최신 revision과 다릅니다.")
    return PerformanceReport(
        id=access.id,
        contract_id=access.contract_id,
        period=access.period,
        source_document_id=access.source_document_id,
        status=access.status,
        extracted_payload=access.extracted_payload,
        current_revision=current_revision,
        revision_count=access.revision_count,
        revisions=ordered,
        created_at=access.created_at,
        updated_at=access.updated_at,
    )


def _performance_flag_basis_snapshot_from_row(row: dict) -> dict:
    return {
        "extracted_term_id": row["extracted_term_id"],
        "document_id": row["document_id"],
        "field": row["field"],
        "source_type": row["source_type"],
        "source_page": row["source_page"],
        "source_text": row["source_text"],
        "confidence": row["confidence"],
        "verification_status": row["verification_status"],
    }


def _performance_flag_from_row(
    row: dict,
    *,
    basis_rows: list[dict],
    draft_row: dict | None,
) -> PerformanceFlag:
    return PerformanceFlag(
        id=UUID(str(row["id"])),
        report_revision_id=UUID(str(row["report_revision_id"])),
        flag_type=row["flag_type"],
        basis_extracted_term_ids=[basis["extracted_term_id"] for basis in basis_rows],
        basis_snapshots=[_performance_flag_basis_snapshot_from_row(basis) for basis in basis_rows],
        comparison_report_revision_id=row.get("comparison_report_revision_id"),
        expected_content_count=row.get("expected_content_count"),
        expected_period_unit=row.get("expected_period_unit"),
        actual_content_count=row.get("actual_content_count"),
        previous_engagement_rate=row.get("previous_engagement_rate"),
        current_engagement_rate=row.get("current_engagement_rate"),
        issue_note=row.get("issue_note"),
        created_at=_parse_datetime(row["created_at"]),
    )


def _performance_revision_from_row(
    row: dict,
    *,
    flag_rows: list[dict],
    basis_by_flag: dict[str, list[dict]],
    drafts_by_flag: dict[str, dict],
) -> PerformanceReportRevision:
    flags = [
        _performance_flag_from_row(
            flag_row,
            basis_rows=basis_by_flag.get(str(flag_row["id"]), []),
            draft_row=drafts_by_flag.get(str(flag_row["id"])),
        )
        for flag_row in flag_rows
    ]
    inquiry_drafts = [
        PerformanceInquiryDraft(
            id=UUID(str(drafts_by_flag[str(flag_row["id"])]["id"])),
            flag_id=UUID(str(flag_row["id"])),
            text=drafts_by_flag[str(flag_row["id"])]["text"],
            template_version=drafts_by_flag[str(flag_row["id"])]["template_version"],
            created_at=_parse_datetime(drafts_by_flag[str(flag_row["id"])]["created_at"]),
        )
        for flag_row in flag_rows
        if str(flag_row["id"]) in drafts_by_flag
    ]
    return PerformanceReportRevision(
        id=UUID(str(row["id"])),
        report_id=UUID(str(row["report_id"])),
        version=int(row["version"]),
        status=row["status"],
        confirmed_payload=row["confirmed_payload"],
        engagement_rate=row.get("engagement_rate"),
        corrected_from_revision_id=row.get("corrected_from_revision_id"),
        correction_reason=row.get("correction_reason"),
        confirmed_at=_parse_datetime(row["confirmed_at"]),
        flags=flags,
        inquiry_drafts=inquiry_drafts,
    )


def _performance_report_from_rows(
    *,
    report_row: dict,
    revision_rows: list[dict],
    flags_by_revision: dict[str, list[dict]],
    basis_by_flag: dict[str, list[dict]],
    drafts_by_flag: dict[str, dict],
) -> PerformanceReport:
    revisions = [
        _performance_revision_from_row(
            revision_row,
            flag_rows=flags_by_revision.get(str(revision_row["id"]), []),
            basis_by_flag=basis_by_flag,
            drafts_by_flag=drafts_by_flag,
        )
        for revision_row in revision_rows
    ]
    extracted_payload = report_row.get("extracted_payload")
    persisted_revision_count = int(report_row.get("revision_count", 0))
    persisted_current_revision_id = (
        UUID(str(report_row["current_revision_id"]))
        if report_row.get("current_revision_id") is not None
        else None
    )
    current_revision = revisions[-1] if revisions else None
    if persisted_revision_count != len(revisions):
        raise ValueError("성과 리포트 revision_count가 저장된 revision 수와 다릅니다.")
    if (persisted_current_revision_id is None) != (current_revision is None):
        raise ValueError("성과 리포트 현재 revision projection이 저장 이력과 다릅니다.")
    if current_revision is not None and persisted_current_revision_id != current_revision.id:
        raise ValueError("성과 리포트 current_revision_id가 최신 revision과 다릅니다.")
    return PerformanceReport(
        id=UUID(str(report_row["id"])),
        contract_id=UUID(str(report_row["contract_id"])),
        period=str(report_row["period"]),
        source_document_id=UUID(str(report_row["source_document_id"])),
        status=report_row["status"],
        extracted_payload=(
            PerformanceExtractedPayload.model_validate(extracted_payload)
            if extracted_payload is not None
            else None
        ),
        current_revision=current_revision,
        revision_count=persisted_revision_count,
        revisions=revisions,
        created_at=_parse_datetime(report_row["created_at"]),
        updated_at=_parse_datetime(report_row["updated_at"]),
    )


def _performance_report_from_snapshot_payload(snapshot: object) -> PerformanceReport:
    if not isinstance(snapshot, dict):
        raise ValueError("성과 리포트 snapshot은 객체여야 합니다.")
    report_row = snapshot.get("report")
    revision_rows = snapshot.get("revisions")
    flag_rows = snapshot.get("flags")
    basis_rows = snapshot.get("basis_terms")
    draft_rows = snapshot.get("inquiry_drafts")
    if not isinstance(report_row, dict) or not all(
        isinstance(rows, list) for rows in (revision_rows, flag_rows, basis_rows, draft_rows)
    ):
        raise ValueError("성과 리포트 snapshot의 중첩 컬렉션이 올바르지 않습니다.")
    if not all(
        isinstance(row, dict)
        for rows in (revision_rows, flag_rows, basis_rows, draft_rows)
        for row in rows
    ):
        raise ValueError("성과 리포트 snapshot 행이 올바르지 않습니다.")

    revision_ids = {str(row["id"]) for row in revision_rows}
    flags_by_revision: dict[str, list[dict]] = {}
    for row in flag_rows:
        revision_id = str(row["report_revision_id"])
        if revision_id not in revision_ids:
            raise ValueError("성과 확인 신호가 snapshot 밖의 revision을 참조합니다.")
        flags_by_revision.setdefault(revision_id, []).append(row)

    flag_ids = {str(row["id"]) for row in flag_rows}
    basis_by_flag: dict[str, list[dict]] = {}
    for row in basis_rows:
        flag_id = str(row["flag_id"])
        if flag_id not in flag_ids:
            raise ValueError("성과 근거가 snapshot 밖의 확인 신호를 참조합니다.")
        basis_by_flag.setdefault(flag_id, []).append(row)

    drafts_by_flag: dict[str, dict] = {}
    for row in draft_rows:
        flag_id = str(row["flag_id"])
        if flag_id not in flag_ids or flag_id in drafts_by_flag:
            raise ValueError("성과 문의 문안의 확인 신호 연결이 올바르지 않습니다.")
        drafts_by_flag[flag_id] = row

    return _performance_report_from_rows(
        report_row=report_row,
        revision_rows=revision_rows,
        flags_by_revision=flags_by_revision,
        basis_by_flag=basis_by_flag,
        drafts_by_flag=drafts_by_flag,
    )


def _performance_flag_to_payload(flag: PerformanceFlag) -> dict:
    return {
        "id": str(flag.id),
        "flag_type": flag.flag_type.value,
        "comparison_report_revision_id": (
            str(flag.comparison_report_revision_id)
            if flag.comparison_report_revision_id is not None
            else None
        ),
        "expected_content_count": flag.expected_content_count,
        "expected_period_unit": flag.expected_period_unit,
        "actual_content_count": flag.actual_content_count,
        "previous_engagement_rate": (
            str(flag.previous_engagement_rate)
            if flag.previous_engagement_rate is not None
            else None
        ),
        "current_engagement_rate": (
            str(flag.current_engagement_rate) if flag.current_engagement_rate is not None else None
        ),
        "issue_note": flag.issue_note,
        "basis_snapshots": [
            {
                "extracted_term_id": str(basis.extracted_term_id),
                "document_id": str(basis.document_id),
                "field": basis.field.value,
                "source_type": basis.source_type.value,
                "source_page": basis.source_page,
                "source_text": basis.source_text,
                "confidence": basis.confidence,
                "verification_status": basis.verification_status.value,
            }
            for basis in flag.basis_snapshots
        ],
    }


def _performance_upload_is_replay(
    *,
    report: PerformanceReportAccess,
    source_document: DocumentRecord | None,
    report_id: UUID,
    period: str,
    requested_document: DocumentRecord,
) -> bool:
    """Compare only immutable upload identity; parse/report status may advance later."""

    return bool(
        source_document is not None
        and report.id == report_id
        and report.contract_id == requested_document.contract_id
        and report.period == period
        and report.source_document_id == requested_document.id
        and report.created_at == requested_document.created_at
        and source_document.id == requested_document.id
        and source_document.contract_id == requested_document.contract_id
        and source_document.type is DocumentType.PERFORMANCE_REPORT
        and source_document.storage_path == requested_document.storage_path
        and source_document.content_type == requested_document.content_type
        and source_document.size_bytes == requested_document.size_bytes
        and source_document.page_count == requested_document.page_count
        and source_document.created_at == requested_document.created_at
    )


def _rpc_json_payload(data: object) -> dict:
    payload = data[0] if isinstance(data, list) and data else data
    if not isinstance(payload, dict):
        raise ExternalStorageFailure("DB RPC 결과가 올바르지 않습니다.")
    return payload


def _performance_confirm_result_from_payload(
    payload: dict,
    *,
    contract_id: UUID,
    report_id: UUID,
    revision: PerformanceReportRevision,
) -> PerformanceReportConfirmResult:
    outcome = payload.get("outcome")
    allowed_outcomes = {
        "CONFIRMED",
        "REVISION_CONFLICT",
        "COMPARISON_REVISION_CONFLICT",
        "PERIOD_ORDER_CONFLICT",
        "CORRECTION_DEPENDENCY_EXISTS",
        "CONTRACT_INVALID_STATUS",
        "REPORT_INVALID_STATUS",
        "NOT_FOUND",
    }
    if outcome not in allowed_outcomes:
        raise ValueError("알 수 없는 광고효과 리포트 확정 결과입니다.")
    snapshot = payload.get("report_snapshot")
    if outcome != "CONFIRMED":
        if snapshot is not None:
            raise ValueError("거부된 광고효과 리포트 확정 결과에 snapshot이 포함됐습니다.")
        return PerformanceReportConfirmResult(outcome=outcome)

    report = _performance_report_from_snapshot_payload(snapshot)
    if (
        report.id != report_id
        or report.contract_id != contract_id
        or report.current_revision is None
        or report.current_revision.id != revision.id
        or report.current_revision.version != revision.version
        or not _performance_revision_snapshot_matches(report.current_revision, revision)
        or report.revision_count != revision.version
    ):
        raise ValueError("확정 RPC snapshot이 이번 요청의 revision projection과 다릅니다.")
    return PerformanceReportConfirmResult(outcome="CONFIRMED", report=report)


def _performance_revision_snapshot_matches(
    actual: PerformanceReportRevision,
    expected: PerformanceReportRevision,
) -> bool:
    if (
        actual.id,
        actual.report_id,
        actual.version,
        actual.status,
        actual.confirmed_payload,
        actual.engagement_rate,
        actual.corrected_from_revision_id,
        actual.correction_reason,
        actual.confirmed_at,
    ) != (
        expected.id,
        expected.report_id,
        expected.version,
        expected.status,
        expected.confirmed_payload,
        expected.engagement_rate,
        expected.corrected_from_revision_id,
        expected.correction_reason,
        expected.confirmed_at,
    ):
        return False
    return {flag.id: flag for flag in actual.flags} == {
        flag.id: flag for flag in expected.flags
    } and {draft.id: draft for draft in actual.inquiry_drafts} == {
        draft.id: draft for draft in expected.inquiry_drafts
    }


def _owned_contract_performance_reports_from_payload(
    payload: dict,
    *,
    contract_id: UUID,
) -> list[PerformanceReport] | None:
    outcome = payload.get("outcome")
    raw_snapshots = payload.get("report_snapshots")
    if outcome == "NOT_FOUND":
        if raw_snapshots is not None:
            raise ValueError("소유하지 않은 계약 snapshot에 리포트가 포함됐습니다.")
        return None
    if outcome != "FOUND" or not isinstance(raw_snapshots, list):
        raise ValueError("계약별 광고효과 snapshot 결과가 올바르지 않습니다.")

    reports = [_performance_report_from_snapshot_payload(snapshot) for snapshot in raw_snapshots]
    if any(report.contract_id != contract_id for report in reports):
        raise ValueError("계약별 광고효과 snapshot에 다른 계약의 리포트가 포함됐습니다.")
    expected_order = sorted(reports, key=lambda report: (report.period, str(report.id)))
    if reports != expected_order or len({report.id for report in reports}) != len(reports):
        raise ValueError("계약별 광고효과 snapshot의 정렬 또는 고유성이 올바르지 않습니다.")
    return reports


def _previous_performance_period(period: str) -> str | None:
    year, month = (int(part) for part in period.split("-"))
    if month == 1:
        if year == 1:
            return None
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def _performance_upload_result_from_payload(payload: dict) -> PerformanceReportUploadResult:
    outcome = payload.get("outcome")
    successful = outcome in {"CREATED", "REPLAYED"}
    if outcome not in {
        "CREATED",
        "REPLAYED",
        "PERIOD_ALREADY_EXISTS",
        "INVALID_STATUS",
        "NOT_FOUND",
        "CONFLICT",
    }:
        raise ExternalStorageFailure("성과 리포트 업로드 저장 결과가 올바르지 않습니다.")

    report_row = payload.get("report")
    document_row = payload.get("source_document")
    if successful != (isinstance(report_row, dict) and isinstance(document_row, dict)):
        raise ExternalStorageFailure("성과 리포트 업로드 저장 결과가 완전하지 않습니다.")
    if not successful and (report_row is not None or document_row is not None):
        raise ExternalStorageFailure("성과 리포트 업로드 거부 결과에 자원이 포함됐습니다.")

    try:
        return PerformanceReportUploadResult(
            outcome=outcome,
            report=(
                _performance_report_access_from_row(report_row)
                if isinstance(report_row, dict)
                else None
            ),
            source_document=(
                SupabaseAdapter._document_record_from_row(document_row)
                if isinstance(document_row, dict)
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ExternalStorageFailure("성과 리포트 업로드 저장 결과가 올바르지 않습니다.") from error


def _performance_extraction_claim_from_payload(
    payload: dict,
) -> PerformanceExtractionClaim:
    outcome = payload.get("outcome")
    if outcome not in {
        "CLAIMED",
        "RECOVERED",
        "IN_PROGRESS",
        "INVALID_STATUS",
        "NOT_FOUND",
    }:
        raise ExternalStorageFailure("광고효과 추출 점유 결과가 올바르지 않습니다.")
    report_row = payload.get("report")
    document_row = payload.get("source_document")
    if (report_row is None) != (document_row is None):
        raise ExternalStorageFailure("광고효과 추출 점유 결과가 완전하지 않습니다.")
    try:
        return PerformanceExtractionClaim(
            outcome=outcome,
            report=(
                _performance_report_access_from_row(report_row)
                if isinstance(report_row, dict)
                else None
            ),
            source_document=(
                SupabaseAdapter._document_record_from_row(document_row)
                if isinstance(document_row, dict)
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ExternalStorageFailure("광고효과 추출 점유 결과가 올바르지 않습니다.") from error


def _performance_extraction_apply_result_from_payload(
    payload: dict,
) -> PerformanceExtractionApplyResult:
    outcome = payload.get("outcome")
    if outcome not in {"APPLIED", "STALE", "INVALID_STATUS", "NOT_FOUND"}:
        raise ExternalStorageFailure("광고효과 추출 저장 결과가 올바르지 않습니다.")
    report_row = payload.get("report")
    document_row = payload.get("source_document")
    if (report_row is None) != (document_row is None):
        raise ExternalStorageFailure("광고효과 추출 저장 결과가 완전하지 않습니다.")
    try:
        return PerformanceExtractionApplyResult(
            outcome=outcome,
            report=(
                _performance_report_access_from_row(report_row)
                if isinstance(report_row, dict)
                else None
            ),
            source_document=(
                SupabaseAdapter._document_record_from_row(document_row)
                if isinstance(document_row, dict)
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ExternalStorageFailure("광고효과 추출 저장 결과가 올바르지 않습니다.") from error


def _analysis_task_record_from_row(row: dict) -> AnalysisTaskRecord:
    result = row.get("result")
    return AnalysisTaskRecord(
        id=UUID(str(row["id"])),
        contract_id=UUID(str(row["contract_id"])),
        document_id=UUID(str(row["document_id"])),
        supporting_document_ids=tuple(
            UUID(str(document_id)) for document_id in row.get("supporting_document_ids") or []
        ),
        status=AnalysisStatus(row["status"]),
        attempt_count=int(row["attempt_count"]),
        error_code=ErrorCode(row["error_code"]) if row.get("error_code") else None,
        result=Analysis.model_validate(result) if result is not None else None,
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _review_item_from_row(row: dict) -> ReviewItem:
    return ReviewItem.model_validate(
        {
            "id": row["id"],
            "contract_id": row["contract_id"],
            "type": row["type"],
            "severity": row["severity"],
            "detection_method": row["detection_method"],
            "model_confidence": row.get("model_confidence"),
            "model_limitations": row.get("model_limitations"),
            "plain_explanation": row["plain_explanation"],
            "basis_type": row["basis_type"],
            "basis_text": row["basis_text"],
            "basis_citation": row.get("basis_citation"),
            "related_extracted_term_ids": row["related_extracted_term_ids"],
            "source_document_id": row.get("source_document_id"),
            "source_page": row.get("source_page"),
            "source_text": row.get("source_text"),
            "source_confidence": row.get("source_confidence"),
            "verification_status": row["verification_status"],
            "suggestion_accept": row["suggestion_accept"],
            "suggestion_compromise": row["suggestion_compromise"],
            "suggestion_request": row["suggestion_request"],
            "user_choice": row.get("user_choice"),
            "status": row["status"],
        }
    )


def _review_item_for_adjustment(item: ReviewItem) -> ReviewItemForAdjustment:
    return ReviewItemForAdjustment(
        id=item.id,
        contract_id=item.contract_id,
        status=item.status,
        user_choice=item.user_choice,
        suggestion_compromise=item.suggestion_compromise,
        suggestion_request=item.suggestion_request,
    )


def _review_item_for_adjustment_from_row(row: dict) -> ReviewItemForAdjustment:
    return ReviewItemForAdjustment(
        id=UUID(str(row["id"])),
        contract_id=UUID(str(row["contract_id"])),
        status=ReviewItemStatus(row["status"]),
        user_choice=SuggestionChoice(row["user_choice"]) if row.get("user_choice") else None,
        suggestion_compromise=row["suggestion_compromise"],
        suggestion_request=row["suggestion_request"],
        category=AgreementClauseCategory(row.get("category", "OTHER")),
        original_text=row.get("original_text", "원계약에서 확인되지 않아 추가 확인 필요"),
    )


def _adjustment_request_record_from_row(row: dict) -> AdjustmentRequestRecord:
    items = tuple(
        AdjustmentRequestItemRecord(
            review_item_id=UUID(str(item["review_item_id"])),
            user_choice=SuggestionChoice(item["user_choice"]),
            request_text=item["request_text"],
            category=AgreementClauseCategory(item.get("category", "OTHER")),
            before_text=item.get("before_text", "원계약에서 확인되지 않아 추가 확인 필요"),
        )
        for item in row["items"]
    )
    return AdjustmentRequestRecord(
        id=UUID(str(row["id"])),
        contract_id=UUID(str(row["contract_id"])),
        status=AdjustmentRequestStatus(row["status"]),
        items=items,
        expires_in_hours=int(row["expires_in_hours"]),
        sent_at=_parse_datetime(row["sent_at"]) if row.get("sent_at") else None,
        expires_at=_parse_datetime(row["expires_at"]) if row.get("expires_at") else None,
        opened_at=_parse_datetime(row["opened_at"]) if row.get("opened_at") else None,
        responded_at=_parse_datetime(row["responded_at"]) if row.get("responded_at") else None,
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _adjustment_response_record_from_row(row: dict) -> AdjustmentResponseRecord:
    return AdjustmentResponseRecord(
        review_item_id=UUID(str(row["review_item_id"])),
        decision=AdjustmentResponseDecision(row["decision"]),
        counter_text=row.get("counter_text"),
        reason=row.get("reason"),
    )


def _adjustment_detail_record_from_row(row: dict) -> AdjustmentDetailRecord:
    return AdjustmentDetailRecord(
        request=_adjustment_request_record_from_row(row["request"]),
        responses=tuple(
            _adjustment_response_record_from_row(response) for response in row.get("responses", [])
        ),
    )


def _public_adjustment_record_from_row(row: dict) -> PublicAdjustmentRecord:
    return PublicAdjustmentRecord(
        contract_title=row["contract_title"],
        request=_adjustment_request_record_from_row(row["request"]),
    )


def _final_clause_record_from_row(row: dict) -> FinalClauseRecord:
    return FinalClauseRecord(
        review_item_id=UUID(str(row["review_item_id"])),
        category=AgreementClauseCategory(row["category"]),
        resolution=AdjustmentResolution(row["resolution"]),
        outcome=row["outcome"],
        disposition=row["disposition"],
        before_text=row["before_text"],
        after_text=row["after_text"],
        reason=row.get("reason"),
    )


def _agreement_creation_context_from_row(
    row: dict,
    *,
    owner_id: UUID,
) -> AgreementCreationContext:
    contract = _contract_record_from_row(row["contract"], owner_id=owner_id)
    return AgreementCreationContext(
        contract=contract,
        original_document_id=(
            UUID(str(row["original_document_id"])) if row.get("original_document_id") else None
        ),
        adjustment_request_id=(
            UUID(str(row["adjustment_request_id"])) if row.get("adjustment_request_id") else None
        ),
        final_clauses=tuple(
            _final_clause_record_from_row(clause) for clause in row.get("final_clauses", [])
        ),
    )


def _agreement_record_from_row(row: dict) -> AgreementRecord:
    return AgreementRecord(
        agreement=Agreement.model_validate(row["agreement"]),
        adjustment_request_id=UUID(str(row["adjustment_request_id"])),
        pdf_storage_path=str(row["pdf_storage_path"]),
        pdf_sha256=str(row["pdf_sha256"]),
        pdf_size_bytes=int(row["pdf_size_bytes"]),
        pdf_page_count=int(row["pdf_page_count"]),
        created_at=_parse_datetime(row["created_at"]),
    )


def _signature_record_from_row(row: dict) -> SignatureRecord:
    return SignatureRecord(
        signature=Signature.model_validate(row["signature"]),
        revised_contract_review_id=(
            UUID(str(row["revised_contract_review_id"]))
            if row.get("revised_contract_review_id")
            else None
        ),
        document_id=UUID(str(row["document_id"])) if row.get("document_id") else None,
        document_sha256=row.get("document_sha256"),
        agreement_id=UUID(str(row["agreement_id"])) if row.get("agreement_id") else None,
        agreement_version=(int(row["agreement_version"]) if row.get("agreement_version") else None),
        idempotency_key=UUID(str(row["idempotency_key"])),
    )
