from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.repositories.adjustments import FinalClauseRecord
from app.repositories.contracts import ContractRecord
from app.schemas.agreements import Agreement


@dataclass(frozen=True)
class AgreementCreationContext:
    contract: ContractRecord
    original_document_id: UUID | None
    adjustment_request_id: UUID | None
    final_clauses: tuple[FinalClauseRecord, ...]


@dataclass(frozen=True)
class AgreementRecord:
    agreement: Agreement
    adjustment_request_id: UUID
    pdf_storage_path: str
    pdf_sha256: str
    pdf_size_bytes: int
    pdf_page_count: int
    created_at: datetime


class AgreementRepository(Protocol):
    async def get_agreement_creation_context(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> AgreementCreationContext | None: ...

    async def create_agreement_with_audit(
        self,
        *,
        owner_id: UUID,
        record: AgreementRecord,
    ) -> AgreementRecord | None: ...

    async def get_owned_agreement(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> AgreementRecord | None: ...
