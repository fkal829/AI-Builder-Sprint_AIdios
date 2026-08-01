from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.solar import SolarReviewAdapter
from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import (
    get_counterproposal_comparator,
    get_supabase_adapter,
)
from app.core.enums import (
    AdjustmentRequestStatus,
    AnalysisStatus,
    ContractStatus,
    ReviewItemStatus,
    SuggestionChoice,
)
from app.main import app
from app.repositories.adjustments import ReviewItemForAdjustment
from app.repositories.analysis import AnalysisTaskRecord
from app.schemas.analysis import Analysis, DocumentClause
from app.services.counterproposal import CounterproposalComparator

OWNER_ID = UUID("00000000-0000-4000-8000-000000000023")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000042")
BEARER_TOKEN = "local-demo-owner-token"


@pytest.fixture
async def adjustment_context():
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


def auth_headers(*, idempotency_key: UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)
    return headers


async def reviewed_contract(client: AsyncClient, adapter: SupabaseAdapter) -> UUID:
    response = await client.post(
        "/api/v1/contracts",
        headers=auth_headers(),
        json={"title": "조정 요청 테스트 계약", "counterparty_name": "부산 대행사"},
    )
    assert response.status_code == 201
    contract_id = UUID(response.json()["data"]["id"])
    adapter._mock_contracts[contract_id] = replace(
        adapter._mock_contracts[contract_id],
        status=ContractStatus.REVIEW_REQUIRED,
    )
    return contract_id


def selected_review_item(
    *,
    contract_id: UUID,
    choice: SuggestionChoice,
) -> ReviewItemForAdjustment:
    return ReviewItemForAdjustment(
        id=uuid4(),
        contract_id=contract_id,
        status=ReviewItemStatus.SELECTED,
        user_choice=choice,
        suggestion_compromise="월 보고서를 제공하는 조건으로 위약금 비율을 조정해 주세요.",
        suggestion_request="위약금 조항을 삭제하고 월 보고서를 제공해 주세요.",
    )


def completed_document_clause(
    adapter: SupabaseAdapter,
    *,
    contract_id: UUID,
) -> DocumentClause:
    now = datetime.now(UTC)
    task_id = uuid4()
    document_id = uuid4()
    clause = DocumentClause(
        id=uuid4(),
        document_id=document_id,
        ordinal=1,
        heading="제7조",
        title="결과물 승인",
        source_page=3,
        source_text="제7조(결과물 승인) 시안을 받은 뒤 3영업일 이내 승인한다.",
        confidence=None,
    )
    adapter._mock_analysis_tasks[task_id] = AnalysisTaskRecord(
        id=task_id,
        contract_id=contract_id,
        document_id=document_id,
        supporting_document_ids=(),
        status=AnalysisStatus.COMPLETED,
        attempt_count=1,
        error_code=None,
        result=Analysis(
            contract_id=contract_id,
            document_clauses=[clause],
            extracted_terms=[],
            review_items=[],
        ),
        created_at=now,
        updated_at=now,
    )
    return clause


async def create_draft(
    client: AsyncClient,
    contract_id: UUID,
    review_item_ids: list[UUID],
    *,
    key: UUID | None = None,
) -> dict:
    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=key or uuid4()),
        json={
            "review_item_ids": [str(item_id) for item_id in review_item_ids],
            "expires_in_hours": 72,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


async def test_draft_previews_selected_request_text_without_public_url(adjustment_context) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)
    compromise = selected_review_item(contract_id=contract_id, choice=SuggestionChoice.COMPROMISE)
    request = selected_review_item(contract_id=contract_id, choice=SuggestionChoice.REQUEST)
    adapter._mock_review_items[compromise.id] = compromise
    adapter._mock_review_items[request.id] = request

    draft_key = uuid4()
    draft = await create_draft(
        client,
        contract_id,
        [compromise.id, request.id],
        key=draft_key,
    )

    assert draft["status"] == "DRAFT"
    assert draft["contract_id"] == str(contract_id)
    assert draft["items"] == [
        {
            "review_item_id": str(compromise.id),
            "user_choice": "COMPROMISE",
            "request_text": compromise.suggestion_compromise,
        },
        {
            "review_item_id": str(request.id),
            "user_choice": "REQUEST",
            "request_text": request.suggestion_request,
        },
    ]
    assert "public_url" not in draft
    assert all(
        draft[field] is None for field in ("sent_at", "expires_at", "opened_at", "responded_at")
    )
    replay = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=draft_key),
        json={
            "review_item_ids": [str(compromise.id), str(request.id)],
            "expires_in_hours": 72,
        },
    )
    assert replay.status_code == 201
    assert replay.json()["data"] == draft

    detail = await client.get(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{draft['id']}",
        headers=auth_headers(),
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["request"] == draft
    assert detail.json()["data"]["responses"] == []
    assert detail.json()["data"]["comparisons"] == []
    events = [event for event in adapter.mock_audit_events if event.contract_id == contract_id]
    assert events[-1].event_type == "ADJUSTMENT_DRAFT_CREATED"


async def test_draft_preserves_owner_confirmed_request_text_override(adjustment_context) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)
    review_item = selected_review_item(
        contract_id=contract_id,
        choice=SuggestionChoice.REQUEST,
    )
    adapter._mock_review_items[review_item.id] = review_item
    edited_text = "  계약기간을 1년으로 조정해 주시기를 요청드립니다.  "

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "review_item_ids": [str(review_item.id)],
            "request_text_overrides": {str(review_item.id): edited_text},
            "expires_in_hours": 72,
        },
    )

    assert response.status_code == 201
    item = response.json()["data"]["items"][0]
    assert item["review_item_id"] == str(review_item.id)
    assert item["request_text"] == edited_text.strip()


async def test_draft_persists_owner_selected_document_clause_with_server_evidence(
    adjustment_context,
) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)
    clause = completed_document_clause(adapter, contract_id=contract_id)
    request_text = "결과물 승인 기한을 5영업일로 명확히 적어 주세요."

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "review_item_ids": [],
            "manual_items": [
                {
                    "document_clause_id": str(clause.id),
                    "request_text": request_text,
                }
            ],
            "expires_in_hours": 72,
        },
    )

    assert response.status_code == 201
    draft = response.json()["data"]
    assert len(draft["items"]) == 1
    item = draft["items"][0]
    assert item["review_item_id"] != str(clause.id)
    assert item["user_choice"] == "REQUEST"
    assert item["request_text"] == request_text
    stored = adapter.mock_review_items[UUID(item["review_item_id"])]
    assert stored.original_text == clause.source_text
    assert stored.suggestion_request == request_text

    sent = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{draft['id']}/send",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"confirmed": True},
    )
    assert sent.status_code == 200
    token = sent.json()["data"]["public_url"].rsplit("/", maxsplit=1)[-1]
    public = await client.get(f"/api/v1/public/adjustment-requests/{token}")
    assert public.status_code == 200
    assert public.json()["data"]["items"][0]["request_text"] == request_text


async def test_draft_rejects_unknown_document_clause(adjustment_context) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)
    completed_document_clause(adapter, contract_id=contract_id)

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "manual_items": [
                {
                    "document_clause_id": str(uuid4()),
                    "request_text": "이 조항의 기한을 명확히 적어 주세요.",
                }
            ],
            "expires_in_hours": 72,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "payload",
    [
        {"expires_in_hours": 72},
        {
            "manual_items": [
                {"document_clause_id": str(uuid4()), "request_text": "   "},
            ],
            "expires_in_hours": 72,
        },
        {
            "review_item_ids": [str(uuid4()) for _ in range(4)],
            "manual_items": [
                {"document_clause_id": str(uuid4()), "request_text": "기한을 명확히 적어 주세요."},
            ],
            "expires_in_hours": 72,
        },
    ],
)
async def test_draft_rejects_invalid_combined_item_counts_and_manual_copy(
    adjustment_context,
    payload,
) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=uuid4()),
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        lambda item_id: {str(uuid4()): "선택하지 않은 항목"},
        lambda item_id: {str(item_id): "   "},
        lambda item_id: {str(item_id): "x" * 1201},
    ],
)
async def test_draft_rejects_invalid_request_text_overrides(
    adjustment_context,
    overrides,
) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)
    review_item = selected_review_item(
        contract_id=contract_id,
        choice=SuggestionChoice.REQUEST,
    )
    adapter._mock_review_items[review_item.id] = review_item

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "review_item_ids": [str(review_item.id)],
            "request_text_overrides": overrides(review_item.id),
            "expires_in_hours": 72,
        },
    )

    assert response.status_code == 422


async def test_send_freezes_items_transitions_contract_and_replays_safely(
    adjustment_context,
) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)
    review_item = selected_review_item(contract_id=contract_id, choice=SuggestionChoice.COMPROMISE)
    adapter._mock_review_items[review_item.id] = review_item
    draft = await create_draft(client, contract_id, [review_item.id])
    send_key = uuid4()
    path = f"/api/v1/contracts/{contract_id}/adjustment-requests/{draft['id']}/send"

    unconfirmed = await client.post(
        path,
        headers=auth_headers(idempotency_key=uuid4()),
        json={"confirmed": False},
    )
    assert unconfirmed.status_code == 422
    assert unconfirmed.headers["Cache-Control"] == "no-store"
    assert adapter.mock_contracts[contract_id].status == ContractStatus.REVIEW_REQUIRED

    sent = await client.post(
        path,
        headers=auth_headers(idempotency_key=send_key),
        json={"confirmed": True},
    )
    assert sent.status_code == 200
    assert sent.headers["Cache-Control"] == "no-store"
    body = sent.json()["data"]
    assert body["id"] == draft["id"]
    assert body["status"] == "SENT"
    assert body["public_url"].startswith("http://localhost:3000/r/")
    assert body["expires_at"] is not None
    assert adapter.mock_contracts[contract_id].status == ContractStatus.NEGOTIATING
    assert adapter.mock_review_items[review_item.id].status == ReviewItemStatus.SENT
    assert (
        adapter.mock_adjustment_requests[UUID(draft["id"])].status == AdjustmentRequestStatus.SENT
    )
    assert len(adapter.mock_public_tokens) == 1

    replay = await client.post(
        path,
        headers=auth_headers(idempotency_key=send_key),
        json={"confirmed": True},
    )
    assert replay.status_code == 200
    assert replay.headers["Cache-Control"] == "no-store"
    assert replay.json()["data"] == body
    events = [event for event in adapter.mock_audit_events if event.contract_id == contract_id]
    assert [event.event_type for event in events][-2:] == [
        "ADJUSTMENT_DRAFT_CREATED",
        "ADJUSTMENT_SENT",
    ]


async def test_draft_rejects_unselected_or_accept_review_items(adjustment_context) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)
    accept_item = selected_review_item(contract_id=contract_id, choice=SuggestionChoice.ACCEPT)
    unselected_item = replace(
        accept_item,
        id=uuid4(),
        user_choice=SuggestionChoice.REQUEST,
        status=ReviewItemStatus.UNREVIEWED,
    )
    adapter._mock_review_items[accept_item.id] = accept_item
    adapter._mock_review_items[unselected_item.id] = unselected_item

    for review_item in (accept_item, unselected_item):
        response = await client.post(
            f"/api/v1/contracts/{contract_id}/adjustment-requests",
            headers=auth_headers(idempotency_key=uuid4()),
            json={"review_item_ids": [str(review_item.id)], "expires_in_hours": 72},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_second_actual_send_is_rejected_with_no_store(adjustment_context) -> None:
    client, adapter = adjustment_context
    contract_id = await reviewed_contract(client, adapter)
    first_item = selected_review_item(contract_id=contract_id, choice=SuggestionChoice.REQUEST)
    second_item = selected_review_item(contract_id=contract_id, choice=SuggestionChoice.COMPROMISE)
    adapter._mock_review_items[first_item.id] = first_item
    adapter._mock_review_items[second_item.id] = second_item
    first_draft = await create_draft(client, contract_id, [first_item.id])
    first_path = f"/api/v1/contracts/{contract_id}/adjustment-requests/{first_draft['id']}/send"
    assert (
        await client.post(
            first_path,
            headers=auth_headers(idempotency_key=uuid4()),
            json={"confirmed": True},
        )
    ).status_code == 200

    second_draft = await create_draft(client, contract_id, [second_item.id])
    second_path = f"/api/v1/contracts/{contract_id}/adjustment-requests/{second_draft['id']}/send"
    response = await client.post(
        second_path,
        headers=auth_headers(idempotency_key=uuid4()),
        json={"confirmed": True},
    )

    assert response.status_code == 409
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
