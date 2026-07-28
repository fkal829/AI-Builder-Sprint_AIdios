from typing import Protocol
from uuid import UUID

from app.schemas.contracts import ContractCreate, ContractSummary


class ContractRepository(Protocol):
    async def create(
        self,
        *,
        owner_id: UUID,
        payload: ContractCreate,
    ) -> ContractSummary: ...

    async def get(self, *, owner_id: UUID, contract_id: UUID) -> ContractSummary | None: ...
