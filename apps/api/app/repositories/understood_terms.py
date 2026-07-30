from typing import Protocol
from uuid import UUID

from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermInput


class UnderstoodTermRepository(Protocol):
    async def save_understood_term_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: UnderstoodTermInput,
    ) -> UnderstoodTerm | None: ...
