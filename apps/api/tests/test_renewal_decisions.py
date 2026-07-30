from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_contract_service, get_supabase_adapter
from app.core.enums import (
    AdjustmentRequestStatus,
    AdjustmentResponseDecision,
    ContractStatus,
    RenewalDecisionType,
    ReviewItemStatus,
    SuggestionChoice,
)
from app.main import app
from app.repositories.adjustments import (
    AdjustmentRequestItemRecord,
    AdjustmentRequestRecord,
    AdjustmentResponseRecord,
    ReviewItemForAdjustment,
)
from app.repositories.contracts import RenewalDecisionSaveOutcome
from app.services.contracts import ContractService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
FIXED_NOW = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)
TODAY = date(2026, 7, 31)


@pytest.fixture
async def renewal_context():
    current_time = [FIXED_NOW]

    def clock() -> datetime:
        return current_time[0]

    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
        clock=clock,
    )

    async def override_adapter():
        return adapter

    async def override_service():
        return ContractService(adapter, now=clock)

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_contract_service] = override_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, adapter, current_time
    finally:
        app.dependency_overrides.clear()


def authorization_header(token: str = BEARER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_contract(client: AsyncClient, title: str = "재계약 검토 계약") -> UUID:
    response = await client.post(
        "/api/v1/contracts",
        headers=authorization_header(),
        json={"title": title, "counterparty_name": "부산홍보대행"},
    )
    assert response.status_code == 201
    return UUID(response.json()["data"]["id"])


def put_contract_in_review_window(
    adapter: SupabaseAdapter,
    contract_id: UUID,
    *,
    end_date: date | None = None,
    termination_notice_date: date | None = None,
    renewal_type: str | None = None,
) -> None:
    adapter._mock_contracts[contract_id] = replace(
        adapter._mock_contracts[contract_id],
        end_date=end_date,
        termination_notice_date=termination_notice_date,
        renewal_type=renewal_type,
    )


async def save_decision(
    client: AsyncClient,
    contract_id: UUID,
    decision: str,
) -> object:
    return await client.put(
        f"/api/v1/contracts/{contract_id}/renewal-decision",
        headers=authorization_header(),
        json={"decision": decision, "confirmed": True},
    )


async def test_saves_replays_and_changes_renewal_decision(renewal_context) -> None:
    client, adapter, current_time = renewal_context
    contract_id = await create_contract(client)
    put_contract_in_review_window(
        adapter,
        contract_id,
        end_date=TODAY + timedelta(days=30),
    )
    kept_item_id = uuid4()
    rejected_item_id = uuid4()
    adapter._mock_review_items[kept_item_id] = ReviewItemForAdjustment(
        id=kept_item_id,
        contract_id=contract_id,
        status=ReviewItemStatus.KEPT_ORIGINAL,
        user_choice=SuggestionChoice.REQUEST,
        suggestion_compromise="일부 조건을 조정해 주세요.",
        suggestion_request="조건 근거를 확인해 주세요.",
    )
    adapter._mock_review_items[rejected_item_id] = ReviewItemForAdjustment(
        id=rejected_item_id,
        contract_id=contract_id,
        status=ReviewItemStatus.SENT,
        user_choice=SuggestionChoice.REQUEST,
        suggestion_compromise="일부 조건을 조정해 주세요.",
        suggestion_request="조건 근거를 확인해 주세요.",
    )
    adjustment_request_id = uuid4()
    adapter._mock_adjustment_requests[adjustment_request_id] = AdjustmentRequestRecord(
        id=adjustment_request_id,
        contract_id=contract_id,
        status=AdjustmentRequestStatus.RESPONDED,
        items=(
            AdjustmentRequestItemRecord(
                review_item_id=rejected_item_id,
                user_choice=SuggestionChoice.REQUEST,
                request_text="조건 근거를 확인해 주세요.",
            ),
        ),
        expires_in_hours=72,
        sent_at=FIXED_NOW,
        expires_at=FIXED_NOW + timedelta(hours=72),
        opened_at=FIXED_NOW,
        responded_at=FIXED_NOW,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )
    adapter._mock_adjustment_responses[adjustment_request_id] = (
        AdjustmentResponseRecord(
            review_item_id=rejected_item_id,
            decision=AdjustmentResponseDecision.REJECT,
            counter_text=None,
            reason="기존 조건을 유지합니다.",
        ),
    )

    first = await save_decision(client, contract_id, "RENEW_WITH_CHANGES")

    assert first.status_code == 200
    first_data = first.json()["data"]
    assert first_data["decision"] == "RENEW_WITH_CHANGES"
    assert first_data["revisit_review_item_ids"] == sorted(
        [str(kept_item_id), str(rejected_item_id)]
    )
    first_decided_at = first_data["decided_at"]
    first_event_count = sum(
        event.event_type == "RENEWAL_DECISION_SAVED"
        for event in adapter.mock_audit_events
    )

    added_after_save = uuid4()
    adapter._mock_review_items[added_after_save] = replace(
        adapter._mock_review_items[kept_item_id],
        id=added_after_save,
    )
    current_time[0] += timedelta(minutes=1)
    replay = await save_decision(client, contract_id, "RENEW_WITH_CHANGES")

    assert replay.status_code == 200
    assert replay.json()["data"] == first_data
    assert replay.json()["data"]["decided_at"] == first_decided_at
    assert (
        sum(
            event.event_type == "RENEWAL_DECISION_SAVED"
            for event in adapter.mock_audit_events
        )
        == first_event_count
    )

    current_time[0] += timedelta(minutes=1)
    changed = await save_decision(client, contract_id, "TERMINATE")
    detail = await client.get(
        f"/api/v1/contracts/{contract_id}",
        headers=authorization_header(),
    )

    assert changed.status_code == 200
    assert changed.json()["data"]["decision"] == "TERMINATE"
    assert changed.json()["data"]["revisit_review_item_ids"] == []
    assert changed.json()["data"]["decided_at"] != first_decided_at
    assert detail.status_code == 200
    assert detail.json()["data"]["renewal_decision"] == changed.json()["data"]
    assert adapter.mock_contracts[contract_id].status == ContractStatus.DRAFT
    assert len(adapter.mock_contracts) == 1
    assert len(adapter._mock_adjustment_requests) == 1


@pytest.mark.parametrize(
    ("end_days", "notice_days", "renewal_type"),
    [
        (30, None, None),
        (0, None, None),
        (None, 14, None),
        (7, None, "AUTO"),
    ],
)
async def test_accepts_inclusive_review_window_boundaries(
    renewal_context,
    end_days,
    notice_days,
    renewal_type,
) -> None:
    client, adapter, _current_time = renewal_context
    contract_id = await create_contract(client)
    put_contract_in_review_window(
        adapter,
        contract_id,
        end_date=TODAY + timedelta(days=end_days) if end_days is not None else None,
        termination_notice_date=(
            TODAY + timedelta(days=notice_days)
            if notice_days is not None
            else None
        ),
        renewal_type=renewal_type,
    )

    response = await save_decision(client, contract_id, "RENEW_SAME_TERMS")

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("end_days", "notice_days"),
    [
        (31, None),
        (None, 15),
        (-1, None),
        (None, -1),
        (None, None),
    ],
)
async def test_rejects_outside_review_window(
    renewal_context,
    end_days,
    notice_days,
) -> None:
    client, adapter, _current_time = renewal_context
    contract_id = await create_contract(client)
    put_contract_in_review_window(
        adapter,
        contract_id,
        end_date=TODAY + timedelta(days=end_days) if end_days is not None else None,
        termination_notice_date=(
            TODAY + timedelta(days=notice_days)
            if notice_days is not None
            else None
        ),
    )

    response = await save_decision(client, contract_id, "TERMINATE")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert contract_id not in adapter.mock_renewal_decisions


async def test_validates_auth_ownership_path_and_body(renewal_context) -> None:
    client, adapter, _current_time = renewal_context
    contract_id = await create_contract(client)
    put_contract_in_review_window(
        adapter,
        contract_id,
        end_date=TODAY + timedelta(days=10),
    )
    path = f"/api/v1/contracts/{contract_id}/renewal-decision"
    valid_body = {"decision": "TERMINATE", "confirmed": True}

    no_auth = await client.put(path, json=valid_body)
    not_found = await client.put(
        f"/api/v1/contracts/{uuid4()}/renewal-decision",
        headers=authorization_header(),
        json=valid_body,
    )
    malformed_path = await client.put(
        "/api/v1/contracts/not-a-uuid/renewal-decision",
        headers=authorization_header(),
        json=valid_body,
    )
    invalid_bodies = [
        {"decision": "TERMINATE", "confirmed": False},
        {"decision": "TERMINATE"},
        {"decision": "UNKNOWN", "confirmed": True},
        {"decision": "TERMINATE", "confirmed": True, "extra": "forbidden"},
    ]
    invalid_responses = [
        await client.put(path, headers=authorization_header(), json=body)
        for body in invalid_bodies
    ]

    assert no_auth.status_code == 401
    assert not_found.status_code == 404
    assert malformed_path.status_code == 422
    assert all(response.status_code == 422 for response in invalid_responses)


async def test_live_adapter_uses_atomic_renewal_decision_rpc(monkeypatch) -> None:
    contract_id = uuid4()
    decision_payload = {
        "contract_id": str(contract_id),
        "decision": "RENEW_WITH_CHANGES",
        "decided_at": FIXED_NOW.isoformat(),
        "revisit_review_item_ids": [str(uuid4())],
    }

    class FakeResponse:
        data = {"outcome": "SAVED", "decision": decision_payload}

    class FakeRpc:
        def execute(self):
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def rpc(self, name, params):
            self.calls.append((name, params))
            return FakeRpc()

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    fake_client = FakeClient()
    monkeypatch.setattr("app.adapters.supabase.create_client", lambda *_args: fake_client)
    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = SupabaseAdapter(
        mode="live",
        url="https://project.supabase.co",
        service_role_key="test-service-role-key",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )

    result = await adapter.save_renewal_decision_with_audit(
        owner_id=OWNER_ID,
        contract_id=contract_id,
        decision=RenewalDecisionType.RENEW_WITH_CHANGES,
        today=TODAY,
        decided_at=FIXED_NOW,
    )

    assert result.outcome == RenewalDecisionSaveOutcome.SAVED
    assert result.decision is not None
    assert result.decision.contract_id == contract_id
    assert fake_client.calls == [
        (
            "save_renewal_decision_with_audit",
            {
                "p_owner_id": str(OWNER_ID),
                "p_contract_id": str(contract_id),
                "p_decision": "RENEW_WITH_CHANGES",
                "p_today": TODAY.isoformat(),
                "p_decided_at": FIXED_NOW.isoformat(),
            },
        )
    ]


def test_openapi_exposes_renewal_decision_contract() -> None:
    openapi = app.openapi()
    operation = openapi["paths"][
        "/api/v1/contracts/{contract_id}/renewal-decision"
    ]["put"]

    assert set(operation["responses"]) >= {"200", "401", "404", "409", "422"}
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/RenewalDecisionRequest")
    assert (
        openapi["components"]["schemas"]["RenewalDecisionRequest"]["properties"][
            "confirmed"
        ]["const"]
        is True
    )
    renewal_decision_schema = openapi["components"]["schemas"]["Contract"][
        "properties"
    ]["renewal_decision"]
    assert any(
        schema.get("$ref", "").endswith("/RenewalDecision")
        for schema in renewal_decision_schema["anyOf"]
    )
