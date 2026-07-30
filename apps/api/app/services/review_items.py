from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from app.core.enums import ReviewItemStatus, SuggestionChoice
from app.core.exceptions import ResourceNotFound
from app.repositories.review_items import (
    ReviewItemRepository,
    ReviewItemSelectionOutcome,
)
from app.schemas.analysis import ReviewItem, ReviewItemUpdate
from app.services.state_machine import InvalidStatusTransition


class ReviewItemService:
    def __init__(
        self,
        *,
        repository: ReviewItemRepository,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    async def update_selection(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        item_id: UUID,
        payload: ReviewItemUpdate,
    ) -> ReviewItem:
        target_status = (
            ReviewItemStatus.RESOLVED
            if payload.user_choice == SuggestionChoice.ACCEPT
            else ReviewItemStatus.SELECTED
        )
        result = await self._repository.update_review_item_selection_with_audit(
            owner_id=owner_id,
            contract_id=contract_id,
            item_id=item_id,
            user_choice=payload.user_choice,
            target_status=target_status,
            updated_at=self._utc_now(),
        )
        if result.outcome == ReviewItemSelectionOutcome.NOT_FOUND:
            raise ResourceNotFound()
        if result.outcome == ReviewItemSelectionOutcome.INVALID_STATUS_TRANSITION:
            raise InvalidStatusTransition("현재 상태에서는 검토 항목 선택을 수정할 수 없습니다.")
        if result.item is None:
            raise RuntimeError("검토 항목 선택 저장 결과가 없습니다.")
        return result.item

    def _utc_now(self) -> datetime:
        now = self._now()
        if now.tzinfo is None:
            raise ValueError("Review item timestamps must be timezone-aware.")
        return now.astimezone(UTC)
