from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from app.core.enums import ContractStatus, ObligationStatus, ReviewItemStatus, ReviewSignalType
from app.repositories.dashboard import DashboardRepository, DashboardReviewItem
from app.schemas.dashboard import Dashboard
from app.services.contracts import SEOUL, contract_d_days

_IN_PROGRESS_STATUSES = {ContractStatus.IN_PROGRESS, ContractStatus.RENEWAL_DUE}
_COMMITTED_STATUSES = {
    ContractStatus.SIGNED,
    ContractStatus.IN_PROGRESS,
    ContractStatus.RENEWAL_DUE,
    ContractStatus.COMPLETED,
}
_UNRESOLVED_REVIEW_STATUSES = {
    ReviewItemStatus.UNREVIEWED,
    ReviewItemStatus.SELECTED,
    ReviewItemStatus.SENT,
}
_SIGNAL_TIE_BREAK_ORDER = list(ReviewSignalType)


class DashboardService:
    """C-10 read-only aggregation across contracts, obligations, and review items."""

    def __init__(
        self,
        *,
        repository: DashboardRepository,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    async def get(self, *, owner_id: UUID) -> Dashboard:
        today = self._now().astimezone(SEOUL).date()
        contracts = await self._repository.list(owner_id=owner_id)
        contract_by_id = {record.id: record for record in contracts}

        expiring_soon = 0
        total_committed = 0
        for record in contracts:
            expiry_d_day, termination_notice_d_day, auto_renewal_d_day = contract_d_days(
                record, today=today
            )
            if any(
                d_day is not None and 0 <= d_day <= upper_bound
                for d_day, upper_bound in (
                    (expiry_d_day, 30),
                    (termination_notice_d_day, 14),
                    (auto_renewal_d_day, 7),
                )
            ):
                expiring_soon += 1
            if record.status in _COMMITTED_STATUSES and record.total_amount is not None:
                total_committed += record.total_amount

        obligations = await self._repository.list_dashboard_obligations(owner_id=owner_id)
        obligation_pending = 0
        obligation_submitted = 0
        obligation_approved = 0
        payment_condition_met_amount = 0
        for obligation in obligations:
            if obligation.status == ObligationStatus.PENDING:
                obligation_pending += 1
            elif obligation.status == ObligationStatus.SUBMITTED:
                obligation_submitted += 1
            elif obligation.status == ObligationStatus.APPROVED:
                obligation_approved += 1
                contract = contract_by_id.get(obligation.contract_id)
                if contract is not None and contract.total_amount is not None:
                    payment_condition_met_amount += contract.total_amount

        review_items = await self._repository.list_dashboard_review_items(owner_id=owner_id)
        adjustment_agreed_clauses = 0
        adjustment_rejected_clauses = 0
        unresolved: list[DashboardReviewItem] = []
        for item in review_items:
            if item.status == ReviewItemStatus.RESOLVED:
                adjustment_agreed_clauses += 1
            elif item.status == ReviewItemStatus.KEPT_ORIGINAL:
                adjustment_rejected_clauses += 1
            if item.status in _UNRESOLVED_REVIEW_STATUSES:
                unresolved.append(item)

        item_counts = await self._repository.list_dashboard_adjustment_request_item_counts(
            owner_id=owner_id
        )

        return Dashboard(
            total=len(contracts),
            signing=sum(1 for r in contracts if r.status == ContractStatus.SIGNING),
            in_progress=sum(1 for r in contracts if r.status in _IN_PROGRESS_STATUSES),
            completed=sum(1 for r in contracts if r.status == ContractStatus.COMPLETED),
            expiring_soon=expiring_soon,
            unresolved_signals=len(unresolved),
            adjustment_requested_clauses=sum(item_counts),
            adjustment_agreed_clauses=adjustment_agreed_clauses,
            adjustment_rejected_clauses=adjustment_rejected_clauses,
            obligation_pending=obligation_pending,
            obligation_submitted=obligation_submitted,
            obligation_approved=obligation_approved,
            total_committed=total_committed,
            payment_condition_met_amount=payment_condition_met_amount,
            most_common_signal=_most_common_signal(unresolved),
        )


def _most_common_signal(items: Sequence[DashboardReviewItem]) -> ReviewSignalType | None:
    if not items:
        return None
    counts = Counter(item.type for item in items)
    return min(counts, key=lambda signal: (-counts[signal], _SIGNAL_TIE_BREAK_ORDER.index(signal)))
