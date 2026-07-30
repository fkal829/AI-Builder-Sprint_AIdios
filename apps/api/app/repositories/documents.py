from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.schemas.documents import DocumentParseStatus, DocumentType


@dataclass(frozen=True)
class DocumentRecord:
    id: UUID
    contract_id: UUID
    type: DocumentType
    parse_status: DocumentParseStatus
    storage_path: str
    content_type: str
    size_bytes: int
    page_count: int
    created_at: datetime


class OwnerAuthenticator(Protocol):
    async def authenticate_owner(self, token: str) -> UUID | None: ...


class ContractOwnershipRepository(Protocol):
    async def is_contract_owned(self, *, owner_id: UUID, contract_id: UUID) -> bool: ...


class DocumentRepository(Protocol):
    async def create_document_with_audit(
        self,
        *,
        owner_id: UUID,
        record: DocumentRecord,
    ) -> DocumentRecord | None: ...

    async def get_owned_document(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_id: UUID,
    ) -> DocumentRecord | None: ...


class PrivateStorage(Protocol):
    async def upload_private_object(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
    ) -> None: ...

    async def delete_private_object(self, *, path: str) -> None: ...

    async def create_signed_access_url(
        self,
        *,
        path: str,
        expires_in_seconds: int,
    ) -> str: ...
