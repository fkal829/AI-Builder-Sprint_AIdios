from collections.abc import Sequence
from uuid import UUID

from app.core.exceptions import ResourceNotFound
from app.repositories.obligations import ObligationRecord, ObligationRepository
from app.schemas.obligations import Obligation


class ObligationService:
    def __init__(self, repository: ObligationRepository) -> None:
        self._repository = repository

    async def list(self, *, owner_id: UUID, contract_id: UUID) -> Sequence[Obligation]:
        records = await self._repository.list_owned_obligations(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if records is None:
            raise ResourceNotFound()
        return [
            _obligation_from_record(record)
            for record in sorted(records, key=lambda item: (item.due_date, str(item.id)))
        ]


def _obligation_from_record(record: ObligationRecord) -> Obligation:
    return Obligation(
        id=record.id,
        contract_id=record.contract_id,
        title=record.title,
        due_date=record.due_date,
        assignee=record.assignee,
        evidence_type=record.evidence_type,
        source_document_id=record.source_document_id,
        source_page=record.source_page,
        source_text=record.source_text,
        confidence=record.confidence,
        evidence_url=record.evidence_url,
        status=record.status,
        submitted_at=record.submitted_at,
        reviewed_at=record.reviewed_at,
        payment_condition_met=record.payment_condition_met,
    )
