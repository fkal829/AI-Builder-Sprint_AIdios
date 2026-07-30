from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_supabase_adapter
from app.core.enums import (
    AdjustmentRequestStatus,
    ContractStatus,
    ReviewItemStatus,
    SuggestionChoice,
)
from app.main import app
from app.repositories.adjustments import ReviewItemForAdjustment
from app.repositories.documents import DocumentRecord
from app.schemas.documents import DocumentParseStatus, DocumentType

OWNER_ID = UUID("00000000-0000-4000-8000-000000000026")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000045")
BEARER_TOKEN = "local-demo-owner-token"


@pytest.fixture
async def agreement_context():
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


def owner_headers(*, idempotency_key: UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)
    return headers


async def responded_adjustment(
    client: AsyncClient,
    adapter: SupabaseAdapter,
    *,
    decisions: list[str],
) -> tuple[UUID, UUID, list[ReviewItemForAdjustment]]:
    contract_response = await client.post(
        "/api/v1/contracts",
        headers=owner_headers(),
        json={"title": "합의서 생성 계약", "counterparty_name": "부산 대행사"},
    )
    assert contract_response.status_code == 201
    contract_id = UUID(contract_response.json()["data"]["id"])
    adapter._mock_contracts[contract_id] = replace(
        adapter._mock_contracts[contract_id],
        status=ContractStatus.REVIEW_REQUIRED,
    )
    review_items = [
        ReviewItemForAdjustment(
            id=uuid4(),
            contract_id=contract_id,
            status=ReviewItemStatus.SELECTED,
            user_choice=SuggestionChoice.REQUEST,
            suggestion_compromise="절충 요청 문구",
            suggestion_request=f"수정 요청 문구 {index + 1}",
            original_text=f"원계약 조항 {index + 1}",
        )
        for index in range(len(decisions))
    ]
    for item in review_items:
        adapter._mock_review_items[item.id] = item
    draft = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=owner_headers(idempotency_key=uuid4()),
        json={
            "review_item_ids": [str(item.id) for item in review_items],
            "expires_in_hours": 72,
        },
    )
    assert draft.status_code == 201
    adjustment_id = UUID(draft.json()["data"]["id"])
    sent = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_id}/send",
        headers=owner_headers(idempotency_key=uuid4()),
        json={"confirmed": True},
    )
    assert sent.status_code == 200
    token = sent.json()["data"]["public_url"].rsplit("/", maxsplit=1)[-1]
    public = await client.get(f"/api/v1/public/adjustment-requests/{token}")
    public_items = public.json()["data"]["items"]
    responses = []
    for public_item, decision in zip(public_items, decisions, strict=True):
        if decision == "ACCEPT":
            responses.append(
                {
                    "item_id": public_item["item_id"],
                    "decision": "ACCEPT",
                    "counter_text": None,
                    "reason": None,
                }
            )
        elif decision == "COUNTER":
            responses.append(
                {
                    "item_id": public_item["item_id"],
                    "decision": "COUNTER",
                    "counter_text": "대행사 역제안 문구",
                    "reason": "일정과 비용을 함께 고려해야 합니다.",
                }
            )
        else:
            responses.append(
                {
                    "item_id": public_item["item_id"],
                    "decision": "REJECT",
                    "counter_text": None,
                    "reason": "해당 변경은 수용하기 어렵습니다.",
                }
            )
    submitted = await client.post(
        f"/api/v1/public/adjustment-requests/{token}/responses",
        json={"responses": responses},
    )
    assert submitted.status_code == 201
    return contract_id, adjustment_id, review_items


async def test_confirmation_resolves_items_and_creates_deterministic_agreement(
    agreement_context,
) -> None:
    client, adapter = agreement_context
    contract_id, adjustment_id, review_items = await responded_adjustment(
        client,
        adapter,
        decisions=["ACCEPT", "COUNTER"],
    )

    confirmed = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-confirmation",
        headers=owner_headers(),
        json={
            "adjustment_request_id": str(adjustment_id),
            "confirmed_items": [
                {"review_item_id": str(review_items[0].id), "resolution": "ACCEPT_REQUEST"},
                {
                    "review_item_id": str(review_items[1].id),
                    "resolution": "ACCEPT_COUNTERPROPOSAL",
                },
            ],
            "confirmed": True,
        },
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "CONFIRMED"
    assert adapter.mock_contracts[contract_id].status == ContractStatus.READY_TO_SIGN
    assert adapter.mock_review_items[review_items[0].id].status == ReviewItemStatus.RESOLVED
    assert adapter.mock_review_items[review_items[1].id].status == ReviewItemStatus.RESOLVED
    assert (
        adapter.mock_adjustment_requests[adjustment_id].status
        == AdjustmentRequestStatus.CONFIRMED
    )

    missing_prerequisite = await client.post(
        f"/api/v1/contracts/{contract_id}/agreement",
        headers=owner_headers(idempotency_key=uuid4()),
    )
    assert missing_prerequisite.status_code == 409
    assert missing_prerequisite.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    adapter._mock_contracts[contract_id] = replace(
        adapter._mock_contracts[contract_id],
        signed_date=date(2026, 7, 1),
    )
    document_id = uuid4()
    adapter._mock_documents[document_id] = DocumentRecord(
        id=document_id,
        contract_id=contract_id,
        type=DocumentType.CONTRACT,
        parse_status=DocumentParseStatus.COMPLETED,
        storage_path=f"contracts/{contract_id}/{document_id}.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        page_count=1,
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    agreement_key = uuid4()
    created = await client.post(
        f"/api/v1/contracts/{contract_id}/agreement",
        headers=owner_headers(idempotency_key=agreement_key),
    )

    assert created.status_code == 201
    agreement = created.json()["data"]
    assert agreement["title"] == "광고대행 계약조건 변경·확인 합의서"
    assert agreement["version"] == 1
    assert agreement["original_contract"]["document_id"] == str(document_id)
    assert agreement["original_contract"]["signed_date"] == "2026-07-01"
    assert [clause["outcome"] for clause in agreement["clauses"]] == ["AGREED", "AGREED"]
    assert agreement["clauses"][0]["after"] == "수정 요청 문구 1"
    assert agreement["clauses"][1]["after"] == "대행사 역제안 문구"
    assert "추가 확인 필요" in agreement["condition_summary"]["deliverables_and_reporting"]
    assert agreement["signature_roles"] == ["OWNER", "AGENCY"]

    replay = await client.post(
        f"/api/v1/contracts/{contract_id}/agreement",
        headers=owner_headers(idempotency_key=agreement_key),
    )
    assert replay.status_code == 201
    assert replay.json()["data"] == agreement
    assert len(adapter.mock_agreements) == 1
    assert [
        event.event_type for event in adapter.mock_audit_events if event.contract_id == contract_id
    ][-1] == "AGREEMENT_CREATED"

    fetched = await client.get(
        f"/api/v1/contracts/{contract_id}/agreement",
        headers=owner_headers(),
    )
    assert fetched.status_code == 200
    assert fetched.json()["data"] == agreement


async def test_keep_original_preserves_rejection_reason_and_rejects_invalid_resolution(
    agreement_context,
) -> None:
    client, adapter = agreement_context
    contract_id, adjustment_id, review_items = await responded_adjustment(
        client,
        adapter,
        decisions=["REJECT"],
    )

    invalid = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-confirmation",
        headers=owner_headers(),
        json={
            "adjustment_request_id": str(adjustment_id),
            "confirmed_items": [
                {"review_item_id": str(review_items[0].id), "resolution": "ACCEPT_REQUEST"}
            ],
            "confirmed": True,
        },
    )
    assert invalid.status_code == 409
    assert (
        adapter.mock_adjustment_requests[adjustment_id].status
        == AdjustmentRequestStatus.RESPONDED
    )

    confirmed = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-confirmation",
        headers=owner_headers(),
        json={
            "adjustment_request_id": str(adjustment_id),
            "confirmed_items": [
                {"review_item_id": str(review_items[0].id), "resolution": "KEEP_ORIGINAL"}
            ],
            "confirmed": True,
        },
    )
    assert confirmed.status_code == 200
    assert adapter.mock_review_items[review_items[0].id].status == ReviewItemStatus.KEPT_ORIGINAL
    final_clause = adapter._mock_final_clauses[adjustment_id][0]
    assert final_clause.disposition == "REJECTED"
    assert final_clause.reason == "해당 변경은 수용하기 어렵습니다."
