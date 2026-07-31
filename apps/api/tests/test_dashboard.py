from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_supabase_adapter
from app.core.enums import (
    AdjustmentRequestStatus,
    ContractStatus,
    DetectionMethod,
    ObligationStatus,
    ReviewBasisType,
    ReviewItemStatus,
    ReviewSeverity,
    ReviewSignalType,
    SuggestionChoice,
    VerificationStatus,
)
from app.main import app
from app.repositories.adjustments import AdjustmentRequestItemRecord, AdjustmentRequestRecord
from app.repositories.contracts import ContractRecord
from app.schemas.analysis import ReviewItem

OWNER_ID = UUID("00000000-0000-4000-8000-000000000091")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000092")
BEARER_TOKEN = "dashboard-test-owner-token-000000"
NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)
TODAY = date(2026, 7, 31)


@pytest.fixture
async def dashboard_context():
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


async def get_dashboard(client: AsyncClient) -> dict:
    response = await client.get("/api/v1/dashboard", headers=authorization_header())
    assert response.status_code == 200
    return response.json()["data"]


def add_contract(
    adapter: SupabaseAdapter,
    *,
    status: ContractStatus,
    total_amount: int | None = None,
    end_date: date | None = None,
    termination_notice_date: date | None = None,
    renewal_type: str | None = None,
    contract_id: UUID | None = None,
) -> UUID:
    contract_id = contract_id or uuid4()
    adapter._mock_owned_contracts.add((OWNER_ID, contract_id))
    adapter._mock_contracts[contract_id] = ContractRecord(
        id=contract_id,
        owner_id=OWNER_ID,
        title="대시보드 테스트 계약",
        counterparty_name="부산홍보대행",
        status=status,
        signed_date=None,
        start_date=None,
        end_date=end_date,
        termination_notice_date=termination_notice_date,
        renewal_type=renewal_type,
        total_amount=total_amount,
        understood_term=None,
        renewal_decision=None,
        modusign_document_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    return contract_id


def make_review_item(
    *,
    contract_id: UUID,
    item_type: ReviewSignalType,
    status: ReviewItemStatus,
    item_id: UUID | None = None,
) -> ReviewItem:
    return ReviewItem(
        id=item_id or uuid4(),
        contract_id=contract_id,
        type=item_type,
        severity=ReviewSeverity.CHECK,
        detection_method=DetectionMethod.DETERMINISTIC,
        model_confidence=None,
        model_limitations=None,
        plain_explanation="설명",
        basis_type=ReviewBasisType.INTERNAL_RULE,
        basis_text="계약 원문과 사용자 이해조건 비교",
        basis_citation=None,
        related_extracted_term_ids=[uuid4()],
        source_document_id=None,
        source_page=None,
        source_text=None,
        source_confidence=None,
        verification_status=VerificationStatus.MISSING_EVIDENCE,
        suggestion_accept="원안을 수용합니다.",
        suggestion_compromise="절충안을 제안합니다.",
        suggestion_request="수정을 요청합니다.",
        user_choice=None if status == ReviewItemStatus.UNREVIEWED else SuggestionChoice.REQUEST,
        status=status,
    )


def add_review_item(adapter: SupabaseAdapter, item: ReviewItem) -> None:
    adapter._mock_review_item_details[item.id] = item


async def test_empty_owner_returns_all_zero_dashboard(dashboard_context) -> None:
    client, _adapter = dashboard_context

    data = await get_dashboard(client)

    assert data == {
        "total": 0,
        "signing": 0,
        "in_progress": 0,
        "completed": 0,
        "expiring_soon": 0,
        "unresolved_signals": 0,
        "adjustment_requested_clauses": 0,
        "adjustment_agreed_clauses": 0,
        "adjustment_rejected_clauses": 0,
        "obligation_pending": 0,
        "obligation_submitted": 0,
        "obligation_approved": 0,
        "total_committed": 0,
        "payment_condition_met_amount": 0,
        "most_common_signal": None,
    }


async def test_requires_authentication() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/dashboard")
    assert response.status_code == 401


async def test_counts_contracts_by_status_without_double_counting(dashboard_context) -> None:
    client, adapter = dashboard_context
    add_contract(adapter, status=ContractStatus.DRAFT)
    add_contract(adapter, status=ContractStatus.SIGNING)
    add_contract(adapter, status=ContractStatus.SIGNING)
    add_contract(adapter, status=ContractStatus.IN_PROGRESS)
    add_contract(adapter, status=ContractStatus.RENEWAL_DUE)
    add_contract(adapter, status=ContractStatus.COMPLETED)

    data = await get_dashboard(client)

    assert data["total"] == 6
    assert data["signing"] == 2
    assert data["in_progress"] == 2
    assert data["completed"] == 1


@pytest.mark.parametrize(
    ("end_days", "notice_days", "renewal_type", "expected"),
    [
        (30, None, None, 1),
        (31, None, None, 0),
        (None, 14, None, 1),
        (None, 15, None, 0),
        (7, None, "AUTO", 1),
        (None, None, None, 0),
    ],
)
async def test_expiring_soon_boundaries(
    dashboard_context, end_days, notice_days, renewal_type, expected
) -> None:
    client, adapter = dashboard_context
    add_contract(
        adapter,
        status=ContractStatus.IN_PROGRESS,
        end_date=TODAY + timedelta(days=end_days) if end_days is not None else None,
        termination_notice_date=(
            TODAY + timedelta(days=notice_days) if notice_days is not None else None
        ),
        renewal_type=renewal_type,
    )

    data = await get_dashboard(client)

    assert data["expiring_soon"] == expected


async def test_expiring_soon_does_not_double_count_a_single_contract(dashboard_context) -> None:
    client, adapter = dashboard_context
    add_contract(
        adapter,
        status=ContractStatus.IN_PROGRESS,
        end_date=TODAY + timedelta(days=10),
        termination_notice_date=TODAY + timedelta(days=5),
    )

    data = await get_dashboard(client)

    assert data["expiring_soon"] == 1


async def test_total_committed_sums_qualifying_statuses_once_each(dashboard_context) -> None:
    client, adapter = dashboard_context
    add_contract(adapter, status=ContractStatus.SIGNED, total_amount=1_000_000)
    add_contract(adapter, status=ContractStatus.IN_PROGRESS, total_amount=2_000_000)
    add_contract(adapter, status=ContractStatus.RENEWAL_DUE, total_amount=3_000_000)
    add_contract(adapter, status=ContractStatus.COMPLETED, total_amount=4_000_000)
    # Not yet committed: excluded even though total_amount is set.
    add_contract(adapter, status=ContractStatus.NEGOTIATING, total_amount=5_000_000)
    add_contract(adapter, status=ContractStatus.READY_TO_SIGN, total_amount=6_000_000)
    # Committed status without a canonical amount contributes nothing.
    add_contract(adapter, status=ContractStatus.SIGNED, total_amount=None)

    data = await get_dashboard(client)

    assert data["total_committed"] == 1_000_000 + 2_000_000 + 3_000_000 + 4_000_000


async def test_obligation_status_counts_and_payment_condition_met_amount(
    dashboard_context,
) -> None:
    client, adapter = dashboard_context
    from app.adapters.supabase import MockObligation

    pending_contract = add_contract(adapter, status=ContractStatus.IN_PROGRESS, total_amount=100)
    submitted_contract = add_contract(
        adapter, status=ContractStatus.IN_PROGRESS, total_amount=200
    )
    approved_contract = add_contract(
        adapter, status=ContractStatus.IN_PROGRESS, total_amount=300
    )
    approved_no_amount_contract = add_contract(
        adapter, status=ContractStatus.IN_PROGRESS, total_amount=None
    )

    def obligation(contract_id: UUID, status: ObligationStatus) -> MockObligation:
        return MockObligation(
            id=uuid4(),
            contract_id=contract_id,
            title="산출물",
            due_date=TODAY,
            assignee="대행사",
            evidence_type="URL",
            source_document_id=uuid4(),
            source_page=1,
            source_text="산출물 근거",
            confidence=0.9,
            status=status,
            created_at=NOW,
            updated_at=NOW,
            payment_condition_met=status == ObligationStatus.APPROVED,
        )

    adapter._mock_obligations[pending_contract] = obligation(
        pending_contract, ObligationStatus.PENDING
    )
    adapter._mock_obligations[submitted_contract] = obligation(
        submitted_contract, ObligationStatus.SUBMITTED
    )
    adapter._mock_obligations[approved_contract] = obligation(
        approved_contract, ObligationStatus.APPROVED
    )
    adapter._mock_obligations[approved_no_amount_contract] = obligation(
        approved_no_amount_contract, ObligationStatus.APPROVED
    )

    data = await get_dashboard(client)

    assert data["obligation_pending"] == 1
    assert data["obligation_submitted"] == 1
    assert data["obligation_approved"] == 2
    assert data["payment_condition_met_amount"] == 300


async def test_review_item_status_drives_unresolved_and_clause_counts(dashboard_context) -> None:
    client, adapter = dashboard_context
    contract_id = add_contract(adapter, status=ContractStatus.NEGOTIATING)
    for status in (
        ReviewItemStatus.UNREVIEWED,
        ReviewItemStatus.SELECTED,
        ReviewItemStatus.SENT,
        ReviewItemStatus.RESOLVED,
        ReviewItemStatus.RESOLVED,
        ReviewItemStatus.KEPT_ORIGINAL,
    ):
        add_review_item(
            adapter,
            make_review_item(
                contract_id=contract_id,
                item_type=ReviewSignalType.MISMATCH,
                status=status,
            ),
        )

    data = await get_dashboard(client)

    assert data["unresolved_signals"] == 3
    assert data["adjustment_agreed_clauses"] == 2
    assert data["adjustment_rejected_clauses"] == 1


async def test_review_item_dashboard_prefers_confirmation_status_override(
    dashboard_context,
) -> None:
    """Adjustment confirmation only updates the narrow `_mock_review_items`
    projection, not the canonical detail store, so the dashboard must merge
    both to match live mode's single `review_items` row."""
    client, adapter = dashboard_context
    from app.repositories.adjustments import ReviewItemForAdjustment

    contract_id = add_contract(adapter, status=ContractStatus.NEGOTIATING)
    item_id = uuid4()
    add_review_item(
        adapter,
        make_review_item(
            contract_id=contract_id,
            item_type=ReviewSignalType.NO_BASIS,
            status=ReviewItemStatus.SENT,
            item_id=item_id,
        ),
    )
    adapter._mock_review_items[item_id] = ReviewItemForAdjustment(
        id=item_id,
        contract_id=contract_id,
        status=ReviewItemStatus.RESOLVED,
        user_choice=SuggestionChoice.REQUEST,
        suggestion_compromise="절충안",
        suggestion_request="요청안",
    )

    data = await get_dashboard(client)

    assert data["adjustment_agreed_clauses"] == 1
    assert data["unresolved_signals"] == 0


@pytest.mark.parametrize(
    ("types", "expected"),
    [
        (
            [ReviewSignalType.MISMATCH, ReviewSignalType.MISMATCH, ReviewSignalType.MISSING],
            "MISMATCH",
        ),
        # Tie broken by ReviewSignalType declaration order: MISMATCH before NO_BASIS.
        ([ReviewSignalType.NO_BASIS, ReviewSignalType.MISMATCH], "MISMATCH"),
        ([], None),
    ],
)
async def test_most_common_signal_is_deterministic(dashboard_context, types, expected) -> None:
    client, adapter = dashboard_context
    contract_id = add_contract(adapter, status=ContractStatus.NEGOTIATING)
    for item_type in types:
        add_review_item(
            adapter,
            make_review_item(
                contract_id=contract_id,
                item_type=item_type,
                status=ReviewItemStatus.UNREVIEWED,
            ),
        )

    data = await get_dashboard(client)

    assert data["most_common_signal"] == expected


async def test_most_common_signal_excludes_resolved_items(dashboard_context) -> None:
    client, adapter = dashboard_context
    contract_id = add_contract(adapter, status=ContractStatus.NEGOTIATING)
    add_review_item(
        adapter,
        make_review_item(
            contract_id=contract_id,
            item_type=ReviewSignalType.MISMATCH,
            status=ReviewItemStatus.RESOLVED,
        ),
    )

    data = await get_dashboard(client)

    assert data["most_common_signal"] is None
    assert data["unresolved_signals"] == 0


async def test_adjustment_requested_clauses_excludes_draft(dashboard_context) -> None:
    client, adapter = dashboard_context
    contract_id = add_contract(adapter, status=ContractStatus.NEGOTIATING)

    def request(status: AdjustmentRequestStatus, item_count: int) -> AdjustmentRequestRecord:
        return AdjustmentRequestRecord(
            id=uuid4(),
            contract_id=contract_id,
            status=status,
            items=tuple(
                AdjustmentRequestItemRecord(
                    review_item_id=uuid4(),
                    user_choice=SuggestionChoice.REQUEST,
                    request_text="수정을 요청합니다.",
                )
                for _ in range(item_count)
            ),
            expires_in_hours=72,
            sent_at=None if status == AdjustmentRequestStatus.DRAFT else NOW,
            expires_at=(
                None
                if status == AdjustmentRequestStatus.DRAFT
                else NOW + timedelta(hours=72)
            ),
            opened_at=None,
            responded_at=None,
            created_at=NOW,
            updated_at=NOW,
        )

    draft = request(AdjustmentRequestStatus.DRAFT, 5)
    sent = request(AdjustmentRequestStatus.SENT, 2)
    confirmed = request(AdjustmentRequestStatus.CONFIRMED, 1)
    adapter._mock_adjustment_requests[draft.id] = draft
    adapter._mock_adjustment_requests[sent.id] = sent
    adapter._mock_adjustment_requests[confirmed.id] = confirmed

    data = await get_dashboard(client)

    assert data["adjustment_requested_clauses"] == 3


class _FakeQueryResult:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeQueryBuilder:
    def __init__(self, table_name: str, data_by_table: dict[str, list[dict]]) -> None:
        self._table_name = table_name
        self._data_by_table = data_by_table

    def select(self, _columns: str) -> "_FakeQueryBuilder":
        return self

    def eq(self, _column: str, _value: object) -> "_FakeQueryBuilder":
        return self

    def in_(self, _column: str, _values: object) -> "_FakeQueryBuilder":
        return self

    def neq(self, _column: str, _value: object) -> "_FakeQueryBuilder":
        return self

    def execute(self) -> _FakeQueryResult:
        return _FakeQueryResult(self._data_by_table.get(self._table_name, []))


class _FakeClient:
    def __init__(self, data_by_table: dict[str, list[dict]]) -> None:
        self._data_by_table = data_by_table

    def table(self, name: str) -> _FakeQueryBuilder:
        return _FakeQueryBuilder(name, self._data_by_table)


async def test_live_adapter_queries_owner_scoped_tables_for_dashboard(monkeypatch) -> None:
    contract_id = uuid4()
    fake_client = _FakeClient(
        {
            "contracts": [
                {
                    "id": str(contract_id),
                    "title": "라이브 계약",
                    "counterparty_name": "부산홍보대행",
                    "status": "IN_PROGRESS",
                    "signed_date": None,
                    "start_date": None,
                    "end_date": None,
                    "termination_notice_date": None,
                    "renewal_type": None,
                    "total_amount": 500000,
                    "modusign_document_id": None,
                    "created_at": NOW.isoformat(),
                    "updated_at": NOW.isoformat(),
                }
            ],
            "obligations": [
                {
                    "id": str(uuid4()),
                    "contract_id": str(contract_id),
                    "title": "산출물",
                    "due_date": TODAY.isoformat(),
                    "assignee": "대행사",
                    "evidence_type": "URL",
                    "source_document_id": str(uuid4()),
                    "source_page": 1,
                    "source_text": "근거",
                    "confidence": 0.9,
                    "evidence_url": None,
                    "status": "APPROVED",
                    "submitted_at": None,
                    "reviewed_at": None,
                    "payment_condition_met": True,
                }
            ],
            "review_items": [
                {"contract_id": str(contract_id), "type": "MISMATCH", "status": "SENT"},
            ],
            "adjustment_requests": [
                {
                    "status": "SENT",
                    "adjustment_request_items": [{"review_item_id": str(uuid4())}],
                }
            ],
        }
    )

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.create_client", lambda *_args: fake_client)
    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = SupabaseAdapter(
        mode="live",
        url="https://project.supabase.co",
        service_role_key="test-service-role-key",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=uuid4(),
        demo_bearer_token=BEARER_TOKEN,
    )

    obligations = await adapter.list_dashboard_obligations(owner_id=OWNER_ID)
    review_items = await adapter.list_dashboard_review_items(owner_id=OWNER_ID)
    item_counts = await adapter.list_dashboard_adjustment_request_item_counts(owner_id=OWNER_ID)

    assert [o.status for o in obligations] == [ObligationStatus.APPROVED]
    assert [(r.contract_id, r.type, r.status) for r in review_items] == [
        (contract_id, ReviewSignalType.MISMATCH, ReviewItemStatus.SENT)
    ]
    assert item_counts == [1]


async def test_live_adapter_skips_queries_when_owner_has_no_contracts(monkeypatch) -> None:
    fake_client = _FakeClient({})

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.create_client", lambda *_args: fake_client)
    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = SupabaseAdapter(
        mode="live",
        url="https://project.supabase.co",
        service_role_key="test-service-role-key",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=uuid4(),
        demo_bearer_token=BEARER_TOKEN,
    )

    assert await adapter.list_dashboard_obligations(owner_id=OWNER_ID) == []
    assert await adapter.list_dashboard_review_items(owner_id=OWNER_ID) == []
    assert await adapter.list_dashboard_adjustment_request_item_counts(owner_id=OWNER_ID) == []


def test_openapi_exposes_dashboard_contract() -> None:
    openapi = app.openapi()
    operation = openapi["paths"]["/api/v1/dashboard"]["get"]

    assert set(operation["responses"]) >= {"200", "401"}
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/ApiResponse_Dashboard_")
    dashboard_schema = openapi["components"]["schemas"]["Dashboard"]
    assert set(dashboard_schema["required"]) == {
        "total",
        "signing",
        "in_progress",
        "completed",
        "expiring_soon",
        "unresolved_signals",
        "adjustment_requested_clauses",
        "adjustment_agreed_clauses",
        "adjustment_rejected_clauses",
        "obligation_pending",
        "obligation_submitted",
        "obligation_approved",
        "total_committed",
        "payment_condition_met_amount",
    }
    assert "most_common_signal" in dashboard_schema["properties"]
