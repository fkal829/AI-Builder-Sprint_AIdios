from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import MockObligation, SupabaseAdapter
from app.api.dependencies import get_obligation_service, get_supabase_adapter
from app.core.enums import ContractStatus, ObligationStatus
from app.main import app
from app.repositories.contracts import ContractRecord
from app.repositories.obligations import EvidenceReviewOutcome
from app.services.obligations import ObligationService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
SUBMITTED_AT = datetime(2026, 7, 31, 6, tzinfo=UTC)
REVIEWED_AT = datetime(2026, 7, 31, 7, tzinfo=UTC)
EVIDENCE_URL = "https://www.instagram.com/p/example"
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260803010000_add_owner_obligation_checklist.sql"
)


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {BEARER_TOKEN}"}


def submitted_obligation() -> MockObligation:
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
        status=ObligationStatus.SUBMITTED,
        created_at=SUBMITTED_AT,
        updated_at=SUBMITTED_AT,
        evidence_url=EVIDENCE_URL,
        submitted_at=SUBMITTED_AT,
    )


def contract_record(*, status: ContractStatus = ContractStatus.SIGNED) -> ContractRecord:
    return ContractRecord(
        id=CONTRACT_ID,
        owner_id=OWNER_ID,
        title="광안리 카페 SNS 광고대행 계약",
        counterparty_name="부산홍보대행",
        status=status,
        signed_date=None,
        start_date=None,
        end_date=None,
        termination_notice_date=None,
        renewal_type=None,
        total_amount=None,
        understood_term=None,
        renewal_decision=None,
        modusign_document_id=None,
        created_at=SUBMITTED_AT,
        updated_at=SUBMITTED_AT,
    )


@pytest.fixture
async def evidence_review_context():
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    obligation = submitted_obligation()
    adapter._mock_contracts[CONTRACT_ID] = contract_record()
    adapter._mock_obligations[CONTRACT_ID] = obligation
    service = ObligationService(adapter, now=lambda: REVIEWED_AT)

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


@pytest.mark.parametrize(
    ("decision", "expected_payment", "expected_event"),
    [
        ("APPROVED", True, "EVIDENCE_APPROVED"),
        ("DISPUTED", False, "EVIDENCE_DISPUTED"),
    ],
)
async def test_reviews_submitted_evidence_and_records_audit(
    evidence_review_context,
    decision: str,
    expected_payment: bool,
    expected_event: str,
) -> None:
    client, adapter, obligation = evidence_review_context
    response = await client.patch(
        f"/api/v1/contracts/{CONTRACT_ID}/obligations/{obligation.id}",
        headers=auth_headers(),
        json={"decision": decision, "confirmed": True, "evidence_url": None},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == decision
    assert data["evidence_url"] == EVIDENCE_URL
    assert data["submitted_at"] == SUBMITTED_AT.isoformat().replace("+00:00", "Z")
    assert data["reviewed_at"] == REVIEWED_AT.isoformat().replace("+00:00", "Z")
    assert data["payment_condition_met"] is expected_payment

    saved = adapter.mock_obligations[CONTRACT_ID]
    assert saved.status == ObligationStatus(decision)
    assert saved.reviewed_at == REVIEWED_AT
    assert saved.payment_condition_met is expected_payment
    assert len(adapter.mock_audit_events) == 1
    event = adapter.mock_audit_events[0]
    assert event.event_type == expected_event
    assert event.actor_type == "OWNER"
    assert event.created_at == REVIEWED_AT
    assert EVIDENCE_URL not in (event.summary or "")


async def test_requires_owner_and_hides_unowned_resources(
    evidence_review_context,
) -> None:
    client, adapter, obligation = evidence_review_context
    path = f"/api/v1/contracts/{CONTRACT_ID}/obligations/{obligation.id}"
    payload = {"decision": "APPROVED", "confirmed": True, "evidence_url": None}

    unauthorized = await client.patch(path, json=payload)
    wrong_bearer = await client.patch(
        path,
        headers={"Authorization": "Bearer invalid-owner-token"},
        json=payload,
    )
    missing_contract = await client.patch(
        f"/api/v1/contracts/{uuid4()}/obligations/{obligation.id}",
        headers=auth_headers(),
        json=payload,
    )
    missing_obligation = await client.patch(
        f"/api/v1/contracts/{CONTRACT_ID}/obligations/{uuid4()}",
        headers=auth_headers(),
        json=payload,
    )

    assert unauthorized.status_code == 401
    assert wrong_bearer.status_code == 401
    assert missing_contract.status_code == 404
    assert missing_obligation.status_code == 404
    assert adapter.mock_obligations[CONTRACT_ID].status == ObligationStatus.SUBMITTED
    assert adapter.mock_audit_events == ()


@pytest.mark.parametrize(
    ("decision", "evidence_url", "expected_submitted_at", "expected_payment"),
    [
        ("APPROVED", EVIDENCE_URL, REVIEWED_AT, True),
        ("APPROVED", None, None, True),
        ("DISPUTED", None, None, False),
    ],
)
async def test_owner_checks_pending_obligation_directly(
    evidence_review_context,
    decision: str,
    evidence_url: str | None,
    expected_submitted_at: datetime | None,
    expected_payment: bool,
) -> None:
    client, adapter, obligation = evidence_review_context
    adapter._mock_obligations[CONTRACT_ID] = replace(
        obligation,
        status=ObligationStatus.PENDING,
        evidence_url=None,
        submitted_at=None,
    )

    response = await client.patch(
        f"/api/v1/contracts/{CONTRACT_ID}/obligations/{obligation.id}",
        headers=auth_headers(),
        json={
            "decision": decision,
            "confirmed": True,
            "evidence_url": evidence_url,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == decision
    assert data["evidence_url"] == evidence_url
    assert data["submitted_at"] == (
        expected_submitted_at.isoformat().replace("+00:00", "Z")
        if expected_submitted_at is not None
        else None
    )
    assert data["reviewed_at"] == REVIEWED_AT.isoformat().replace("+00:00", "Z")
    assert data["payment_condition_met"] is expected_payment


async def test_rejects_pending_before_signature_and_repeated_reviews(
    evidence_review_context,
) -> None:
    client, adapter, obligation = evidence_review_context
    path = f"/api/v1/contracts/{CONTRACT_ID}/obligations/{obligation.id}"
    adapter._mock_obligations[CONTRACT_ID] = replace(
        obligation,
        status=ObligationStatus.PENDING,
        evidence_url=None,
        submitted_at=None,
    )
    adapter._mock_contracts[CONTRACT_ID] = contract_record(status=ContractStatus.NEGOTIATING)

    pending = await client.patch(
        path,
        headers=auth_headers(),
        json={"decision": "APPROVED", "confirmed": True, "evidence_url": None},
    )

    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert adapter.mock_audit_events == ()

    adapter._mock_obligations[CONTRACT_ID] = obligation
    adapter._mock_contracts[CONTRACT_ID] = contract_record()
    approved = await client.patch(
        path,
        headers=auth_headers(),
        json={"decision": "APPROVED", "confirmed": True, "evidence_url": None},
    )
    repeated = await client.patch(
        path,
        headers=auth_headers(),
        json={"decision": "DISPUTED", "confirmed": True, "evidence_url": None},
    )

    assert approved.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert adapter.mock_obligations[CONTRACT_ID].status == ObligationStatus.APPROVED
    assert [
        event.event_type for event in adapter.mock_audit_events
    ] == ["EVIDENCE_APPROVED"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"decision": "SUBMITTED"},
        {"decision": "UNKNOWN"},
        {"decision": None},
        {"decision": "APPROVED", "unexpected": True},
        {"decision": "APPROVED", "confirmed": False},
        {"decision": "APPROVED", "confirmed": True, "evidence_url": "ftp://invalid"},
    ],
)
async def test_rejects_invalid_review_requests_without_mutation(
    evidence_review_context,
    payload,
) -> None:
    client, adapter, obligation = evidence_review_context
    response = await client.patch(
        f"/api/v1/contracts/{CONTRACT_ID}/obligations/{obligation.id}",
        headers=auth_headers(),
        json=payload,
    )

    assert response.status_code == 422
    assert adapter.mock_obligations[CONTRACT_ID].status == ObligationStatus.SUBMITTED
    assert adapter.mock_audit_events == ()


async def test_live_adapter_calls_atomic_review_rpc(monkeypatch) -> None:
    obligation = submitted_obligation()
    reviewed_row = {
        "id": str(obligation.id),
        "contract_id": str(CONTRACT_ID),
        "title": obligation.title,
        "due_date": obligation.due_date.isoformat(),
        "assignee": obligation.assignee,
        "evidence_type": obligation.evidence_type,
        "source_document_id": str(obligation.source_document_id),
        "source_page": obligation.source_page,
        "source_text": obligation.source_text,
        "confidence": obligation.confidence,
        "evidence_url": obligation.evidence_url,
        "status": "APPROVED",
        "submitted_at": SUBMITTED_AT.isoformat(),
        "reviewed_at": REVIEWED_AT.isoformat(),
        "payment_condition_met": True,
    }

    class FakeResponse:
        data = {"outcome": "REVIEWED", "obligation": reviewed_row}

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

    result = await adapter.review_obligation_evidence_with_audit(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        obligation_id=obligation.id,
        decision=ObligationStatus.APPROVED,
        evidence_url=None,
        reviewed_at=REVIEWED_AT,
    )

    assert result.outcome == EvidenceReviewOutcome.REVIEWED
    assert result.obligation is not None
    assert result.obligation.status == ObligationStatus.APPROVED
    assert result.obligation.payment_condition_met is True
    assert fake_client.calls == [
        (
            "check_obligation_with_audit",
            {
                "p_owner_id": str(OWNER_ID),
                "p_contract_id": str(CONTRACT_ID),
                "p_obligation_id": str(obligation.id),
                "p_decision": "APPROVED",
                "p_evidence_url": None,
                "p_reviewed_at": REVIEWED_AT.isoformat(),
            },
        )
    ]


def test_owner_check_migration_enforces_owner_state_and_atomic_audit() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "function public.check_obligation_with_audit" in sql
    assert "contract.owner_id = p_owner_id" in sql
    assert "obligation.id = p_obligation_id" in sql
    assert "for update of obligation" in sql
    assert "v_obligation.status not in ('PENDING', 'SUBMITTED')" in sql
    assert "v_contract_status not in ('SIGNED', 'IN_PROGRESS')" in sql
    assert "p_evidence_url" in sql
    assert "status = p_decision" in sql
    assert "reviewed_at = p_reviewed_at" in sql
    assert "payment_condition_met = p_decision = 'APPROVED'" in sql
    assert "'EVIDENCE_APPROVED'" in sql
    assert "'EVIDENCE_DISPUTED'" in sql
    assert "'OWNER'" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_openapi_exposes_obligation_evidence_review_contract() -> None:
    openapi = app.openapi()
    operation = openapi["paths"][
        "/api/v1/contracts/{contract_id}/obligations/{obligation_id}"
    ]["patch"]

    assert set(operation["responses"]) >= {"200", "401", "404", "409", "422"}
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/EvidenceReviewRequest")
    decision_schema = openapi["components"]["schemas"]["EvidenceReviewRequest"][
        "properties"
    ]["decision"]
    assert decision_schema["enum"] == ["APPROVED", "DISPUTED"]
    request_component = openapi["components"]["schemas"]["EvidenceReviewRequest"]
    assert set(request_component["required"]) == {"decision", "confirmed"}
    assert request_component["properties"]["confirmed"]["const"] is True
