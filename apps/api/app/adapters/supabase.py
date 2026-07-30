import asyncio
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Literal
from uuid import UUID

from supabase import Client, create_client

from app.core.exceptions import ExternalStorageFailure
from app.repositories.documents import DocumentRecord
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermInput


@dataclass(frozen=True)
class MockAuditEvent:
    contract_id: UUID
    event_type: str
    actor_type: str
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
        self._mock_objects: dict[str, bytes] = {}
        self._mock_object_content_types: dict[str, str] = {}
        self._mock_documents: dict[UUID, DocumentRecord] = {}
        self._mock_understood_terms: dict[UUID, UnderstoodTerm] = {}
        self._mock_audit_events: list[MockAuditEvent] = []
        self._mock_signed_accesses: dict[str, MockSignedAccess] = {}
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
    def mock_audit_events(self) -> tuple[MockAuditEvent, ...]:
        return tuple(self._mock_audit_events)

    @property
    def mock_signed_accesses(self) -> tuple[MockSignedAccess, ...]:
        return tuple(self._mock_signed_accesses.values())

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
                        contract_id=record.contract_id,
                        event_type="DOCUMENT_UPLOADED",
                        actor_type="OWNER",
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
                        contract_id=contract_id,
                        event_type="UNDERSTOOD_TERMS_SAVED",
                        actor_type="OWNER",
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

    def _require_live_client(self) -> Client:
        if self._client is None:
            raise RuntimeError("Supabase live client가 초기화되지 않았습니다.")
        return self._client
