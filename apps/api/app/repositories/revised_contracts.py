from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.repositories.adjustments import FinalClauseRecord
from app.schemas.revised_contracts import RevisedContractReview


@dataclass(frozen=True)
class RevisedContractContext:
    contract_title: str
    final_clauses: tuple[FinalClauseRecord, ...]


class RevisedContractRepository(Protocol):
    async def get_revised_contract_context(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
    ) -> RevisedContractContext | None: ...

    async def create_revised_contract_review_with_audit(
        self,
        *,
        owner_id: UUID,
        review: RevisedContractReview,
    ) -> RevisedContractReview | None: ...

    async def get_latest_owned_revised_contract_review(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> RevisedContractReview | None: ...

    async def confirm_revised_contract_review_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        review_id: UUID,
        confirmed_review_item_ids: tuple[UUID, ...],
        confirmed_at: datetime,
    ) -> RevisedContractReview | None: ...
