from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.core.enums import ContractStatus, RenewalDecisionType
from app.schemas.contracts import ContractCreate, RenewalDecision
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
    renewal_decision: RenewalDecision | None
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


class RenewalDecisionSaveOutcome(StrEnum):
    SAVED = "SAVED"
    UNCHANGED = "UNCHANGED"
    NOT_FOUND = "NOT_FOUND"
    OUTSIDE_REVIEW_WINDOW = "OUTSIDE_REVIEW_WINDOW"


@dataclass(frozen=True)
class RenewalDecisionSaveResult:
    outcome: RenewalDecisionSaveOutcome
    decision: RenewalDecision | None


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

    async def save_renewal_decision_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        decision: RenewalDecisionType,
        today: date,
        decided_at: datetime,
    ) -> RenewalDecisionSaveResult: ...
