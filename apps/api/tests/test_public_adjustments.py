from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.solar import SolarCounterproposalError, SolarReviewAdapter
from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import (
    get_counterproposal_comparator,
    get_supabase_adapter,
)
from app.core.enums import (
    AdjustmentRequestStatus,
    AdjustmentResponseDecision,
    ContractStatus,
    ReviewItemStatus,
    SuggestionChoice,
)
from app.main import app
from app.repositories.adjustments import ReviewItemForAdjustment
from app.schemas.adjustments import CounterproposalComparisonInput
from app.services.counterproposal import CounterproposalComparator

OWNER_ID = UUID("00000000-0000-4000-8000-000000000024")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000043")
BEARER_TOKEN = "local-demo-owner-token"


class FailingComparisonAdapter:
    async def compare_counterproposals(
        self,
        *,
        items: list[CounterproposalComparisonInput],
    ):
        raise SolarCounterproposalError(f"failed items={len(items)}")


@pytest.fixture
async def public_adjustment_context():
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )

    async def override_adapter():
        return adapter

    async def override_comparator():
        return CounterproposalComparator(
            SolarReviewAdapter(
                mode="mock",
                api_key="",
                base_url="https://api.upstage.ai",
            )
        )

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_counterproposal_comparator] = override_comparator
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, adapter
    finally:
        app.dependency_overrides.clear()


def owner_headers(*, idempotency_key: UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)
    return headers


async def sent_adjustment(
    client: AsyncClient,
    adapter: SupabaseAdapter,
    *,
    item_count: int = 1,
) -> tuple[UUID, UUID, list[ReviewItemForAdjustment], str]:
    contract_response = await client.post(
        "/api/v1/contracts",
        headers=owner_headers(),
        json={"title": "대행사 공개 응답 계약", "counterparty_name": "부산 대행사"},
    )
    assert contract_response.status_code == 201
    contract_id = UUID(contract_response.json()["data"]["id"])
    adapter._mock_contracts[contract_id] = replace(
        adapter._mock_contracts[contract_id],
        status=ContractStatus.REVIEW_REQUIRED,
    )
    review_items = [
        ReviewItemForAdjustment(
            id=uuid4(),
            contract_id=contract_id,
            status=ReviewItemStatus.SELECTED,
            user_choice=(
                SuggestionChoice.COMPROMISE if index % 2 == 0 else SuggestionChoice.REQUEST
            ),
            suggestion_compromise=f"절충 요청 문구 {index + 1}",
            suggestion_request=f"수정 요청 문구 {index + 1}",
        )
        for index in range(item_count)
    ]
    for item in review_items:
        adapter._mock_review_items[item.id] = item
    draft_response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=owner_headers(idempotency_key=uuid4()),
        json={
            "review_item_ids": [str(item.id) for item in review_items],
            "expires_in_hours": 72,
        },
    )
    assert draft_response.status_code == 201
    adjustment_id = UUID(draft_response.json()["data"]["id"])
    sent_response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_id}/send",
        headers=owner_headers(idempotency_key=uuid4()),
        json={"confirmed": True},
    )
    assert sent_response.status_code == 200
    token = sent_response.json()["data"]["public_url"].rsplit("/", maxsplit=1)[-1]
    return contract_id, adjustment_id, review_items, token


async def test_public_get_is_no_store_and_does_not_record_open(public_adjustment_context) -> None:
    client, adapter = public_adjustment_context
    _contract_id, adjustment_id, review_items, token = await sent_adjustment(client, adapter)

    response = await client.get(f"/api/v1/public/adjustment-requests/{token}")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()["data"]
    assert body["status"] == "SENT"
    assert len(body["items"]) == len(review_items)
    assert str(review_items[0].id) not in response.text
    assert adapter.mock_adjustment_requests[adjustment_id].status == AdjustmentRequestStatus.SENT
    assert not any(event.event_type == "ADJUSTMENT_OPENED" for event in adapter.mock_audit_events)


async def test_first_open_is_recorded_once_and_repeated_open_is_stable(
    public_adjustment_context,
) -> None:
    client, adapter = public_adjustment_context
    _contract_id, adjustment_id, _review_items, token = await sent_adjustment(client, adapter)
    path = f"/api/v1/public/adjustment-requests/{token}/open"

    first = await client.post(path)
    second = await client.post(path)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["Cache-Control"] == "no-store"
    assert first.json()["data"] == second.json()["data"]
    request = adapter.mock_adjustment_requests[adjustment_id]
    assert request.status == AdjustmentRequestStatus.OPENED
    assert request.opened_at is not None
    events = [
        event
        for event in adapter.mock_audit_events
        if event.event_type == "ADJUSTMENT_OPENED"
    ]
    assert len(events) == 1


async def test_response_requires_every_public_item_exactly_once(public_adjustment_context) -> None:
    client, adapter = public_adjustment_context
    _contract_id, adjustment_id, _review_items, token = await sent_adjustment(
        client,
        adapter,
        item_count=2,
    )
    public = await client.get(f"/api/v1/public/adjustment-requests/{token}")
    item_id = public.json()["data"]["items"][0]["item_id"]

    response = await client.post(
        f"/api/v1/public/adjustment-requests/{token}/responses",
        json={
            "responses": [
                {
                    "item_id": item_id,
                    "decision": "ACCEPT",
                    "counter_text": None,
                    "reason": None,
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert adapter.mock_adjustment_requests[adjustment_id].status == AdjustmentRequestStatus.SENT
    assert not adapter.mock_adjustment_responses


async def test_expired_public_token_is_rejected_without_leaking_request(
    public_adjustment_context,
) -> None:
    client, adapter = public_adjustment_context
    _contract_id, _adjustment_id, _review_items, token = await sent_adjustment(client, adapter)
    token_hash = next(iter(adapter._mock_public_tokens))
    adapter._mock_public_tokens[token_hash] = replace(
        adapter._mock_public_tokens[token_hash],
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    response = await client.get(f"/api/v1/public/adjustment-requests/{token}")

    assert response.status_code == 410
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "ADJUSTMENT_LINK_EXPIRED"


async def test_direct_response_sets_opened_and_responded_and_updates_owner_detail(
    public_adjustment_context,
) -> None:
    client, adapter = public_adjustment_context
    contract_id, adjustment_id, review_items, token = await sent_adjustment(
        client,
        adapter,
        item_count=2,
    )
    public = await client.get(f"/api/v1/public/adjustment-requests/{token}")
    public_items = public.json()["data"]["items"]
    response = await client.post(
        f"/api/v1/public/adjustment-requests/{token}/responses",
        json={
            "responses": [
                {
                    "item_id": public_items[0]["item_id"],
                    "decision": "ACCEPT",
                    "counter_text": None,
                    "reason": None,
                },
                {
                    "item_id": public_items[1]["item_id"],
                    "decision": "COUNTER",
                    "counter_text": "월 보고서 제공을 전제로 위약금을 10%로 조정하겠습니다.",
                    "reason": "운영 일정과 제작 비용을 고려해야 합니다.",
                },
            ]
        },
    )

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"] == {"submitted": True}
    request = adapter.mock_adjustment_requests[adjustment_id]
    assert request.status == AdjustmentRequestStatus.RESPONDED
    assert request.opened_at == request.responded_at
    assert [item.decision for item in adapter.mock_adjustment_responses[adjustment_id]] == [
        AdjustmentResponseDecision.ACCEPT,
        AdjustmentResponseDecision.COUNTER,
    ]
    assert [
        event.event_type for event in adapter.mock_audit_events if event.contract_id == contract_id
    ][-1] == "ADJUSTMENT_RESPONDED"

    detail = await client.get(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_id}",
        headers=owner_headers(),
    )
    assert detail.status_code == 200
    detail_body = detail.json()["data"]
    assert [item["review_item_id"] for item in detail_body["responses"]] == [
        str(item.id) for item in review_items
    ]
    assert detail_body["comparisons"][0]["remaining_checks"] == []
    counter_comparison = detail_body["comparisons"][1]
    assert "수정 요청 문구 2" in counter_comparison["changed_summary"]
    assert "월 보고서 제공을 전제로 위약금을 10%로 조정" in counter_comparison[
        "changed_summary"
    ]
    assert "운영 일정과 제작 비용" in counter_comparison["remaining_checks"][0]
    assert counter_comparison["changed_summary"] != "대행사가 역제안을 제시했습니다."

    repeat = await client.post(
        f"/api/v1/public/adjustment-requests/{token}/responses",
        json={
            "responses": [
                {
                    "item_id": public_items[0]["item_id"],
                    "decision": "ACCEPT",
                    "counter_text": None,
                    "reason": None,
                },
                {
                    "item_id": public_items[1]["item_id"],
                    "decision": "COUNTER",
                    "counter_text": "다른 문구",
                    "reason": "다른 사유",
                },
            ]
        },
    )
    assert repeat.status_code == 409
    assert repeat.headers["Cache-Control"] == "no-store"
    assert len(adapter.mock_adjustment_responses[adjustment_id]) == 2


async def test_comparison_failure_keeps_persisted_agency_response(
    public_adjustment_context,
) -> None:
    client, adapter = public_adjustment_context
    contract_id, adjustment_id, _review_items, token = await sent_adjustment(
        client,
        adapter,
    )
    public = await client.get(f"/api/v1/public/adjustment-requests/{token}")
    item_id = public.json()["data"]["items"][0]["item_id"]
    submitted = await client.post(
        f"/api/v1/public/adjustment-requests/{token}/responses",
        json={
            "responses": [
                {
                    "item_id": item_id,
                    "decision": "COUNTER",
                    "counter_text": "위약금을 10%로 조정하겠습니다.",
                    "reason": "제작비가 이미 집행되었습니다.",
                }
            ]
        },
    )
    assert submitted.status_code == 201

    async def override_failing_comparator():
        return CounterproposalComparator(FailingComparisonAdapter())

    app.dependency_overrides[
        get_counterproposal_comparator
    ] = override_failing_comparator
    detail = await client.get(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_id}",
        headers=owner_headers(),
    )

    assert detail.status_code == 502
    assert detail.json()["error"]["code"] == "ANALYSIS_SCHEMA_INVALID"
    assert len(adapter.mock_adjustment_responses[adjustment_id]) == 1
    persisted = adapter.mock_adjustment_responses[adjustment_id][0]
    assert persisted.counter_text == "위약금을 10%로 조정하겠습니다."
    assert persisted.reason == "제작비가 이미 집행되었습니다."
