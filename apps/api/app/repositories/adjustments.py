from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.core.enums import AdjustmentRequestStatus, ReviewItemStatus, SuggestionChoice
from app.repositories.public_tokens import PublicTokenRecord


@dataclass(frozen=True)
class ReviewItemForAdjustment:
    id: UUID
    contract_id: UUID
    status: ReviewItemStatus
    user_choice: SuggestionChoice | None
    suggestion_compromise: str
    suggestion_request: str


@dataclass(frozen=True)
class AdjustmentRequestItemRecord:
    review_item_id: UUID
    user_choice: SuggestionChoice
    request_text: str


@dataclass(frozen=True)
class AdjustmentRequestRecord:
    id: UUID
    contract_id: UUID
    status: AdjustmentRequestStatus
    items: tuple[AdjustmentRequestItemRecord, ...]
    expires_in_hours: int
    sent_at: datetime | None
    expires_at: datetime | None
    opened_at: datetime | None
    responded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdjustmentRepository(Protocol):
    async def list_review_items_for_adjustment(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        review_item_ids: list[UUID],
    ) -> list[ReviewItemForAdjustment] | None: ...

    async def create_adjustment_draft_with_audit(
        self,
        *,
        owner_id: UUID,
        record: AdjustmentRequestRecord,
    ) -> AdjustmentRequestRecord | None: ...

    async def get_owned_adjustment_request(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
    ) -> AdjustmentRequestRecord | None: ...

    async def send_adjustment_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
        sent_at: datetime,
        public_token: PublicTokenRecord,
    ) -> AdjustmentRequestRecord | None: ...
