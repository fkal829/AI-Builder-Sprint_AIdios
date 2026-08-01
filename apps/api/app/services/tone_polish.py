from uuid import UUID

from app.adapters.solar import SolarReviewAdapter, SolarTonePolishError
from app.core.exceptions import ResourceNotFound, TonePolishUnavailable
from app.repositories.contracts import ContractRepository
from app.schemas.adjustments import AdjustmentCopyPolishRequest, AdjustmentCopyPolishResult


class TonePolishService:
    """Owner-scoped, non-persistent orchestration for adjustment copy polishing."""

    def __init__(
        self,
        *,
        repository: ContractRepository,
        polisher: SolarReviewAdapter,
    ) -> None:
        self._repository = repository
        self._polisher = polisher

    async def polish(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: AdjustmentCopyPolishRequest,
    ) -> AdjustmentCopyPolishResult:
        contract = await self._repository.get(owner_id=owner_id, contract_id=contract_id)
        if contract is None:
            raise ResourceNotFound()
        try:
            return await self._polisher.polish_adjustment_copy(text=payload.text)
        except SolarTonePolishError as error:
            raise TonePolishUnavailable() from error
