from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import MockAuditEvent, SupabaseAdapter
from app.api.dependencies import get_supabase_adapter
from app.core.enums import ContractStatus
from app.main import app

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"


@pytest.fixture
async def contract_context():
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

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, adapter
    finally:
        app.dependency_overrides.clear()


def authorization_header(token: str = BEARER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_contract(client: AsyncClient, title: str) -> dict:
    response = await client.post(
        "/api/v1/contracts",
        headers=authorization_header(),
        json={"title": title, "counterparty_name": "부산홍보대행"},
    )
    assert response.status_code == 201
    return response.json()["data"]


async def test_creates_draft_contract_and_atomic_creation_audit(contract_context) -> None:
    client, adapter = contract_context

    body = await create_contract(client, "광안리 카페 SNS 광고대행 계약")

    assert body["status"] == "DRAFT"
    assert body["title"] == "광안리 카페 SNS 광고대행 계약"
    assert body["counterparty_name"] == "부산홍보대행"
    for nullable_field in (
        "signed_date",
        "start_date",
        "end_date",
        "termination_notice_date",
        "renewal_type",
        "total_amount",
        "understood_term",
        "renewal_decision",
        "modusign_document_id",
    ):
        assert body[nullable_field] is None

    contract_id = UUID(body["id"])
    assert adapter.mock_contracts[contract_id].status == ContractStatus.DRAFT
    events = [event for event in adapter.mock_audit_events if event.contract_id == contract_id]
    assert [(event.event_type, event.actor_type) for event in events] == [
        ("CONTRACT_CREATED", "OWNER")
    ]


async def test_lists_contracts_by_expiry_with_null_last_and_stable_id(contract_context) -> None:
    client, adapter = contract_context
    first = UUID((await create_contract(client, "종료일 빠른 계약"))["id"])
    second = UUID((await create_contract(client, "종료일 없는 계약"))["id"])
    third = UUID((await create_contract(client, "종료일 늦은 계약"))["id"])
    adapter._mock_contracts[first] = replace(
        adapter._mock_contracts[first],
        end_date=date(2026, 8, 3),
        termination_notice_date=date(2026, 7, 31),
        renewal_type="AUTO",
    )
    adapter._mock_contracts[third] = replace(
        adapter._mock_contracts[third],
        end_date=date(2026, 8, 3),
        termination_notice_date=date(2026, 8, 1),
        renewal_type="MANUAL",
    )

    response = await client.get("/api/v1/contracts", headers=authorization_header())

    assert response.status_code == 200
    contracts = response.json()["data"]
    assert [item["id"] for item in contracts] == [
        *(str(contract_id) for contract_id in sorted((first, third), key=str)),
        str(second),
    ]
    first_item = next(item for item in contracts if item["id"] == str(first))
    third_item = next(item for item in contracts if item["id"] == str(third))
    assert first_item["expiry_d_day"] is not None
    assert first_item["termination_notice_d_day"] is not None
    assert first_item["auto_renewal_d_day"] == first_item["expiry_d_day"]
    assert third_item["auto_renewal_d_day"] is None


async def test_hides_other_owner_contract_from_detail_and_timeline(contract_context) -> None:
    client, adapter = contract_context
    own_contract = UUID((await create_contract(client, "내 계약"))["id"])
    foreign_contract = uuid4()
    adapter._mock_contracts[foreign_contract] = replace(
        adapter._mock_contracts[own_contract], id=foreign_contract, owner_id=OTHER_OWNER_ID
    )
    adapter._mock_owned_contracts.add((OTHER_OWNER_ID, foreign_contract))

    paths = (
        f"/api/v1/contracts/{foreign_contract}",
        f"/api/v1/contracts/{foreign_contract}/timeline",
    )
    for path in paths:
        response = await client.get(path, headers=authorization_header())
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_timeline_is_ordered_and_never_returns_internal_payload(contract_context) -> None:
    client, adapter = contract_context
    contract_id = UUID((await create_contract(client, "타임라인 계약"))["id"])
    first_id = UUID("00000000-0000-4000-8000-000000000001")
    second_id = UUID("00000000-0000-4000-8000-000000000002")
    created_at = datetime(2026, 7, 30, 1, tzinfo=UTC)
    adapter._mock_audit_events.extend(
        [
            MockAuditEvent(
                id=second_id,
                contract_id=contract_id,
                event_type="ANALYSIS_STARTED",
                actor_type="OWNER",
                summary="분석을 시작했습니다.",
                created_at=created_at,
            ),
            MockAuditEvent(
                id=first_id,
                contract_id=contract_id,
                event_type="DOCUMENT_UPLOADED",
                actor_type="OWNER",
                summary="문서를 업로드했습니다.",
                created_at=created_at,
            ),
        ]
    )

    response = await client.get(
        f"/api/v1/contracts/{contract_id}/timeline", headers=authorization_header()
    )

    assert response.status_code == 200
    events = response.json()["data"]
    matching = [event for event in events if event["id"] in {str(first_id), str(second_id)}]
    assert [event["id"] for event in matching] == [str(first_id), str(second_id)]
    assert set(matching[0]) == {"id", "event_type", "actor_type", "summary", "created_at"}


async def test_contract_apis_require_valid_owner_authentication(contract_context) -> None:
    client, _adapter = contract_context

    response = await client.get("/api/v1/contracts")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"
