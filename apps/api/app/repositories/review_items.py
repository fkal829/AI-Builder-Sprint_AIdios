from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.core.enums import ReviewItemStatus, SuggestionChoice
from app.schemas.analysis import ReviewItem


class ReviewItemSelectionOutcome(StrEnum):
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"


@dataclass(frozen=True)
class ReviewItemSelectionResult:
    outcome: ReviewItemSelectionOutcome
    item: ReviewItem | None


class ReviewItemRepository(Protocol):
    async def update_review_item_selection_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        item_id: UUID,
        user_choice: SuggestionChoice,
        target_status: ReviewItemStatus,
        updated_at: datetime,
    ) -> ReviewItemSelectionResult: ...
