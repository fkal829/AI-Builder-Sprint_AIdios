from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.core.enums import ContractStatus
from app.core.exceptions import ResourceNotFound
from app.repositories.contracts import ContractRecord, ContractRepository
from app.schemas.contracts import AuditEvent, Contract, ContractCreate, ContractListItem

# Korea has no daylight saving time.  A fixed offset keeps Asia/Seoul date
# calculations available in minimal Windows environments without tzdata.
SEOUL = timezone(timedelta(hours=9), name="Asia/Seoul")


class ContractService:
    """C-2 contract queries and creation, isolated from HTTP and Supabase."""

    def __init__(
        self,
        repository: ContractRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
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
        ordered = sorted(
            records,
            key=lambda item: (item.end_date is None, item.end_date, str(item.id)),
        )
        return [_list_item_from_record(record, today=today) for record in ordered]

    async def get(self, *, owner_id: UUID, contract_id: UUID) -> Contract:
        record = await self._repository.get(owner_id=owner_id, contract_id=contract_id)
        if record is None:
            raise ResourceNotFound()
        return _contract_from_record(record)

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


def _list_item_from_record(record: ContractRecord, *, today: date) -> ContractListItem:
    expiry_d_day = (record.end_date - today).days if record.end_date else None
    termination_notice_d_day = (
        (record.termination_notice_date - today).days
        if record.termination_notice_date
        else None
    )
    auto_renewal_d_day = (
        expiry_d_day if record.renewal_type == "AUTO" and record.end_date else None
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
