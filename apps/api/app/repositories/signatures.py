from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.schemas.signatures import Signature


@dataclass(frozen=True)
class SignatureRecord:
    signature: Signature
    agreement_id: UUID | None
    agreement_version: int | None
    idempotency_key: UUID
    revised_contract_review_id: UUID | None = None
    document_id: UUID | None = None
    document_sha256: str | None = None


class SignatureRepository(Protocol):
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
    ) -> SignatureRecord | None: ...

    async def complete_embedded_signature_draft(
        self,
        *,
        owner_id: UUID,
        signature_id: UUID,
        modusign_draft_id: str,
    ) -> SignatureRecord | None: ...

    async def fail_embedded_signature_draft(
        self,
        *,
        owner_id: UUID,
        signature_id: UUID,
        completed_at: datetime,
    ) -> SignatureRecord | None: ...

    async def get_latest_owned_signature(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> SignatureRecord | None: ...
