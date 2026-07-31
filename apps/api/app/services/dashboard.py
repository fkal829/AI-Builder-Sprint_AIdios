from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import Dashboard

SEOUL = timezone(timedelta(hours=9), name="Asia/Seoul")


class DashboardService:
    def __init__(
        self,
        repository: DashboardRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    async def get(self, *, owner_id: UUID) -> Dashboard:
        now = self._now()
        if now.tzinfo is None:
            raise ValueError("Dashboard timestamps must be timezone-aware.")
        record = await self._repository.get_dashboard(
            owner_id=owner_id,
            today=now.astimezone(SEOUL).date(),
        )
        return Dashboard(
            total=record.total,
            signing=record.signing,
            in_progress=record.in_progress,
            completed=record.completed,
            expiring_soon=record.expiring_soon,
            unresolved_signals=record.unresolved_signals,
            adjustment_requested_clauses=record.adjustment_requested_clauses,
            adjustment_agreed_clauses=record.adjustment_agreed_clauses,
            adjustment_rejected_clauses=record.adjustment_rejected_clauses,
            obligation_pending=record.obligation_pending,
            obligation_submitted=record.obligation_submitted,
            obligation_approved=record.obligation_approved,
            total_committed=record.total_committed,
            payment_condition_met_amount=record.payment_condition_met_amount,
            most_common_signal=record.most_common_signal,
        )
