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
        completion_attempts: int = 3,
        completion_retry_delay_seconds: float = 0.05,
        pending_replay_attempts: int = 100,
        pending_replay_delay_seconds: float = 0.02,
    ) -> None:
        if completion_attempts < 1:
            raise ValueError("Idempotency completion attempts must be positive.")
        if completion_retry_delay_seconds < 0:
            raise ValueError("Idempotency retry delay cannot be negative.")
        if pending_replay_attempts < 1:
            raise ValueError("Idempotency pending replay attempts must be positive.")
        if pending_replay_delay_seconds < 0:
            raise ValueError("Idempotency pending replay delay cannot be negative.")
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))
        self._completion_attempts = completion_attempts
        self._completion_retry_delay_seconds = completion_retry_delay_seconds
        self._pending_replay_attempts = pending_replay_attempts
        self._pending_replay_delay_seconds = pending_replay_delay_seconds

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
        exception_outcome: (
            Callable[[Exception], IdempotentOutcome[ResponseT] | None] | None
        ) = None,
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
        except Exception as error:
            outcome = exception_outcome(error) if exception_outcome is not None else None
            if outcome is not None:
                _ensure_safe_replay_payload(outcome.replay_payload)
                await self._complete_with_retry(
                    owner_id=owner_id,
                    operation=operation,
                    resource_id=resource_id,
                    key=key,
                    request_hash=request_hash,
                    outcome=outcome,
                )
                return IdempotentResult(
                    status_code=outcome.status_code,
                    response=outcome.response,
                    replayed=False,
                )
            await self._repository.abandon_idempotency(
                owner_id=owner_id,
                operation=operation,
                resource_id=resource_id,
                key=key,
                request_hash=request_hash,
            )
            raise

        # Once perform() has returned, it may already have committed a business
        # transaction. Never abandon its reservation if replay persistence fails:
        # deleting it would allow the same key to execute the side effect again.
        _ensure_safe_replay_payload(outcome.replay_payload)
        await self._complete_with_retry(
            owner_id=owner_id,
            operation=operation,
            resource_id=resource_id,
            key=key,
            request_hash=request_hash,
            outcome=outcome,
        )
        return IdempotentResult(
            status_code=outcome.status_code,
            response=outcome.response,
            replayed=False,
        )

    async def _complete_with_retry(
        self,
        *,
        owner_id: UUID,
        operation: IdempotencyOperation,
        resource_id: UUID,
        key: UUID,
        request_hash: str,
        outcome: IdempotentOutcome[Any],
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(self._completion_attempts):
            try:
                await self._repository.complete_idempotency(
                    owner_id=owner_id,
                    operation=operation,
                    resource_id=resource_id,
                    key=key,
                    request_hash=request_hash,
                    response_status=outcome.status_code,
                    response_payload=outcome.replay_payload,
                )
                return
            except Exception as error:
                last_error = error
                if attempt + 1 < self._completion_attempts:
                    await asyncio.sleep(self._completion_retry_delay_seconds)
        assert last_error is not None
        raise last_error

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
        for _ in range(self._pending_replay_attempts):
            await asyncio.sleep(self._pending_replay_delay_seconds)
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
        raise IdempotencyConflict("같은 멱등 요청이 아직 처리 중입니다.")


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
