from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from app.core.enums import ReviewSignalType

DASHBOARD_SIGNAL_TIE_BREAK = (
    ReviewSignalType.MISMATCH,
    ReviewSignalType.NO_BASIS,
    ReviewSignalType.UNCLEAR,
    ReviewSignalType.MISSING,
    ReviewSignalType.NEEDS_CHECK,
)


@dataclass(frozen=True)
class DashboardRecord:
    total: int
    signing: int
    in_progress: int
    completed: int
    expiring_soon: int
    unresolved_signals: int
    adjustment_requested_clauses: int
    adjustment_agreed_clauses: int
    adjustment_rejected_clauses: int
    obligation_pending: int
    obligation_submitted: int
    obligation_approved: int
    total_committed: int
    payment_condition_met_amount: int
    most_common_signal: ReviewSignalType | None


class DashboardRepository(Protocol):
    async def get_dashboard(
        self,
        *,
        owner_id: UUID,
        today: date,
    ) -> DashboardRecord: ...
