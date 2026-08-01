from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.core.enums import ContractStatus
from app.core.exceptions import ResourceNotFound
from app.repositories.contracts import (
    ContractDeleteOutcome,
    ContractRecord,
    ContractRepository,
    RenewalDecisionSaveOutcome,
)
from app.schemas.contracts import (
    AuditEvent,
    Contract,
    ContractCreate,
    ContractDeletion,
    ContractListItem,
    RenewalDecision,
    RenewalDecisionRequest,
)
from app.services.signature_reconciliation import SignatureReconciler
from app.services.state_machine import InvalidStatusTransition

# Korea has no daylight saving time.  A fixed offset keeps Asia/Seoul date
# calculations available in minimal Windows environments without tzdata.
SEOUL = timezone(timedelta(hours=9), name="Asia/Seoul")

# A contract can only have a pending, non-terminal signature while it sits in
# one of these statuses (see supabase/migrations/*_add_modusign_webhook_reconciliation.sql).
_SIGNATURE_PENDING_STATUSES = (ContractStatus.READY_TO_SIGN, ContractStatus.SIGNING)


class ContractService:
    """C-2 contract queries and creation, isolated from HTTP and Supabase."""

    def __init__(
        self,
        repository: ContractRepository,
        *,
        signatures: SignatureReconciler | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._signatures = signatures
        self._now = now or (lambda: datetime.now(UTC))

    async def create(self, *, owner_id: UUID, payload: ContractCreate) -> Contract:
        created_at = self._now()
        record = ContractRecord(
            id=uuid4(),
            owner_id=owner_id,
            title=payload.title,
            counterparty_name=payload.counterparty_name,
            status=ContractStatus.DRAFT,
            signed_date=None,
            start_date=None,
            end_date=None,
            termination_notice_date=None,
            renewal_type=None,
            total_amount=None,
            understood_term=None,
            renewal_decision=None,
            modusign_document_id=None,
            created_at=created_at,
            updated_at=created_at,
        )
        saved = await self._repository.create(owner_id=owner_id, payload=payload, record=record)
        return _contract_from_record(saved)

    async def list(self, *, owner_id: UUID) -> Sequence[ContractListItem]:
        today = self._now().astimezone(SEOUL).date()
        records = await self._repository.list(owner_id=owner_id)
        records = await self._with_reconciled_signatures(owner_id=owner_id, records=records)
        ordered = sorted(
            records,
            key=lambda item: (item.end_date is None, item.end_date, str(item.id)),
        )
        return [_list_item_from_record(record, today=today) for record in ordered]

    async def _with_reconciled_signatures(
        self, *, owner_id: UUID, records: Sequence[ContractRecord]
    ) -> Sequence[ContractRecord]:
        """A contract stuck at READY_TO_SIGN/SIGNING may only be stale because
        Modusign's webhook (C-8) never reached this server. Reconciling every
        pending signature here means simply reloading the contract list shows
        the true signing state, without visiting that contract's signature page.
        """
        if self._signatures is None:
            return records
        pending_ids = [
            record.id for record in records if record.status in _SIGNATURE_PENDING_STATUSES
        ]
        if not pending_ids:
            return records
        for contract_id in pending_ids:
            await self._signatures.reconcile_owned(owner_id=owner_id, contract_id=contract_id)
        refreshed = {
            record.id: record for record in await self._repository.list(owner_id=owner_id)
        }
        return [refreshed.get(record.id, record) for record in records]

    async def get(self, *, owner_id: UUID, contract_id: UUID) -> Contract:
        record = await self._repository.get(owner_id=owner_id, contract_id=contract_id)
        if record is None:
            raise ResourceNotFound()
        return _contract_from_record(record)

    async def delete(self, *, owner_id: UUID, contract_id: UUID) -> ContractDeletion:
        outcome = await self._repository.delete_discardable(
            owner_id=owner_id,
            contract_id=contract_id,
            deleted_at=self._utc_now(),
        )
        if outcome is ContractDeleteOutcome.NOT_FOUND:
            raise ResourceNotFound()
        if outcome is ContractDeleteOutcome.PROTECTED:
            raise InvalidStatusTransition(
                "조정 요청을 발송했거나 서명 단계가 시작된 계약은 삭제할 수 없습니다."
            )
        return ContractDeletion(contract_id=contract_id)

    async def timeline(self, *, owner_id: UUID, contract_id: UUID) -> Sequence[AuditEvent]:
        events = await self._repository.list_audit_events(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if events is None:
            raise ResourceNotFound()
        return [
            AuditEvent(
                id=event.id,
                event_type=event.event_type,
                actor_type=event.actor_type,
                summary=event.summary,
                created_at=event.created_at,
            )
            for event in sorted(events, key=lambda item: (item.created_at, str(item.id)))
        ]

    async def save_renewal_decision(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: RenewalDecisionRequest,
    ) -> RenewalDecision:
        record = await self._repository.get(owner_id=owner_id, contract_id=contract_id)
        if record is None:
            raise ResourceNotFound()
        decided_at = self._utc_now()
        today = decided_at.astimezone(SEOUL).date()
        if not _is_renewal_review_window(record, today=today):
            raise InvalidStatusTransition(
                "현재 계약은 재계약 의사를 저장할 수 있는 기간이 아닙니다."
            )

        result = await self._repository.save_renewal_decision_with_audit(
            owner_id=owner_id,
            contract_id=contract_id,
            decision=payload.decision,
            today=today,
            decided_at=decided_at,
        )
        if result.outcome == RenewalDecisionSaveOutcome.NOT_FOUND:
            raise ResourceNotFound()
        if result.outcome == RenewalDecisionSaveOutcome.OUTSIDE_REVIEW_WINDOW:
            raise InvalidStatusTransition(
                "현재 계약은 재계약 의사를 저장할 수 있는 기간이 아닙니다."
            )
        if result.decision is None:
            raise RuntimeError("재계약 의사 저장 결과가 없습니다.")
        return result.decision

    def _utc_now(self) -> datetime:
        now = self._now()
        if now.tzinfo is None:
            raise ValueError("Contract timestamps must be timezone-aware.")
        return now.astimezone(UTC)


def _contract_from_record(record: ContractRecord) -> Contract:
    return Contract(
        id=record.id,
        title=record.title,
        counterparty_name=record.counterparty_name,
        status=record.status,
        signed_date=record.signed_date,
        start_date=record.start_date,
        end_date=record.end_date,
        termination_notice_date=record.termination_notice_date,
        renewal_type=record.renewal_type,
        total_amount=record.total_amount,
        understood_term=record.understood_term,
        renewal_decision=record.renewal_decision,
        modusign_document_id=record.modusign_document_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def contract_d_days(
    record: ContractRecord, *, today: date
) -> tuple[int | None, int | None, int | None]:
    """Return (expiry, termination-notice, auto-renewal) D-day counts.

    Shared by list rendering, the C-9 renewal review window, and C-10's
    dashboard so the D-30/D-14/D-7 boundaries stay identical everywhere.
    """
    expiry_d_day = (record.end_date - today).days if record.end_date else None
    termination_notice_d_day = (
        (record.termination_notice_date - today).days
        if record.termination_notice_date
        else None
    )
    auto_renewal_d_day = (
        expiry_d_day if record.renewal_type == "AUTO" and record.end_date else None
    )
    return expiry_d_day, termination_notice_d_day, auto_renewal_d_day


def _list_item_from_record(record: ContractRecord, *, today: date) -> ContractListItem:
    expiry_d_day, termination_notice_d_day, auto_renewal_d_day = contract_d_days(
        record, today=today
    )
    return ContractListItem(
        id=record.id,
        title=record.title,
        counterparty_name=record.counterparty_name,
        status=record.status,
        total_amount=record.total_amount,
        end_date=record.end_date,
        expiry_d_day=expiry_d_day,
        termination_notice_d_day=termination_notice_d_day,
        auto_renewal_d_day=auto_renewal_d_day,
    )


def _is_renewal_review_window(record: ContractRecord, *, today: date) -> bool:
    expiry_d_day, termination_notice_d_day, auto_renewal_d_day = contract_d_days(
        record, today=today
    )
    return any(
        d_day is not None and 0 <= d_day <= upper_bound
        for d_day, upper_bound in (
            (expiry_d_day, 30),
            (termination_notice_d_day, 14),
            (auto_renewal_d_day, 7),
        )
    )
