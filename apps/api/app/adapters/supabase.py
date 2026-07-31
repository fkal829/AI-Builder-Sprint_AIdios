import asyncio
import hmac
import secrets
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
    PublicTokenScope,
    RenewalDecisionType,
    ReviewItemStatus,
    SuggestionChoice,
    VerificationStatus,
)
from app.core.errors import ErrorCode
from app.core.exceptions import ExternalStorageFailure
from app.domain.obligations import build_representative_obligation
from app.repositories.adjustments import (
    AdjustmentDetailRecord,
    AdjustmentRequestItemRecord,
    AdjustmentRequestRecord,
    AdjustmentResponseRecord,
    FinalClauseRecord,
    PublicAdjustmentRecord,
    ReviewItemForAdjustment,
)
from app.repositories.agreements import AgreementCreationContext, AgreementRecord
from app.repositories.analysis import AnalysisTaskRecord
from app.repositories.contracts import (
    AuditEventRecord,
    ContractRecord,
    RenewalDecisionSaveOutcome,
    RenewalDecisionSaveResult,
)
from app.repositories.documents import DocumentRecord
from app.repositories.idempotency import IdempotencyClaim, IdempotencyRecord
from app.repositories.obligations import (
    EvidenceLinkCreateOutcome,
    EvidenceSubmissionOutcome,
    ObligationRecord,
)
from app.repositories.public_tokens import PublicTokenRecord
from app.repositories.review_items import (
    ReviewItemSelectionOutcome,
    ReviewItemSelectionResult,
)
from app.repositories.signatures import SignatureRecord
from app.repositories.webhooks import ModusignWebhookReceipt
from app.schemas.agreements import Agreement
from app.schemas.analysis import Analysis, ReviewItem
from app.schemas.contracts import ContractCreate, RenewalDecision
from app.schemas.documents import DocumentParseStatus, DocumentType
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
        mock_storage_access_base_url: str = (
            "http://localhost:8000/api/v1/_mock/storage"
        ),
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
        self._mock_adjustment_responses: dict[
            UUID, tuple[AdjustmentResponseRecord, ...]
        ] = {}
        self._mock_final_clauses: dict[UUID, tuple[FinalClauseRecord, ...]] = {}
        self._mock_agreements: dict[UUID, AgreementRecord] = {}
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
                    .select(
                        "contract_id,decision,decided_at,revisit_review_item_ids"
                    )
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
            id=UUID(row["id"]),
            contract_id=UUID(row["contract_id"]),
            type=DocumentType(row["type"]),
            parse_status=DocumentParseStatus(row["parse_status"]),
            storage_path=row["storage_path"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            page_count=row["page_count"],
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
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
                    client.table("contracts")
                    .select("*")
                    .eq("owner_id", str(owner_id))
                    .execute()
                )
            )
        except Exception as error:
            raise ExternalStorageFailure("계약 목록 조회에 실패했습니다.") from error
        return [_contract_record_from_row(row, owner_id=owner_id) for row in response.data or []]

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

    async def create_obligation_evidence_link_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        obligation_id: UUID,
        public_token: PublicTokenRecord,
    ) -> EvidenceLinkCreateOutcome:
        if (
            public_token.scope != PublicTokenScope.OBLIGATION_EVIDENCE
            or public_token.resource_id != obligation_id
            or public_token.expires_at <= public_token.created_at
        ):
            raise ValueError("증빙 제출 공개 토큰 정보가 올바르지 않습니다.")

        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, contract_id) not in self._mock_owned_contracts:
                    return EvidenceLinkCreateOutcome.NOT_FOUND
                obligation = self._mock_obligations.get(contract_id)
                if obligation is None or obligation.id != obligation_id:
                    return EvidenceLinkCreateOutcome.NOT_FOUND
                if obligation.status != ObligationStatus.PENDING:
                    return EvidenceLinkCreateOutcome.INVALID_STATUS_TRANSITION
                if public_token.token_hash in self._mock_public_tokens:
                    raise ExternalStorageFailure("증빙 제출 링크 저장에 실패했습니다.")
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
                return EvidenceLinkCreateOutcome.CREATED

        client = self._require_live_client()
        params = {
            "p_owner_id": str(owner_id),
            "p_contract_id": str(contract_id),
            "p_obligation_id": str(obligation_id),
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
                    "create_obligation_evidence_link_with_audit",
                    params,
                ).execute()
            )
        except Exception as error:
            raise ExternalStorageFailure("증빙 제출 링크 저장에 실패했습니다.") from error
        payload = response.data[0] if isinstance(response.data, list) else response.data
        try:
            return EvidenceLinkCreateOutcome(payload)
        except (TypeError, ValueError) as error:
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
            raise ExternalStorageFailure(
                "증빙 URL 제출 저장 결과를 확인할 수 없습니다."
            ) from error

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
                if (
                    contract is None
                    or (owner_id, contract_id) not in self._mock_owned_contracts
                ):
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
                if (
                    obligation is not None
                    and obligation.contract_id not in self._mock_obligations
                ):
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
            item=_review_item_from_row(item_payload)
            if isinstance(item_payload, dict)
            else None,
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

    async def create_adjustment_draft_with_audit(
        self,
        *,
        owner_id: UUID,
        record: AdjustmentRequestRecord,
    ) -> AdjustmentRequestRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                if (owner_id, record.contract_id) not in self._mock_owned_contracts:
                    return None
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
            "p_review_item_ids": [str(item.review_item_id) for item in record.items],
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
                    item is None or item.status != ReviewItemStatus.SENT
                    for item in review_items
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
                self._mock_contracts[contract_id] = replace(
                    contract,
                    status=ContractStatus.READY_TO_SIGN,
                    updated_at=confirmed_at,
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
        agreement_id: UUID,
        agreement_version: int,
        idempotency_key: UUID,
        requested_at: datetime,
    ) -> SignatureRecord | None:
        if self.mode == "mock":
            async with self._mock_lock:
                contract = self._mock_contracts.get(contract_id)
                agreement = self._mock_agreements.get(contract_id)
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
                if (
                    contract is None
                    or contract.owner_id != owner_id
                    or contract.status != ContractStatus.READY_TO_SIGN
                    or agreement is None
                    or agreement.agreement.id != agreement_id
                    or agreement.agreement.version != agreement_version
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
            "p_agreement_id": str(agreement_id),
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
                elif status not in {
                    ModusignStatus.DRAFT,
                    ModusignStatus.SCHEDULED,
                    ModusignStatus.ON_PROCESSING,
                } or signature.status != InternalSignatureStatus.EDITING:
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
                review_items = [
                    self._mock_review_items.get(item_id) for item_id in review_item_ids
                ]
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
            _parse_datetime(row["submitted_at"])
            if row.get("submitted_at") is not None
            else None
        ),
        reviewed_at=(
            _parse_datetime(row["reviewed_at"])
            if row.get("reviewed_at") is not None
            else None
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
            UnderstoodTerm.model_validate(understood_term)
            if understood_term is not None
            else None
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
        expiry_d_day
        if contract.renewal_type == "AUTO" and contract.end_date
        else None
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


def _analysis_task_record_from_row(row: dict) -> AnalysisTaskRecord:
    result = row.get("result")
    return AnalysisTaskRecord(
        id=UUID(str(row["id"])),
        contract_id=UUID(str(row["contract_id"])),
        document_id=UUID(str(row["document_id"])),
        supporting_document_ids=tuple(
            UUID(str(document_id))
            for document_id in row.get("supporting_document_ids") or []
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
            before_text=item.get(
                "before_text", "원계약에서 확인되지 않아 추가 확인 필요"
            ),
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
            _adjustment_response_record_from_row(response)
            for response in row.get("responses", [])
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
            UUID(str(row["original_document_id"]))
            if row.get("original_document_id")
            else None
        ),
        adjustment_request_id=(
            UUID(str(row["adjustment_request_id"]))
            if row.get("adjustment_request_id")
            else None
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
        agreement_id=UUID(str(row["agreement_id"])),
        agreement_version=int(row["agreement_version"]),
        idempotency_key=UUID(str(row["idempotency_key"])),
    )
