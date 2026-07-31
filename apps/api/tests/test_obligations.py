from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import MockObligation, SupabaseAdapter
from app.api.dependencies import get_supabase_adapter
from app.core.enums import ObligationStatus
from app.main import app
from app.repositories.obligations import ObligationRecord
from app.services.obligations import ObligationService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"


@pytest.fixture
async def obligation_context():
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
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, adapter
    finally:
        app.dependency_overrides.clear()


def auth_headers(token: str = BEARER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def pending_obligation(*, contract_id: UUID, obligation_id: UUID | None = None):
    now = datetime(2026, 7, 31, 1, tzinfo=UTC)
    return MockObligation(
        id=obligation_id or uuid4(),
        contract_id=contract_id,
        title="인스타그램 게시물 4건",
        due_date=date(2026, 8, 20),
        assignee="AGENCY",
        evidence_type="URL",
        source_document_id=uuid4(),
        source_page=2,
        source_text="인스타그램 게시물 4건을 2026년 8월 20일까지 게시한다.",
        confidence=0.94,
        status=ObligationStatus.PENDING,
        created_at=now,
        updated_at=now,
    )


async def test_lists_empty_obligations_for_owned_contract(obligation_context) -> None:
    client, _adapter = obligation_context

    response = await client.get(
        f"/api/v1/contracts/{DEMO_CONTRACT_ID}/obligations",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_lists_representative_obligation_with_evidence_fields(
    obligation_context,
) -> None:
    client, adapter = obligation_context
    obligation = pending_obligation(contract_id=DEMO_CONTRACT_ID)
    adapter._mock_obligations[DEMO_CONTRACT_ID] = obligation

    response = await client.get(
        f"/api/v1/contracts/{DEMO_CONTRACT_ID}/obligations",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["requestId"].startswith("req_")
    assert body["data"] == [
        {
            "id": str(obligation.id),
            "contract_id": str(DEMO_CONTRACT_ID),
            "title": obligation.title,
            "due_date": "2026-08-20",
            "assignee": "AGENCY",
            "evidence_type": "URL",
            "source_document_id": str(obligation.source_document_id),
            "source_page": 2,
            "source_text": obligation.source_text,
            "confidence": 0.94,
            "evidence_url": None,
            "status": "PENDING",
            "submitted_at": None,
            "reviewed_at": None,
            "payment_condition_met": False,
        }
    ]


async def test_hides_missing_or_other_owner_contract(obligation_context) -> None:
    client, _adapter = obligation_context

    response = await client.get(
        f"/api/v1/contracts/{uuid4()}/obligations",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_requires_owner_authentication_and_valid_contract_id(
    obligation_context,
) -> None:
    client, _adapter = obligation_context

    unauthorized = await client.get(
        f"/api/v1/contracts/{DEMO_CONTRACT_ID}/obligations"
    )
    invalid_id = await client.get(
        "/api/v1/contracts/not-a-uuid/obligations",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"
    assert invalid_id.status_code == 422
    assert invalid_id.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_service_orders_obligations_by_due_date_then_id() -> None:
    contract_id = uuid4()
    first_id = UUID("00000000-0000-4000-8000-000000000001")
    second_id = UUID("00000000-0000-4000-8000-000000000002")

    def record(*, obligation_id: UUID, due_date: date) -> ObligationRecord:
        return ObligationRecord(
            id=obligation_id,
            contract_id=contract_id,
            title="블로그 게시물 1건",
            due_date=due_date,
            assignee="AGENCY",
            evidence_type="URL",
            source_document_id=uuid4(),
            source_page=1,
            source_text="블로그 게시물 1건을 제출한다.",
            confidence=0.9,
            evidence_url=None,
            status=ObligationStatus.PENDING,
            submitted_at=None,
            reviewed_at=None,
            payment_condition_met=False,
        )

    class FakeRepository:
        async def list_owned_obligations(self, *, owner_id: UUID, contract_id: UUID):
            return [
                record(obligation_id=second_id, due_date=date(2026, 8, 20)),
                record(obligation_id=first_id, due_date=date(2026, 8, 20)),
                record(obligation_id=uuid4(), due_date=date(2026, 8, 10)),
            ]

    obligations = await ObligationService(FakeRepository()).list(
        owner_id=OWNER_ID,
        contract_id=contract_id,
    )

    assert [item.due_date for item in obligations] == sorted(
        item.due_date for item in obligations
    )
    same_date_ids = [item.id for item in obligations if item.due_date == date(2026, 8, 20)]
    assert same_date_ids == [first_id, second_id]


async def test_live_adapter_checks_ownership_and_queries_in_stable_order(
    monkeypatch,
) -> None:
    obligation_id = uuid4()
    document_id = uuid4()
    obligation_row = {
        "id": str(obligation_id),
        "contract_id": str(DEMO_CONTRACT_ID),
        "title": "인스타그램 게시물 4건",
        "due_date": "2026-08-20",
        "assignee": "AGENCY",
        "evidence_type": "URL",
        "source_document_id": str(document_id),
        "source_page": 2,
        "source_text": "인스타그램 게시물 4건을 제출한다.",
        "confidence": 0.94,
        "evidence_url": None,
        "status": "PENDING",
        "submitted_at": None,
        "reviewed_at": None,
        "payment_condition_met": False,
    }

    class FakeResponse:
        def __init__(self, data) -> None:
            self.data = data

    class FakeQuery:
        def __init__(self, table_name: str, orders: list[str]) -> None:
            self.table_name = table_name
            self.orders = orders

        def select(self, _columns: str):
            return self

        def eq(self, _column: str, _value: str):
            return self

        def limit(self, _count: int):
            return self

        def order(self, column: str):
            self.orders.append(column)
            return self

        def execute(self):
            if self.table_name == "contracts":
                return FakeResponse([{"id": str(DEMO_CONTRACT_ID)}])
            if self.table_name == "obligations":
                return FakeResponse([obligation_row])
            raise AssertionError(f"예상하지 못한 테이블 조회: {self.table_name}")

    class FakeClient:
        def __init__(self) -> None:
            self.tables: list[str] = []
            self.orders: list[str] = []

        def table(self, table_name: str):
            self.tables.append(table_name)
            return FakeQuery(table_name, self.orders)

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

    records = await adapter.list_owned_obligations(
        owner_id=OWNER_ID,
        contract_id=DEMO_CONTRACT_ID,
    )

    assert records is not None
    assert len(records) == 1
    assert records[0].id == obligation_id
    assert records[0].source_document_id == document_id
    assert records[0].status == ObligationStatus.PENDING
    assert fake_client.tables == ["contracts", "obligations"]
    assert fake_client.orders == ["due_date", "id"]


def test_openapi_exposes_obligation_list_contract() -> None:
    openapi = app.openapi()
    operation = openapi["paths"]["/api/v1/contracts/{contract_id}/obligations"]["get"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    envelope_schema = openapi["components"]["schemas"][
        response_schema["$ref"].rsplit("/", 1)[-1]
    ]

    assert set(operation["responses"]) >= {"200", "401", "404", "422"}
    assert envelope_schema["properties"]["data"]["anyOf"][0]["maxItems"] == 1
