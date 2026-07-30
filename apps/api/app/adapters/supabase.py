import asyncio
import hmac
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import partial
from typing import Literal
from uuid import UUID, uuid4

from supabase import Client, create_client

from app.core.enums import ContractStatus
from app.core.exceptions import ExternalStorageFailure
from app.repositories.contracts import AuditEventRecord, ContractRecord
from app.repositories.documents import DocumentRecord
from app.schemas.contracts import ContractCreate
from app.schemas.documents import DocumentParseStatus, DocumentType


@dataclass(frozen=True)
class MockAuditEvent:
    id: UUID
    contract_id: UUID
    event_type: str
    actor_type: str
    summary: str | None
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
        self._mock_contracts: dict[UUID, ContractRecord] = {}
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

    @property
    def mock_contracts(self) -> dict[UUID, ContractRecord]:
        return dict(self._mock_contracts)

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
                return self._mock_contracts.get(contract_id)

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
        return _contract_record_from_row(response.data[0], owner_id=owner_id)

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


def _contract_record_from_row(row: dict, *, owner_id: UUID) -> ContractRecord:
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
        understood_term=row.get("understood_term"),
        renewal_decision=row.get("renewal_decision"),
        modusign_document_id=row.get("modusign_document_id"),
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
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
