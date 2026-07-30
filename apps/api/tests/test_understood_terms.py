from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import (
    get_supabase_adapter,
    get_understood_term_service,
)
from app.main import app
from app.schemas.understood_terms import UnderstoodTermInput
from app.services.understood_terms import UnderstoodTermService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
FIXED_NOW = datetime(2026, 7, 30, 13, 0, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_DIR = REPOSITORY_ROOT / "supabase" / "migrations"
MIGRATION_PATH = MIGRATION_DIR / "20260730180001_add_understood_terms.sql"


def understood_term_payload(**overrides):
    payload = {
        "duration_text": "1년",
        "monthly_amount": 500_000,
        "total_amount": 6_000_000,
        "refund_text": "중도해지 시 일부 환불",
        "termination_text": "중도해지 가능",
        "source_type": "USER_MEMORY",
    }
    payload.update(overrides)
    return payload


def authorization_header(token: str = BEARER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def understood_term_context():
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
        clock=lambda: FIXED_NOW,
    )
    service = UnderstoodTermService(repository=adapter)

    async def override_adapter():
        return adapter

    async def override_service():
        return service

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_understood_term_service] = override_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, adapter
    finally:
        app.dependency_overrides.clear()


async def test_saves_five_understood_terms_with_audit(
    understood_term_context,
) -> None:
    client, adapter = understood_term_context

    response = await client.put(
        f"/api/v1/contracts/{CONTRACT_ID}/understood-terms",
        headers=authorization_header(),
        json=understood_term_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["requestId"].startswith("req_")
    assert body["data"] == {
        **understood_term_payload(),
        "contract_id": str(CONTRACT_ID),
    }
    stored = adapter.mock_understood_terms[CONTRACT_ID]
    assert stored.contract_id == CONTRACT_ID
    assert stored.source_type == "USER_MEMORY"
    assert [event.event_type for event in adapter.mock_audit_events] == ["UNDERSTOOD_TERMS_SAVED"]
    assert adapter.mock_audit_events[0].created_at == FIXED_NOW


async def test_trims_user_text_and_allows_unknown_amounts(
    understood_term_context,
) -> None:
    client, adapter = understood_term_context

    response = await client.put(
        f"/api/v1/contracts/{CONTRACT_ID}/understood-terms",
        headers=authorization_header(),
        json=understood_term_payload(
            duration_text="  1년  ",
            monthly_amount=None,
            total_amount=None,
            refund_text="  잘 모르겠음  ",
            termination_text="  확인 필요  ",
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["duration_text"] == "1년"
    assert data["monthly_amount"] is None
    assert data["total_amount"] is None
    assert data["refund_text"] == "잘 모르겠음"
    assert data["termination_text"] == "확인 필요"
    assert adapter.mock_understood_terms[CONTRACT_ID].monthly_amount is None


async def test_same_put_does_not_duplicate_audit_event(
    understood_term_context,
) -> None:
    client, adapter = understood_term_context
    request = {
        "headers": authorization_header(),
        "json": understood_term_payload(),
    }

    first_response = await client.put(
        f"/api/v1/contracts/{CONTRACT_ID}/understood-terms",
        **request,
    )
    second_response = await client.put(
        f"/api/v1/contracts/{CONTRACT_ID}/understood-terms",
        **request,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["data"] == first_response.json()["data"]
    assert len(adapter.mock_audit_events) == 1


async def test_changed_put_replaces_values_and_adds_audit_event(
    understood_term_context,
) -> None:
    client, adapter = understood_term_context
    path = f"/api/v1/contracts/{CONTRACT_ID}/understood-terms"

    first_response = await client.put(
        path,
        headers=authorization_header(),
        json=understood_term_payload(),
    )
    changed_response = await client.put(
        path,
        headers=authorization_header(),
        json=understood_term_payload(
            duration_text="6개월",
            monthly_amount=400_000,
            total_amount=2_400_000,
        ),
    )

    assert first_response.status_code == 200
    assert changed_response.status_code == 200
    assert changed_response.json()["data"]["duration_text"] == "6개월"
    assert adapter.mock_understood_terms[CONTRACT_ID].total_amount == 2_400_000
    assert len(adapter.mock_audit_events) == 2


async def test_requires_owner_authentication(understood_term_context) -> None:
    client, adapter = understood_term_context
    path = f"/api/v1/contracts/{CONTRACT_ID}/understood-terms"

    missing_response = await client.put(path, json=understood_term_payload())
    invalid_response = await client.put(
        path,
        headers=authorization_header("not-the-demo-token"),
        json=understood_term_payload(),
    )

    assert missing_response.status_code == 401
    assert invalid_response.status_code == 401
    assert missing_response.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"
    assert invalid_response.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"
    assert adapter.mock_understood_terms == {}
    assert adapter.mock_audit_events == ()


async def test_hides_unknown_or_unowned_contract(understood_term_context) -> None:
    client, adapter = understood_term_context

    response = await client.put(
        f"/api/v1/contracts/{uuid4()}/understood-terms",
        headers=authorization_header(),
        json=understood_term_payload(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert adapter.mock_understood_terms == {}
    assert adapter.mock_audit_events == ()


@pytest.mark.parametrize(
    "missing_field",
    [
        "duration_text",
        "monthly_amount",
        "total_amount",
        "refund_text",
        "termination_text",
        "source_type",
    ],
)
async def test_requires_every_understood_term_field(
    understood_term_context,
    missing_field,
) -> None:
    client, adapter = understood_term_context
    payload = understood_term_payload()
    payload.pop(missing_field)

    response = await client.put(
        f"/api/v1/contracts/{CONTRACT_ID}/understood-terms",
        headers=authorization_header(),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert adapter.mock_understood_terms == {}


@pytest.mark.parametrize(
    "payload",
    [
        understood_term_payload(duration_text="   "),
        understood_term_payload(refund_text=""),
        understood_term_payload(termination_text="\t"),
        understood_term_payload(monthly_amount=-1),
        understood_term_payload(total_amount=-1),
        understood_term_payload(monthly_amount="500000"),
        understood_term_payload(total_amount=6_000_000.0),
        understood_term_payload(monthly_amount=True),
        understood_term_payload(source_type="DOCUMENTED_EXPLANATION"),
        understood_term_payload(contract_id=str(CONTRACT_ID)),
    ],
)
async def test_rejects_invalid_or_untrusted_understood_terms(
    understood_term_context,
    payload,
) -> None:
    client, adapter = understood_term_context

    response = await client.put(
        f"/api/v1/contracts/{CONTRACT_ID}/understood-terms",
        headers=authorization_header(),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert adapter.mock_understood_terms == {}
    assert adapter.mock_audit_events == ()


async def test_live_adapter_uses_atomic_save_rpc(monkeypatch) -> None:
    class FakeResponse:
        data = understood_term_payload(contract_id=str(CONTRACT_ID))

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
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    payload = UnderstoodTermInput.model_validate(understood_term_payload())

    saved = await adapter.save_understood_term_with_audit(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        payload=payload,
    )

    assert saved is not None
    assert saved.contract_id == CONTRACT_ID
    assert fake_client.calls == [
        (
            "save_understood_term_with_audit",
            {
                "p_owner_id": str(OWNER_ID),
                "p_contract_id": str(CONTRACT_ID),
                "p_duration_text": "1년",
                "p_monthly_amount": 500_000,
                "p_total_amount": 6_000_000,
                "p_refund_text": "중도해지 시 일부 환불",
                "p_termination_text": "중도해지 가능",
            },
        )
    ]


def test_migration_enforces_one_row_and_atomic_audit() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "contract_id uuid primary key" in migration
    assert "check (source_type = 'USER_MEMORY')" in migration
    assert "save_understood_term_with_audit" in migration
    assert "for update;" in migration
    assert "'UNDERSTOOD_TERMS_SAVED'" in migration
    assert "is not distinct from" in migration
    assert "to service_role;" in migration


def test_openapi_exposes_understood_term_contract() -> None:
    operation = app.openapi()["paths"]["/api/v1/contracts/{contract_id}/understood-terms"]["put"]

    assert set(operation["responses"]) >= {"200", "401", "404", "422"}
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("UnderstoodTermInput")
