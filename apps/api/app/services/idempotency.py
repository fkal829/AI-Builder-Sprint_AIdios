import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import IdempotencyOperation
from app.core.exceptions import IdempotencyConflict
from app.repositories.idempotency import IdempotencyRecord, IdempotencyRepository

ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True)
class IdempotentOutcome[ResponseT]:
    status_code: int
    response: ResponseT
    replay_payload: dict[str, Any]


@dataclass(frozen=True)
class IdempotentResult[ResponseT]:
    status_code: int
    response: ResponseT
    replayed: bool


class IdempotencyService:
    """Atomically reserve an operation and replay a safe persisted result."""

    def __init__(
        self,
        repository: IdempotencyRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_payload: Any,
        perform: Callable[[], Awaitable[IdempotentOutcome[ResponseT]]],
        replay: Callable[[dict[str, Any]], ResponseT],
    ) -> IdempotentResult[ResponseT]:
        request_hash = request_fingerprint(request_payload)
        claim = await self._repository.claim_idempotency(
            owner_id=owner_id,
            operation=operation,
            resource_id=resource_id,
            key=key,
            request_hash=request_hash,
            created_at=_as_utc(self._now()),
        )
        if claim.outcome == "CONFLICT":
            raise IdempotencyConflict()
        if claim.outcome == "REPLAY":
            return _replay(claim.record, request_hash=request_hash, replay=replay)
        if claim.outcome == "PENDING":
            return await self._wait_for_replay(
                owner_id=owner_id,
                operation=operation,
                resource_id=resource_id,
                key=key,
                request_hash=request_hash,
                replay=replay,
            )

        try:
            outcome = await perform()
            _ensure_safe_replay_payload(outcome.replay_payload)
            await self._repository.complete_idempotency(
                owner_id=owner_id,
                operation=operation,
                resource_id=resource_id,
                key=key,
                request_hash=request_hash,
                response_status=outcome.status_code,
                response_payload=outcome.replay_payload,
            )
        except Exception:
            await self._repository.abandon_idempotency(
                owner_id=owner_id,
                operation=operation,
                resource_id=resource_id,
                key=key,
                request_hash=request_hash,
            )
            raise
        return IdempotentResult(
            status_code=outcome.status_code,
            response=outcome.response,
            replayed=False,
        )

    async def _wait_for_replay(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_hash: str,
        replay: Callable[[dict[str, Any]], ResponseT],
    ) -> IdempotentResult[ResponseT]:
        for _ in range(100):
            await asyncio.sleep(0.02)
            record = await self._repository.get_idempotency(
                owner_id=owner_id,
                operation=operation,
                resource_id=resource_id,
                key=key,
            )
            if record is None:
                break
            if record.request_hash != request_hash:
                raise IdempotencyConflict()
            if record.response_status is not None:
                return _replay(record, request_hash=request_hash, replay=replay)
        raise RuntimeError("The original idempotent request did not complete in time.")


def request_fingerprint(payload: Any) -> str:
    """Hash a canonical JSON request without retaining its original contents."""

    encoded = json.dumps(
        _json_normalize(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_normalize(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_normalize(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_normalize(item) for item in value]
    if isinstance(value, UUID | date | datetime | Enum):
        return str(value.value if isinstance(value, Enum) else value)
    return value


def _ensure_safe_replay_payload(payload: dict[str, Any]) -> None:
    forbidden = {"token", "public_token", "public_url", "signing_url"}
    _ensure_safe_replay_value(payload, forbidden=forbidden)


def _ensure_safe_replay_value(value: Any, *, forbidden: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in forbidden:
                raise ValueError(
                    "Raw public tokens and URLs cannot be stored for idempotency replay."
                )
            _ensure_safe_replay_value(item, forbidden=forbidden)
    elif isinstance(value, list):
        for item in value:
            _ensure_safe_replay_value(item, forbidden=forbidden)


def _replay[ResponseT](
    record: IdempotencyRecord | None,
    *,
    request_hash: str,
    replay: Callable[[dict[str, Any]], ResponseT],
) -> IdempotentResult[ResponseT]:
    if (
        record is None
        or record.request_hash != request_hash
        or record.response_status is None
        or record.response_payload is None
    ):
        raise IdempotencyConflict()
    return IdempotentResult(
        status_code=record.response_status,
        response=replay(record.response_payload),
        replayed=True,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Idempotency timestamps must be timezone-aware.")
    return value.astimezone(UTC)
