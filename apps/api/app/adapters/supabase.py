import asyncio
import hmac
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Literal
from uuid import UUID

from supabase import Client, create_client

from app.core.exceptions import ExternalStorageFailure
from app.repositories.documents import DocumentRecord
from app.schemas.documents import DocumentParseStatus, DocumentType


@dataclass(frozen=True)
class MockAuditEvent:
    contract_id: UUID
    event_type: str
    actor_type: str
    created_at: datetime


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
    ) -> None:
        self.mode = mode
        self.bucket = bucket
        self._demo_owner_id = demo_owner_id
        self._demo_bearer_token = demo_bearer_token
        self._client: Client | None = None
        self._mock_lock = asyncio.Lock()
        self._mock_owned_contracts = {(demo_owner_id, demo_contract_id)}
        self._mock_objects: dict[str, bytes] = {}
        self._mock_documents: dict[UUID, DocumentRecord] = {}
        self._mock_audit_events: list[MockAuditEvent] = []
        if mode == "live":
            self._client = create_client(url, service_role_key)

    @property
    def mock_objects(self) -> dict[str, bytes]:
        return dict(self._mock_objects)

    @property
    def mock_documents(self) -> dict[UUID, DocumentRecord]:
        return dict(self._mock_documents)

    @property
    def mock_audit_events(self) -> tuple[MockAuditEvent, ...]:
        return tuple(self._mock_audit_events)

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
