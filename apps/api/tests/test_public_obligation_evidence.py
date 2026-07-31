from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import MockObligation, SupabaseAdapter
from app.api.dependencies import get_obligation_service, get_supabase_adapter
from app.core.enums import ContractStatus, ObligationStatus, PublicTokenScope
from app.main import app
from app.repositories.contracts import ContractRecord
from app.repositories.obligations import EvidenceSubmissionOutcome
from app.services.obligations import ObligationService
from app.services.public_tokens import PublicTokenService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
TOKEN_SECRET = "test-obligation-token-secret-at-least-32-characters"
STARTED_AT = datetime(2026, 7, 31, 6, tzinfo=UTC)
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260730310000_submit_obligation_evidence.sql"
)


def owner_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Idempotency-Key": str(uuid4()),
    }


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
        created_at=STARTED_AT,
        updated_at=STARTED_AT,
    )


def signed_contract() -> ContractRecord:
    return ContractRecord(
        id=CONTRACT_ID,
        owner_id=OWNER_ID,
        title="광안리 카페 SNS 광고대행 계약",
        counterparty_name="부산홍보대행",
        status=ContractStatus.SIGNED,
        signed_date=None,
        start_date=None,
        end_date=None,
        termination_notice_date=None,
        renewal_type=None,
        total_amount=None,
        understood_term=None,
        renewal_decision=None,
        modusign_document_id=None,
        created_at=STARTED_AT,
        updated_at=STARTED_AT,
    )


@pytest.fixture
async def public_evidence_context():
    clock = [STARTED_AT]
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
    adapter._mock_contracts[CONTRACT_ID] = signed_contract()
    adapter._mock_obligations[CONTRACT_ID] = obligation
    token_service = PublicTokenService(
        adapter,
        signing_secret=TOKEN_SECRET,
        now=lambda: clock[0],
    )
    service = ObligationService(
        adapter,
        public_tokens=token_service,
        public_app_base_url="http://localhost:3000",
        now=lambda: clock[0],
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
            yield client, adapter, obligation, token_service, clock
    finally:
        app.dependency_overrides.clear()


async def create_evidence_token(
    client: AsyncClient,
    *,
    obligation_id: UUID,
    expires_in_hours: int = 72,
) -> str:
    response = await client.post(
        (f"/api/v1/contracts/{CONTRACT_ID}/obligations/{obligation_id}/evidence-link"),
        headers=owner_headers(),
        json={"expires_in_hours": expires_in_hours},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["public_url"].split("/r/", 1)[1].removesuffix("/evidence")


async def test_submits_url_once_and_records_state_with_audit(
    public_evidence_context,
) -> None:
    client, adapter, obligation, _token_service, _clock = public_evidence_context
    token = await create_evidence_token(client, obligation_id=obligation.id)
    path = f"/api/v1/public/obligations/{token}/evidence"
    evidence_url = "https://www.instagram.com/p/example"

    submitted = await client.post(path, json={"evidence_url": evidence_url})

    assert submitted.status_code == 200
    assert submitted.headers["Cache-Control"] == "no-store"
    assert submitted.json()["data"] == {"submitted": True}
    saved = adapter.mock_obligations[CONTRACT_ID]
    assert saved.status == ObligationStatus.SUBMITTED
    assert saved.evidence_url == evidence_url
    assert saved.submitted_at == STARTED_AT
    assert saved.reviewed_at is None
    assert saved.payment_condition_met is False
    assert [
        event.event_type for event in adapter.mock_audit_events if event.contract_id == CONTRACT_ID
    ] == ["EVIDENCE_LINK_CREATED", "EVIDENCE_SUBMITTED"]
    submitted_event = adapter.mock_audit_events[-1]
    assert submitted_event.actor_type == "AGENCY"
    assert token not in repr(submitted_event)

    repeated = await client.post(path, json={"evidence_url": evidence_url})

    assert repeated.status_code == 409
    assert repeated.headers["Cache-Control"] == "no-store"
    assert repeated.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert [event.event_type for event in adapter.mock_audit_events].count(
        "EVIDENCE_SUBMITTED"
    ) == 1


async def test_hides_malformed_scope_target_and_revoked_tokens(
    public_evidence_context,
) -> None:
    client, adapter, obligation, token_service, clock = public_evidence_context
    payload = {"evidence_url": "https://example.com/evidence"}
    wrong_scope = await token_service.issue_adjustment_response(
        adjustment_request_id=uuid4(),
        expires_at=clock[0] + timedelta(hours=1),
    )
    wrong_target = await token_service.issue(
        scope=PublicTokenScope.OBLIGATION_EVIDENCE,
        resource_id=uuid4(),
        expires_at=clock[0] + timedelta(hours=1),
    )
    revoked_token = await create_evidence_token(client, obligation_id=obligation.id)
    revoked_hash = next(
        token_hash
        for token_hash, record in adapter._mock_public_tokens.items()
        if record.resource_id == obligation.id
    )
    adapter._mock_public_tokens[revoked_hash] = replace(
        adapter._mock_public_tokens[revoked_hash],
        revoked_at=clock[0],
    )

    responses = [
        await client.post(
            "/api/v1/public/obligations/not-a-valid-token/evidence",
            json=payload,
        ),
        await client.post(
            f"/api/v1/public/obligations/{wrong_scope.token}/evidence",
            json=payload,
        ),
        await client.post(
            f"/api/v1/public/obligations/{wrong_target.token}/evidence",
            json=payload,
        ),
        await client.post(
            f"/api/v1/public/obligations/{revoked_token}/evidence",
            json=payload,
        ),
    ]

    assert all(response.status_code == 404 for response in responses)
    assert all(response.json()["error"]["code"] == "NOT_FOUND" for response in responses)
    assert all(response.headers["Cache-Control"] == "no-store" for response in responses)


async def test_returns_gone_for_valid_expired_obligation_token(
    public_evidence_context,
) -> None:
    client, _adapter, obligation, _token_service, clock = public_evidence_context
    token = await create_evidence_token(
        client,
        obligation_id=obligation.id,
        expires_in_hours=1,
    )
    clock[0] = clock[0] + timedelta(hours=1)

    response = await client.post(
        f"/api/v1/public/obligations/{token}/evidence",
        json={"evidence_url": "https://example.com/evidence"},
    )

    assert response.status_code == 410
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "OBLIGATION_LINK_EXPIRED"


@pytest.mark.parametrize(
    "payload",
    [
        {"evidence_url": "ftp://example.com/evidence"},
        {"evidence_url": "not-a-url"},
        {"evidence_url": f"https://example.com/{'x' * 2030}"},
        {
            "evidence_url": "https://example.com/evidence",
            "unexpected": "field",
        },
    ],
)
async def test_rejects_invalid_evidence_urls_without_changing_state(
    public_evidence_context,
    payload,
) -> None:
    client, adapter, obligation, _token_service, _clock = public_evidence_context
    token = await create_evidence_token(client, obligation_id=obligation.id)

    response = await client.post(
        f"/api/v1/public/obligations/{token}/evidence",
        json=payload,
    )

    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert adapter.mock_obligations[CONTRACT_ID].status == ObligationStatus.PENDING
    assert not any(event.event_type == "EVIDENCE_SUBMITTED" for event in adapter.mock_audit_events)


async def test_live_adapter_calls_atomic_submission_rpc(monkeypatch) -> None:
    obligation_id = uuid4()

    class FakeResponse:
        data = "SUBMITTED"

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
        now=lambda: STARTED_AT,
    )
    _issued, token_record = token_service.prepare(
        scope=PublicTokenScope.OBLIGATION_EVIDENCE,
        resource_id=obligation_id,
        expires_at=STARTED_AT + timedelta(hours=72),
        created_at=STARTED_AT,
    )
    evidence_url = "https://example.com/evidence"

    outcome = await adapter.submit_obligation_evidence_with_audit(
        public_token=token_record,
        evidence_url=evidence_url,
        submitted_at=STARTED_AT,
    )

    assert outcome == EvidenceSubmissionOutcome.SUBMITTED
    assert fake_client.calls == [
        (
            "submit_obligation_evidence_with_audit",
            {
                "p_public_token_id": str(token_record.id),
                "p_token_hash": token_record.token_hash,
                "p_obligation_id": str(obligation_id),
                "p_evidence_url": evidence_url,
                "p_submitted_at": STARTED_AT.isoformat(),
            },
        )
    ]


def test_submission_migration_validates_token_and_updates_atomically() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "function public.submit_obligation_evidence_with_audit" in sql
    assert "token.scope = 'OBLIGATION_EVIDENCE'" in sql
    assert "token.resource_id = p_obligation_id" in sql
    assert "token.revoked_at is null" in sql
    assert "for update" in sql
    assert "v_expires_at <= p_submitted_at" in sql
    assert "p_evidence_url is null" in sql
    assert "v_status <> 'PENDING'" in sql
    assert "status = 'SUBMITTED'" in sql
    assert "insert into public.audit_events" in sql
    assert "'EVIDENCE_SUBMITTED'" in sql
    assert "'AGENCY'" in sql


def test_openapi_exposes_public_obligation_submission_contract() -> None:
    openapi = app.openapi()
    operation = openapi["paths"]["/api/v1/public/obligations/{token}/evidence"]["post"]

    assert set(operation["responses"]) >= {"200", "404", "409", "410", "422"}
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/EvidenceSubmission")
    evidence_schema = openapi["components"]["schemas"]["EvidenceSubmission"]["properties"][
        "evidence_url"
    ]
    assert evidence_schema["format"] == "uri"
    assert evidence_schema["maxLength"] == 2048
