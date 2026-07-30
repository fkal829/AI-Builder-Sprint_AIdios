from uuid import UUID

from app.core.exceptions import ResourceNotFound
from app.repositories.understood_terms import UnderstoodTermRepository
from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermInput


class UnderstoodTermService:
    def __init__(self, *, repository: UnderstoodTermRepository) -> None:
        self.repository = repository

    async def save(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: UnderstoodTermInput,
    ) -> UnderstoodTerm:
        saved = await self.repository.save_understood_term_with_audit(
            owner_id=owner_id,
            contract_id=contract_id,
            payload=payload,
        )
        if saved is None:
            raise ResourceNotFound()
        return saved
