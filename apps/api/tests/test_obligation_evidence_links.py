from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import MockObligation, SupabaseAdapter
from app.api.dependencies import get_obligation_service, get_supabase_adapter
from app.core.enums import ObligationStatus, PublicTokenScope
from app.main import app
from app.repositories.obligations import EvidenceLinkCreateOutcome
from app.services.idempotency import IdempotencyService
from app.services.obligations import ObligationService
from app.services.public_tokens import PublicTokenService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
TOKEN_SECRET = "test-obligation-token-secret-at-least-32-characters"
FIXED_NOW = datetime(2026, 7, 31, 6, tzinfo=UTC)
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260730300000_add_obligation_evidence_links.sql"
)


def auth_headers(*, idempotency_key: UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)
    return headers


def pending_obligation() -> MockObligation:
    return MockObligation(
        id=uuid4(),
        contract_id=CONTRACT_ID,
        title="인스타그램 게시물 4건",
        due_date=date(2026, 8, 20),
        assignee="AGENCY",
        evidence_type="URL",
        source_document_id=uuid4(),
        source_page=2,
        source_text="인스타그램 게시물 4건을 2026년 8월 20일까지 게시한다.",
        confidence=0.94,
        status=ObligationStatus.PENDING,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


@pytest.fixture
async def evidence_link_context():
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    obligation = pending_obligation()
    adapter._mock_obligations[CONTRACT_ID] = obligation
    service = ObligationService(
        adapter,
        idempotency=IdempotencyService(adapter, now=lambda: FIXED_NOW),
        public_tokens=PublicTokenService(
            adapter,
            signing_secret=TOKEN_SECRET,
            now=lambda: FIXED_NOW,
        ),
        public_app_base_url="http://localhost:3000",
        now=lambda: FIXED_NOW,
    )

    async def override_adapter():
        return adapter

    async def override_service():
        return service

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_obligation_service] = override_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, adapter, obligation
    finally:
        app.dependency_overrides.clear()


async def test_creates_and_replays_evidence_link_without_storing_raw_url(
    evidence_link_context,
) -> None:
    client, adapter, obligation = evidence_link_context
    key = uuid4()
    path = (
        f"/api/v1/contracts/{CONTRACT_ID}/obligations/"
        f"{obligation.id}/evidence-link"
    )

    created = await client.post(
        path,
        headers=auth_headers(idempotency_key=key),
        json={"expires_in_hours": 72},
    )

    assert created.status_code == 201
    assert created.headers["Cache-Control"] == "no-store"
    data = created.json()["data"]
    assert data["scope"] == "OBLIGATION_EVIDENCE"
    assert data["public_url"].startswith("http://localhost:3000/obligations/")
    assert data["expires_at"] == (FIXED_NOW + timedelta(hours=72)).isoformat().replace(
        "+00:00", "Z"
    )

    token = data["public_url"].rsplit("/", 1)[-1]
    token_records = tuple(adapter.mock_public_tokens.values())
    assert len(token_records) == 1
    assert token_records[0].scope == PublicTokenScope.OBLIGATION_EVIDENCE
    assert token_records[0].resource_id == obligation.id
    assert token_records[0].created_at == FIXED_NOW
    assert token_records[0].expires_at == FIXED_NOW + timedelta(hours=72)
    assert token not in adapter.mock_public_tokens
    assert token not in repr(token_records[0])

    idempotency_record = adapter.mock_idempotency_records[0]
    assert idempotency_record.response_payload is not None
    assert set(idempotency_record.response_payload) == {"token_id", "expires_at"}
    assert token not in repr(idempotency_record.response_payload)
    events = [
        event
        for event in adapter.mock_audit_events
        if event.contract_id == CONTRACT_ID
        and event.event_type == "EVIDENCE_LINK_CREATED"
    ]
    assert len(events) == 1
    assert events[0].created_at == FIXED_NOW

    replay = await client.post(
        path,
        headers=auth_headers(idempotency_key=key),
        json={"expires_in_hours": 72},
    )

    assert replay.status_code == 201
    assert replay.headers["Cache-Control"] == "no-store"
    assert replay.json()["data"] == data
    assert len(adapter.mock_public_tokens) == 1
    assert len(
        [
            event
            for event in adapter.mock_audit_events
            if event.event_type == "EVIDENCE_LINK_CREATED"
        ]
    ) == 1


async def test_rejects_same_key_with_different_expiry(evidence_link_context) -> None:
    client, _adapter, obligation = evidence_link_context
    key = uuid4()
    path = (
        f"/api/v1/contracts/{CONTRACT_ID}/obligations/"
        f"{obligation.id}/evidence-link"
    )
    first = await client.post(
        path,
        headers=auth_headers(idempotency_key=key),
        json={"expires_in_hours": 24},
    )

    conflict = await client.post(
        path,
        headers=auth_headers(idempotency_key=key),
        json={"expires_in_hours": 48},
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.headers["Cache-Control"] == "no-store"
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_hides_missing_resources_and_rejects_non_pending_status(
    evidence_link_context,
) -> None:
    client, adapter, obligation = evidence_link_context
    missing_contract = await client.post(
        f"/api/v1/contracts/{uuid4()}/obligations/{obligation.id}/evidence-link",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"expires_in_hours": 72},
    )
    missing_obligation = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/obligations/{uuid4()}/evidence-link",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"expires_in_hours": 72},
    )
    adapter._mock_obligations[CONTRACT_ID] = replace(
        obligation,
        status=ObligationStatus.SUBMITTED,
        evidence_url="https://example.com/evidence",
        submitted_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )
    invalid_status = await client.post(
        (
            f"/api/v1/contracts/{CONTRACT_ID}/obligations/"
            f"{obligation.id}/evidence-link"
        ),
        headers=auth_headers(idempotency_key=uuid4()),
        json={"expires_in_hours": 72},
    )

    assert missing_contract.status_code == 404
    assert missing_obligation.status_code == 404
    assert invalid_status.status_code == 409
    assert invalid_status.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert all(
        response.headers["Cache-Control"] == "no-store"
        for response in (missing_contract, missing_obligation, invalid_status)
    )


async def test_validates_auth_header_and_expiry_with_no_store(
    evidence_link_context,
) -> None:
    client, _adapter, obligation = evidence_link_context
    path = (
        f"/api/v1/contracts/{CONTRACT_ID}/obligations/"
        f"{obligation.id}/evidence-link"
    )
    unauthorized = await client.post(
        path,
        headers={"Idempotency-Key": str(uuid4())},
        json={"expires_in_hours": 72},
    )
    missing_key = await client.post(
        path,
        headers=auth_headers(),
        json={"expires_in_hours": 72},
    )
    invalid_expiry = await client.post(
        path,
        headers=auth_headers(idempotency_key=uuid4()),
        json={"expires_in_hours": 169},
    )

    assert unauthorized.status_code == 401
    assert missing_key.status_code == 422
    assert invalid_expiry.status_code == 422
    assert all(
        response.headers["Cache-Control"] == "no-store"
        for response in (unauthorized, missing_key, invalid_expiry)
    )


async def test_live_adapter_calls_atomic_evidence_link_rpc(monkeypatch) -> None:
    obligation_id = uuid4()

    class FakeResponse:
        data = "CREATED"

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
    token_service = PublicTokenService(
        adapter,
        signing_secret=TOKEN_SECRET,
        now=lambda: FIXED_NOW,
    )
    _issued, token_record = token_service.prepare(
        scope=PublicTokenScope.OBLIGATION_EVIDENCE,
        resource_id=obligation_id,
        created_at=FIXED_NOW,
        expires_at=FIXED_NOW + timedelta(hours=72),
    )

    outcome = await adapter.create_obligation_evidence_link_with_audit(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        obligation_id=obligation_id,
        public_token=token_record,
    )

    assert outcome == EvidenceLinkCreateOutcome.CREATED
    assert fake_client.calls == [
        (
            "create_obligation_evidence_link_with_audit",
            {
                "p_owner_id": str(OWNER_ID),
                "p_contract_id": str(CONTRACT_ID),
                "p_obligation_id": str(obligation_id),
                "p_public_token_id": str(token_record.id),
                "p_token_hash": token_record.token_hash,
                "p_token_scope": "OBLIGATION_EVIDENCE",
                "p_token_resource_id": str(obligation_id),
                "p_token_expires_at": token_record.expires_at.isoformat(),
                "p_token_created_at": token_record.created_at.isoformat(),
            },
        )
    ]


def test_migration_persists_token_and_audit_in_one_rpc() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "function public.create_obligation_evidence_link_with_audit" in sql
    assert "contract.owner_id = p_owner_id" in sql
    assert "v_status <> 'PENDING'" in sql
    assert "p_token_scope <> 'OBLIGATION_EVIDENCE'" in sql
    assert "insert into public.public_tokens" in sql
    assert "insert into public.audit_events" in sql
    assert "'EVIDENCE_LINK_CREATED'" in sql
    assert "to service_role" in sql


def test_openapi_exposes_evidence_link_contract() -> None:
    openapi = app.openapi()
    operation = openapi["paths"][
        "/api/v1/contracts/{contract_id}/obligations/{obligation_id}/evidence-link"
    ]["post"]

    assert set(operation["responses"]) >= {"201", "401", "404", "409", "422"}
    assert operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/PublicLinkCreate")
    assert any(
        parameter["name"] == "Idempotency-Key"
        and parameter["required"] is True
        for parameter in operation["parameters"]
    )
