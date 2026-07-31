import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.adapters.supabase import SupabaseAdapter
from app.core.enums import IdempotencyOperation
from app.core.exceptions import ExternalStorageFailure, IdempotencyConflict
from app.services.idempotency import (
    IdempotencyService,
    IdempotentOutcome,
    request_fingerprint,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
RECOVERABLE_COMPLETION_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260730330000_make_idempotency_completion_recoverable.sql"
)


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

    records = idempotency_service._repository.mock_idempotency_records
    assert len(records) == 1
    assert records[0].response_status is None
    assert records[0].response_payload is None


async def test_persists_and_replays_an_explicit_failure_outcome(
    idempotency_service,
) -> None:
    key = uuid4()
    calls = 0

    async def perform() -> IdempotentOutcome[dict[str, object]]:
        nonlocal calls
        calls += 1
        raise ExternalStorageFailure("admission failed")

    def failure_outcome(error: Exception):
        if not isinstance(error, ExternalStorageFailure):
            return None
        return IdempotentOutcome(
            status_code=503,
            response={"data": None, "error": {"code": "ANALYSIS_START_FAILED"}},
            replay_payload={
                "data": None,
                "error": {"code": "ANALYSIS_START_FAILED"},
            },
        )

    async def execute():
        return await idempotency_service.execute(
            owner_id=OWNER_ID,
            operation=IdempotencyOperation.ANALYSIS_START,
            resource_id=CONTRACT_ID,
            key=key,
            request_payload={"document_id": "same"},
            perform=perform,
            replay=lambda payload: payload,
            exception_outcome=failure_outcome,
        )

    first = await execute()
    replay = await execute()

    assert calls == 1
    assert first.status_code == replay.status_code == 503
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.response["error"]["code"] == "ANALYSIS_START_FAILED"


async def test_retries_replay_completion_after_transient_storage_failure(
    idempotency_service,
    monkeypatch,
) -> None:
    repository = idempotency_service._repository
    original = repository.complete_idempotency
    completion_calls = 0

    async def flaky_complete(**kwargs):
        nonlocal completion_calls
        completion_calls += 1
        if completion_calls == 1:
            raise ExternalStorageFailure("temporary failure")
        return await original(**kwargs)

    monkeypatch.setattr(repository, "complete_idempotency", flaky_complete)
    idempotency_service._completion_retry_delay_seconds = 0

    result = await idempotency_service.execute(
        owner_id=OWNER_ID,
        operation=IdempotencyOperation.ANALYSIS_START,
        resource_id=CONTRACT_ID,
        key=uuid4(),
        request_payload={"document_id": "same"},
        perform=lambda: _successful_outcome(),
        replay=lambda payload: payload,
    )

    assert result.status_code == 202
    assert completion_calls == 2


async def test_does_not_abandon_after_business_outcome_when_completion_fails(
    idempotency_service,
    monkeypatch,
) -> None:
    repository = idempotency_service._repository

    async def always_fails(**_kwargs):
        raise ExternalStorageFailure("persistent failure")

    monkeypatch.setattr(repository, "complete_idempotency", always_fails)
    idempotency_service._completion_attempts = 1

    with pytest.raises(ExternalStorageFailure, match="persistent failure"):
        await idempotency_service.execute(
            owner_id=OWNER_ID,
            operation=IdempotencyOperation.ANALYSIS_START,
            resource_id=CONTRACT_ID,
            key=uuid4(),
            request_payload={"document_id": "same"},
            perform=lambda: _successful_outcome(),
            replay=lambda payload: payload,
        )

    records = repository.mock_idempotency_records
    assert len(records) == 1
    assert records[0].response_status is None
    assert records[0].response_payload is None


async def test_pending_reservation_times_out_as_api_conflict(
    idempotency_service,
) -> None:
    repository = idempotency_service._repository
    key = uuid4()
    request_payload = {"document_id": "same"}
    await repository.claim_idempotency(
        owner_id=OWNER_ID,
        operation=IdempotencyOperation.ANALYSIS_START,
        resource_id=CONTRACT_ID,
        key=key,
        request_hash=request_fingerprint(request_payload),
        created_at=datetime.now(UTC),
    )
    service = IdempotencyService(
        repository,
        pending_replay_attempts=1,
        pending_replay_delay_seconds=0,
    )

    with pytest.raises(IdempotencyConflict):
        await service.execute(
            owner_id=OWNER_ID,
            operation=IdempotencyOperation.ANALYSIS_START,
            resource_id=CONTRACT_ID,
            key=key,
            request_payload=request_payload,
            perform=lambda: _successful_outcome(),
            replay=lambda payload: payload,
        )


def test_request_fingerprint_is_stable_and_does_not_retain_payload() -> None:
    assert request_fingerprint({"b": 2, "a": 1}) == request_fingerprint({"a": 1, "b": 2})


def test_completion_migration_is_retry_safe_without_overwriting_first_result() -> None:
    sql = RECOVERABLE_COMPLETION_MIGRATION.read_text(encoding="utf-8").lower()

    assert "for update" in sql
    assert "response_payload is not distinct from p_response_payload" in sql
    assert "completed idempotency response cannot be changed" in sql


async def _successful_outcome() -> IdempotentOutcome[dict[str, str]]:
    return IdempotentOutcome(
        status_code=202,
        response={"result": "queued"},
        replay_payload={"result": "queued"},
    )
