from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.core.enums import ObligationStatus


@dataclass(frozen=True)
class ObligationRecord:
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
    evidence_url: str | None
    status: ObligationStatus
    submitted_at: datetime | None
    reviewed_at: datetime | None
    payment_condition_met: bool


class ObligationRepository(Protocol):
    async def list_owned_obligations(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> Sequence[ObligationRecord] | None: ...
