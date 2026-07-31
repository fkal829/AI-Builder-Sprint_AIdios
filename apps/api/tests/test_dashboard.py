from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import MockObligation, SupabaseAdapter
from app.api.dependencies import (
    get_dashboard_service,
    get_supabase_adapter,
)
from app.core.enums import (
    AdjustmentRequestStatus,
    AdjustmentResolution,
    AdjustmentResponseDecision,
    AgreementClauseCategory,
    ContractStatus,
    ObligationStatus,
    ReviewItemStatus,
    ReviewSignalType,
    SuggestionChoice,
)
from app.main import app
from app.repositories.adjustments import (
    AdjustmentRequestItemRecord,
    AdjustmentRequestRecord,
    AdjustmentResponseRecord,
    FinalClauseRecord,
    ReviewItemForAdjustment,
)
from app.repositories.contracts import ContractRecord
from app.services.dashboard import DashboardService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
TODAY = date(2026, 7, 31)
NOW = datetime(2026, 7, 31, 3, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class DashboardReviewItem:
    id: UUID
    contract_id: UUID
    type: ReviewSignalType
    status: ReviewItemStatus


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

    async def override_service():
        return DashboardService(adapter, now=lambda: NOW)

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_dashboard_service] = override_service
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


def contract_record(
    *,
    owner_id: UUID = OWNER_ID,
    status: ContractStatus,
    total_amount: int | None = None,
    end_date: date | None = None,
    termination_notice_date: date | None = None,
    renewal_type: str | None = None,
) -> ContractRecord:
    contract_id = uuid4()
    return ContractRecord(
        id=contract_id,
        owner_id=owner_id,
        title=f"대시보드 계약 {contract_id}",
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


def seed_contract(adapter: SupabaseAdapter, record: ContractRecord) -> None:
    adapter._mock_contracts[record.id] = record
    adapter._mock_owned_contracts.add((record.owner_id, record.id))


def seed_review_item(
    adapter: SupabaseAdapter,
    *,
    contract_id: UUID,
    signal: ReviewSignalType,
    status: ReviewItemStatus,
) -> UUID:
    item_id = uuid4()
    adapter._mock_review_item_details[item_id] = DashboardReviewItem(
        id=item_id,
        contract_id=contract_id,
        type=signal,
        status=status,
    )
    return item_id


def adjustment_item(
    adapter: SupabaseAdapter,
    *,
    contract_id: UUID,
    item_id: UUID | None = None,
) -> AdjustmentRequestItemRecord:
    review_item_id = item_id or uuid4()
    adapter._mock_review_items[review_item_id] = ReviewItemForAdjustment(
        id=review_item_id,
        contract_id=contract_id,
        status=ReviewItemStatus.SENT,
        user_choice=SuggestionChoice.REQUEST,
        suggestion_compromise="조건을 절충해 주세요.",
        suggestion_request="조건을 명확히 적어 주세요.",
    )
    return AdjustmentRequestItemRecord(
        review_item_id=review_item_id,
        user_choice=SuggestionChoice.REQUEST,
        request_text="조건을 명확히 적어 주세요.",
    )


def adjustment_request(
    *,
    contract_id: UUID,
    status: AdjustmentRequestStatus,
    items: tuple[AdjustmentRequestItemRecord, ...],
) -> AdjustmentRequestRecord:
    sent_at = None if status == AdjustmentRequestStatus.DRAFT else NOW
    return AdjustmentRequestRecord(
        id=uuid4(),
        contract_id=contract_id,
        status=status,
        items=items,
        expires_in_hours=72,
        sent_at=sent_at,
        expires_at=sent_at,
        opened_at=None,
        responded_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def obligation(
    *,
    contract_id: UUID,
    status: ObligationStatus,
) -> MockObligation:
    has_submission = status != ObligationStatus.PENDING
    has_review = status in {
        ObligationStatus.APPROVED,
        ObligationStatus.DISPUTED,
    }
    return MockObligation(
        id=uuid4(),
        contract_id=contract_id,
        title="인스타그램 게시물 4건",
        due_date=date(2026, 8, 20),
        assignee="AGENCY",
        evidence_type="URL",
        source_document_id=uuid4(),
        source_page=1,
        source_text="인스타그램 게시물 4건을 게시한다.",
        confidence=0.9,
        status=status,
        created_at=NOW,
        updated_at=NOW,
        evidence_url="https://example.com/evidence" if has_submission else None,
        submitted_at=NOW if has_submission else None,
        reviewed_at=NOW if has_review else None,
        payment_condition_met=status == ObligationStatus.APPROVED,
    )


def final_clause(
    *,
    review_item_id: UUID,
    resolution: AdjustmentResolution,
) -> FinalClauseRecord:
    agreed = resolution != AdjustmentResolution.KEEP_ORIGINAL
    return FinalClauseRecord(
        review_item_id=review_item_id,
        category=AgreementClauseCategory.OTHER,
        resolution=resolution,
        outcome="AGREED" if agreed else "KEPT_ORIGINAL",
        disposition="AGREED" if agreed else "WITHDRAWN",
        before_text="기존 조건",
        after_text="최종 조건",
        reason=None,
    )


async def test_empty_dashboard_returns_zeroes_and_null_signal(
    dashboard_context,
) -> None:
    client, _adapter = dashboard_context

    response = await client.get("/api/v1/dashboard", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["data"] == {
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


async def test_dashboard_aggregates_deterministic_counts_dates_and_amounts(
    dashboard_context,
) -> None:
    client, adapter = dashboard_context
    signing = contract_record(
        status=ContractStatus.SIGNING,
        total_amount=500_000,
        end_date=date(2026, 8, 30),
    )
    in_progress = contract_record(
        status=ContractStatus.IN_PROGRESS,
        total_amount=1_000_000,
        end_date=date(2026, 12, 31),
        termination_notice_date=date(2026, 8, 14),
    )
    renewal_due = contract_record(
        status=ContractStatus.RENEWAL_DUE,
        total_amount=2_000_000,
        end_date=date(2026, 8, 7),
        renewal_type="AUTO",
    )
    completed = contract_record(
        status=ContractStatus.COMPLETED,
        total_amount=3_000_000,
    )
    signed = contract_record(
        status=ContractStatus.SIGNED,
        total_amount=4_000_000,
        end_date=date(2026, 7, 30),
    )
    for record in (signing, in_progress, renewal_due, completed, signed):
        seed_contract(adapter, record)

    adapter._mock_obligations[in_progress.id] = obligation(
        contract_id=in_progress.id,
        status=ObligationStatus.PENDING,
    )
    adapter._mock_obligations[renewal_due.id] = obligation(
        contract_id=renewal_due.id,
        status=ObligationStatus.APPROVED,
    )
    adapter._mock_obligations[completed.id] = obligation(
        contract_id=completed.id,
        status=ObligationStatus.SUBMITTED,
    )
    adapter._mock_obligations[signed.id] = obligation(
        contract_id=signed.id,
        status=ObligationStatus.APPROVED,
    )

    response = await client.get("/api/v1/dashboard", headers=auth_headers())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 5
    assert data["signing"] == 1
    assert data["in_progress"] == 2
    assert data["completed"] == 1
    assert data["expiring_soon"] == 3
    assert data["obligation_pending"] == 1
    assert data["obligation_submitted"] == 1
    assert data["obligation_approved"] == 2
    assert data["total_committed"] == 10_000_000
    assert data["payment_condition_met_amount"] == 6_000_000


async def test_dashboard_counts_distinct_adjustments_and_uses_fixed_signal_tie_break(
    dashboard_context,
) -> None:
    client, adapter = dashboard_context
    contract = contract_record(status=ContractStatus.NEGOTIATING)
    seed_contract(adapter, contract)

    for signal in (
        ReviewSignalType.MISMATCH,
        ReviewSignalType.MISMATCH,
        ReviewSignalType.NO_BASIS,
        ReviewSignalType.NO_BASIS,
        ReviewSignalType.UNCLEAR,
    ):
        seed_review_item(
            adapter,
            contract_id=contract.id,
            signal=signal,
            status=ReviewItemStatus.UNREVIEWED,
        )
    seed_review_item(
        adapter,
        contract_id=contract.id,
        signal=ReviewSignalType.MISSING,
        status=ReviewItemStatus.RESOLVED,
    )

    shared_item = adjustment_item(adapter, contract_id=contract.id)
    rejected_item = adjustment_item(adapter, contract_id=contract.id)
    kept_item = adjustment_item(adapter, contract_id=contract.id)
    draft_item = adjustment_item(adapter, contract_id=contract.id)
    sent = adjustment_request(
        contract_id=contract.id,
        status=AdjustmentRequestStatus.SENT,
        items=(shared_item, rejected_item),
    )
    confirmed = adjustment_request(
        contract_id=contract.id,
        status=AdjustmentRequestStatus.CONFIRMED,
        items=(shared_item, kept_item),
    )
    draft = adjustment_request(
        contract_id=contract.id,
        status=AdjustmentRequestStatus.DRAFT,
        items=(draft_item,),
    )
    adapter._mock_adjustment_requests.update(
        {
            sent.id: sent,
            confirmed.id: confirmed,
            draft.id: draft,
        }
    )
    adapter._mock_adjustment_responses[sent.id] = (
        AdjustmentResponseRecord(
            review_item_id=shared_item.review_item_id,
            decision=AdjustmentResponseDecision.ACCEPT,
            counter_text=None,
            reason=None,
        ),
        AdjustmentResponseRecord(
            review_item_id=rejected_item.review_item_id,
            decision=AdjustmentResponseDecision.REJECT,
            counter_text=None,
            reason="원안 유지",
        ),
    )
    adapter._mock_final_clauses[confirmed.id] = (
        final_clause(
            review_item_id=shared_item.review_item_id,
            resolution=AdjustmentResolution.ACCEPT_REQUEST,
        ),
        final_clause(
            review_item_id=kept_item.review_item_id,
            resolution=AdjustmentResolution.KEEP_ORIGINAL,
        ),
    )

    response = await client.get("/api/v1/dashboard", headers=auth_headers())

    data = response.json()["data"]
    assert data["unresolved_signals"] == 5
    assert data["most_common_signal"] == "MISMATCH"
    assert data["adjustment_requested_clauses"] == 3
    assert data["adjustment_agreed_clauses"] == 1
    assert data["adjustment_rejected_clauses"] == 2


async def test_dashboard_excludes_every_other_owner_fact(
    dashboard_context,
) -> None:
    client, adapter = dashboard_context
    own = contract_record(status=ContractStatus.DRAFT)
    foreign = contract_record(
        owner_id=OTHER_OWNER_ID,
        status=ContractStatus.COMPLETED,
        total_amount=99_000_000,
        end_date=TODAY,
    )
    seed_contract(adapter, own)
    seed_contract(adapter, foreign)
    seed_review_item(
        adapter,
        contract_id=foreign.id,
        signal=ReviewSignalType.NEEDS_CHECK,
        status=ReviewItemStatus.UNREVIEWED,
    )
    adapter._mock_obligations[foreign.id] = obligation(
        contract_id=foreign.id,
        status=ObligationStatus.APPROVED,
    )
    foreign_item = adjustment_item(adapter, contract_id=foreign.id)
    foreign_request = adjustment_request(
        contract_id=foreign.id,
        status=AdjustmentRequestStatus.SENT,
        items=(foreign_item,),
    )
    adapter._mock_adjustment_requests[foreign_request.id] = foreign_request

    response = await client.get("/api/v1/dashboard", headers=auth_headers())

    assert response.json()["data"] == {
        "total": 1,
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


async def test_dashboard_unauthorized_error_uses_safe_envelope(
    dashboard_context,
) -> None:
    client, _adapter = dashboard_context

    response = await client.get("/api/v1/dashboard")

    assert response.status_code == 401
    body = response.json()
    assert body["data"] is None
    assert body["error"] == {
        "code": "UNAUTHORIZED_ACCESS",
        "message": "인증이 필요합니다.",
    }
    assert body["requestId"] == response.headers["X-Request-ID"]


async def test_live_adapter_calls_owner_scoped_dashboard_rpc(monkeypatch) -> None:
    calls = []
    row = {
        "total": 2,
        "signing": 1,
        "in_progress": 1,
        "completed": 0,
        "expiring_soon": 1,
        "unresolved_signals": 3,
        "adjustment_requested_clauses": 2,
        "adjustment_agreed_clauses": 1,
        "adjustment_rejected_clauses": 1,
        "obligation_pending": 1,
        "obligation_submitted": 0,
        "obligation_approved": 1,
        "total_committed": 1_500_000,
        "payment_condition_met_amount": 500_000,
        "most_common_signal": "UNCLEAR",
    }

    class FakeClient:
        def rpc(self, name, params):
            calls.append((name, params))
            return SimpleNamespace(
                execute=lambda: SimpleNamespace(data=row),
            )

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "app.adapters.supabase.create_client",
        lambda *_args: FakeClient(),
    )
    monkeypatch.setattr(
        "app.adapters.supabase.asyncio.to_thread",
        run_inline,
    )
    adapter = SupabaseAdapter(
        mode="live",
        url="https://example.supabase.co",
        service_role_key="service-role-key",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )

    result = await adapter.get_dashboard(owner_id=OWNER_ID, today=TODAY)

    assert calls == [
        (
            "get_owner_dashboard",
            {
                "p_owner_id": str(OWNER_ID),
                "p_today": "2026-07-31",
            },
        )
    ]
    assert result.total == 2
    assert result.total_committed == 1_500_000
    assert result.most_common_signal == ReviewSignalType.UNCLEAR


def test_dashboard_openapi_matches_canonical_operation() -> None:
    operation = app.openapi()["paths"]["/api/v1/dashboard"]["get"]

    assert operation["operationId"] == "getDashboard"
    assert set(operation["responses"]) == {"200", "401"}


def test_dashboard_migration_is_owner_scoped_and_deterministic() -> None:
    migration = (
        REPOSITORY_ROOT / "supabase" / "migrations" / "20260730330003_add_dashboard_aggregation.sql"
    ).read_text(encoding="utf-8")

    assert "where contract.owner_id = p_owner_id" in migration
    assert "request.status <> 'DRAFT'" in migration
    assert "select distinct item.review_item_id" in migration
    assert "order by signal.signal_count desc, signal.tie_priority" in migration
    assert "end_date - p_today between 0 and 30" in migration
    assert "termination_notice_date - p_today between 0 and 14" in migration
    assert "end_date - p_today between 0 and 7" in migration
    assert "from public.obligations obligation" in migration
    assert "to service_role" in migration
