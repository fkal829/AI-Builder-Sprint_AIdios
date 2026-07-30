from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from app.core.enums import IdempotencyOperation

IdempotencyClaimOutcome = Literal["NEW", "REPLAY", "PENDING", "CONFLICT"]


@dataclass(frozen=True)
class IdempotencyRecord:
    owner_id: UUID
    operation: IdempotencyOperation
    resource_id: UUID
    key: UUID
    request_hash: str
    response_status: int | None
    response_payload: dict[str, Any] | None
    created_at: datetime


@dataclass(frozen=True)
class IdempotencyClaim:
    outcome: IdempotencyClaimOutcome
    record: IdempotencyRecord | None


class IdempotencyRepository(Protocol):
    async def claim_idempotency(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_hash: str,
        created_at: datetime,
    ) -> IdempotencyClaim: ...

    async def get_idempotency(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
    ) -> IdempotencyRecord | None: ...

    async def complete_idempotency(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_hash: str,
        response_status: int,
        response_payload: dict[str, Any],
    ) -> IdempotencyRecord: ...

    async def abandon_idempotency(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_hash: str,
    ) -> None: ...
