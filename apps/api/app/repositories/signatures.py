from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.schemas.signatures import Signature


@dataclass(frozen=True)
class SignatureRecord:
    signature: Signature
    agreement_id: UUID
    agreement_version: int
    idempotency_key: UUID


class SignatureRepository(Protocol):
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
