from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.enums import ReviewItemStatus, ReviewSignalType
from app.repositories.contracts import ContractRecord
from app.repositories.obligations import ObligationRecord


@dataclass(frozen=True)
class DashboardReviewItem:
    """Narrow ReviewItem projection: only the fields the dashboard aggregates."""

    contract_id: UUID
    type: ReviewSignalType
    status: ReviewItemStatus


class DashboardRepository(Protocol):
    async def list(self, *, owner_id: UUID) -> Sequence[ContractRecord]: ...

    async def list_dashboard_obligations(
        self, *, owner_id: UUID
    ) -> Sequence[ObligationRecord]: ...

    async def list_dashboard_review_items(
        self, *, owner_id: UUID
    ) -> Sequence[DashboardReviewItem]: ...

    async def list_dashboard_adjustment_request_item_counts(
        self, *, owner_id: UUID
    ) -> Sequence[int]:
        """Item counts of non-DRAFT adjustment requests owned by owner_id."""
        ...
