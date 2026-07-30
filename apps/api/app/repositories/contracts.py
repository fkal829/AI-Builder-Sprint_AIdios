from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from app.core.enums import ContractStatus
from app.schemas.contracts import ContractCreate
from app.schemas.understood_terms import UnderstoodTerm


@dataclass(frozen=True)
class ContractRecord:
    id: UUID
    owner_id: UUID
    title: str
    counterparty_name: str
    status: ContractStatus
    signed_date: date | None
    start_date: date | None
    end_date: date | None
    termination_notice_date: date | None
    renewal_type: str | None
    total_amount: int | None
    understood_term: UnderstoodTerm | None
    renewal_decision: dict[str, Any] | None
    modusign_document_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuditEventRecord:
    id: UUID
    contract_id: UUID
    event_type: str
    actor_type: str
    summary: str | None
    created_at: datetime


class ContractRepository(Protocol):
    async def create(
        self,
        *,
        owner_id: UUID,
        payload: ContractCreate,
        record: ContractRecord,
    ) -> ContractRecord: ...

    async def get(self, *, owner_id: UUID, contract_id: UUID) -> ContractRecord | None: ...

    async def list(self, *, owner_id: UUID) -> Sequence[ContractRecord]: ...

    async def list_audit_events(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> Sequence[AuditEventRecord] | None: ...
