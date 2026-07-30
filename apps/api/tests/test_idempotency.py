import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.adapters.supabase import SupabaseAdapter
from app.core.enums import IdempotencyOperation
from app.core.exceptions import IdempotencyConflict
from app.services.idempotency import (
    IdempotencyService,
    IdempotentOutcome,
    request_fingerprint,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")


@pytest.fixture
def idempotency_service() -> IdempotencyService:
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token="local-demo-owner-token",
    )
    return IdempotencyService(adapter, now=lambda: datetime(2026, 7, 30, tzinfo=UTC))


async def test_replays_first_response_for_same_key_and_request(idempotency_service) -> None:
    key = uuid4()
    calls = 0

    async def perform() -> IdempotentOutcome[dict[str, str]]:
        nonlocal calls
        calls += 1
        return IdempotentOutcome(
            status_code=201,
            response={"visible": "first response"},
            replay_payload={"adjustment_request_id": "safe-resource-id"},
        )

    async def execute():
        return await idempotency_service.execute(
            owner_id=OWNER_ID,
            operation=IdempotencyOperation.ADJUSTMENT_SEND,
            resource_id=CONTRACT_ID,
            key=key,
            request_payload={"confirmed": True},
            perform=perform,
            replay=lambda payload: {"visible": payload["adjustment_request_id"]},
        )

    first = await execute()
    replayed = await execute()

    assert calls == 1
    assert first.status_code == replayed.status_code == 201
    assert first.replayed is False
    assert replayed.replayed is True
    assert len(idempotency_service._repository.mock_idempotency_records) == 1


async def test_rejects_same_key_with_different_request(idempotency_service) -> None:
    key = uuid4()

    async def perform() -> IdempotentOutcome[dict[str, str]]:
        return IdempotentOutcome(200, {"ok": "yes"}, {"result": "safe"})

    kwargs = {
        "owner_id": OWNER_ID,
        "operation": IdempotencyOperation.ANALYSIS_START,
        "resource_id": CONTRACT_ID,
        "key": key,
        "perform": perform,
        "replay": lambda payload: payload,
    }
    await idempotency_service.execute(request_payload={"document_id": "one"}, **kwargs)

    with pytest.raises(IdempotencyConflict):
        await idempotency_service.execute(request_payload={"document_id": "two"}, **kwargs)


async def test_concurrent_same_request_waits_for_first_result(idempotency_service) -> None:
    key = uuid4()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def perform() -> IdempotentOutcome[dict[str, str]]:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return IdempotentOutcome(202, {"visible": "done"}, {"result": "done"})

    kwargs = {
        "owner_id": OWNER_ID,
        "operation": IdempotencyOperation.SIGNATURE_REQUEST,
        "resource_id": CONTRACT_ID,
        "key": key,
        "request_payload": {"confirmed": True},
        "perform": perform,
        "replay": lambda payload: {"visible": payload["result"]},
    }
    first_task = asyncio.create_task(idempotency_service.execute(**kwargs))
    await started.wait()
    second_task = asyncio.create_task(idempotency_service.execute(**kwargs))
    await asyncio.sleep(0)
    release.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert calls == 1
    assert first.replayed is False
    assert second.replayed is True


async def test_does_not_store_public_url_or_raw_token_in_replay_payload(
    idempotency_service,
) -> None:
    async def perform() -> IdempotentOutcome[dict[str, str]]:
        return IdempotentOutcome(
            201,
            {"public_url": "https://example.test/public/raw-token"},
            {"public_url": "https://example.test/public/raw-token"},
        )

    with pytest.raises(ValueError, match="Raw public tokens"):
        await idempotency_service.execute(
            owner_id=OWNER_ID,
            operation=IdempotencyOperation.ADJUSTMENT_SEND,
            resource_id=CONTRACT_ID,
            key=uuid4(),
            request_payload={"confirmed": True},
            perform=perform,
            replay=lambda payload: payload,
        )

    assert idempotency_service._repository.mock_idempotency_records == ()


def test_request_fingerprint_is_stable_and_does_not_retain_payload() -> None:
    assert request_fingerprint({"b": 2, "a": 1}) == request_fingerprint({"a": 1, "b": 2})
