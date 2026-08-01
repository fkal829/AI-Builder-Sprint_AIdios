from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.modusign import ModusignAdapter, ModusignDocumentStatus
from app.adapters.supabase import MockAuditEvent, SupabaseAdapter
from app.api.dependencies import (
    get_contract_service,
    get_modusign_adapter,
    get_supabase_adapter,
)
from app.core.enums import (
    AdjustmentRequestStatus,
    ContractStatus,
    InternalSignatureStatus,
    ModusignStatus,
)
from app.main import app
from app.repositories.adjustments import AdjustmentRequestRecord
from app.repositories.documents import DocumentRecord
from app.repositories.signatures import SignatureRecord
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.signatures import Signature
from app.services.contracts import ContractService
from app.services.signature_reconciliation import SignatureReconciler
from app.services.webhooks import ModusignWebhookService

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

    # ContractService now reconciles pending signatures through the Modusign
    # adapter (see test_reconciles_pending_signatures_when_listing_contracts
    # below). Pin it to mock mode explicitly rather than letting DI fall back
    # to whatever MODUSIGN_MODE/API key happens to be in a developer's .env.
    async def override_modusign():
        return ModusignAdapter(account_email="", api_key="", mode="mock")

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_modusign_adapter] = override_modusign
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


async def test_contract_detail_returns_saved_understood_term(contract_context) -> None:
    client, _adapter = contract_context
    contract_id = UUID((await create_contract(client, "이해조건 재조회 계약"))["id"])
    detail_path = f"/api/v1/contracts/{contract_id}"

    before_save = await client.get(detail_path, headers=authorization_header())

    assert before_save.status_code == 200
    assert before_save.json()["data"]["understood_term"] is None

    payload = {
        "duration_text": "1년",
        "monthly_amount": 500_000,
        "total_amount": 6_000_000,
        "refund_text": "중도해지 시 일부 환불",
        "termination_text": "중도해지 가능",
        "source_type": "USER_MEMORY",
    }
    saved = await client.put(
        f"/api/v1/contracts/{contract_id}/understood-terms",
        headers=authorization_header(),
        json=payload,
    )
    detail = await client.get(detail_path, headers=authorization_header())

    assert saved.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["data"]["understood_term"] == {
        "contract_id": str(contract_id),
        **payload,
    }


async def test_deletes_contract_and_unsent_child_data(contract_context) -> None:
    client, adapter = contract_context
    contract_id = UUID((await create_contract(client, "삭제할 테스트 계약"))["id"])
    document_id = uuid4()
    storage_path = f"{OWNER_ID}/{contract_id}/{document_id}.pdf"
    created_at = datetime(2026, 8, 2, tzinfo=UTC)
    adapter._mock_documents[document_id] = DocumentRecord(
        id=document_id,
        contract_id=contract_id,
        type=DocumentType.CONTRACT,
        parse_status=DocumentParseStatus.COMPLETED,
        storage_path=storage_path,
        content_type="application/pdf",
        size_bytes=10,
        page_count=1,
        created_at=created_at,
    )
    adapter._mock_objects[storage_path] = b"test-pdf"
    adapter._mock_object_content_types[storage_path] = "application/pdf"
    request_id = uuid4()
    adapter._mock_adjustment_requests[request_id] = AdjustmentRequestRecord(
        id=request_id,
        contract_id=contract_id,
        status=AdjustmentRequestStatus.DRAFT,
        items=(),
        expires_in_hours=72,
        sent_at=None,
        expires_at=None,
        opened_at=None,
        responded_at=None,
        created_at=created_at,
        updated_at=created_at,
    )

    response = await client.delete(
        f"/api/v1/contracts/{contract_id}", headers=authorization_header()
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"contract_id": str(contract_id), "deleted": True}
    assert contract_id not in adapter.mock_contracts
    assert document_id not in adapter.mock_documents
    assert storage_path not in adapter.mock_objects
    assert request_id not in adapter.mock_adjustment_requests
    assert not [event for event in adapter.mock_audit_events if event.contract_id == contract_id]
    detail = await client.get(
        f"/api/v1/contracts/{contract_id}", headers=authorization_header()
    )
    assert detail.status_code == 404


@pytest.mark.parametrize(
    "status",
    [
        ContractStatus.ANALYZING,
        ContractStatus.REVIEW_REQUIRED,
        ContractStatus.NEGOTIATING,
    ],
)
async def test_deletes_each_pre_send_contract_status(contract_context, status) -> None:
    client, adapter = contract_context
    contract_id = UUID((await create_contract(client, f"{status.value} 삭제"))["id"])
    adapter._mock_contracts[contract_id] = replace(
        adapter._mock_contracts[contract_id], status=status
    )

    response = await client.delete(
        f"/api/v1/contracts/{contract_id}", headers=authorization_header()
    )

    assert response.status_code == 200
    assert contract_id not in adapter.mock_contracts


async def test_rejects_deletion_after_adjustment_was_sent(contract_context) -> None:
    client, adapter = contract_context
    contract_id = UUID((await create_contract(client, "조정 발송 계약"))["id"])
    adapter._mock_contracts[contract_id] = replace(
        adapter._mock_contracts[contract_id], status=ContractStatus.NEGOTIATING
    )
    sent_at = datetime(2026, 8, 2, tzinfo=UTC)
    request_id = uuid4()
    adapter._mock_adjustment_requests[request_id] = AdjustmentRequestRecord(
        id=request_id,
        contract_id=contract_id,
        status=AdjustmentRequestStatus.SENT,
        items=(),
        expires_in_hours=72,
        sent_at=sent_at,
        expires_at=sent_at.replace(day=5),
        opened_at=None,
        responded_at=None,
        created_at=sent_at,
        updated_at=sent_at,
    )

    response = await client.delete(
        f"/api/v1/contracts/{contract_id}", headers=authorization_header()
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert contract_id in adapter.mock_contracts
    assert request_id in adapter.mock_adjustment_requests


async def test_rejects_deletion_when_any_signature_attempt_exists(contract_context) -> None:
    client, adapter = contract_context
    contract_id = UUID((await create_contract(client, "서명 시도 계약"))["id"])
    signature_id = uuid4()
    adapter._mock_signatures[signature_id] = SignatureRecord(
        signature=Signature(
            id=signature_id,
            contract_id=contract_id,
            status=InternalSignatureStatus.EDITING,
            modusign_status=ModusignStatus.DRAFT,
            modusign_draft_id="protected-draft-id",
            requested_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
        agreement_id=uuid4(),
        agreement_version=1,
        idempotency_key=uuid4(),
    )

    response = await client.delete(
        f"/api/v1/contracts/{contract_id}", headers=authorization_header()
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert contract_id in adapter.mock_contracts


@pytest.mark.parametrize(
    "status",
    [
        ContractStatus.READY_TO_SIGN,
        ContractStatus.SIGNING,
        ContractStatus.SIGNED,
        ContractStatus.IN_PROGRESS,
        ContractStatus.COMPLETED,
        ContractStatus.RENEWAL_DUE,
    ],
)
async def test_rejects_deletion_for_protected_contract_status(contract_context, status) -> None:
    client, adapter = contract_context
    contract_id = UUID((await create_contract(client, f"{status.value} 보호"))["id"])
    adapter._mock_contracts[contract_id] = replace(
        adapter._mock_contracts[contract_id], status=status
    )

    response = await client.delete(
        f"/api/v1/contracts/{contract_id}", headers=authorization_header()
    )

    assert response.status_code == 409
    assert contract_id in adapter.mock_contracts


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


RECONCILE_WEBHOOK_SECRET = "test-reconcile-webhook-secret"


class FakeDocumentListModusignAdapter:
    """Stands in for Modusign after the user sent an embedded draft.

    The sent draft became a document with a *different* id and no webhook
    reached us, so the document is only findable by the metadata we attached
    when the draft was created.
    """

    def __init__(self, *, documents: list[ModusignDocumentStatus]) -> None:
        self.documents = documents
        self.listed = 0

    async def list_recent_documents(self, *, limit: int = 50) -> list[ModusignDocumentStatus]:
        self.listed += 1
        return self.documents

    async def get_document_status(self, *, document_id: str) -> ModusignDocumentStatus:
        for document in self.documents:
            if document.id == document_id:
                return document
        raise AssertionError("unexpected direct fetch")


async def test_reconciles_pending_signatures_when_listing_contracts(contract_context) -> None:
    """Simply reloading the contract list must reflect real signing progress,
    even for a contract nobody has opened the signature page for yet — the
    user should not have to guess which of many contracts finished signing."""
    client, adapter = contract_context
    signed_id = UUID((await create_contract(client, "서명 완료 계약"))["id"])
    untouched_id = UUID((await create_contract(client, "아직 서명 전 계약"))["id"])
    adapter._mock_contracts[signed_id] = replace(
        adapter._mock_contracts[signed_id], status=ContractStatus.READY_TO_SIGN
    )
    signature_id = uuid4()
    adapter._mock_signatures[signature_id] = SignatureRecord(
        signature=Signature(
            id=signature_id,
            contract_id=signed_id,
            status=InternalSignatureStatus.EDITING,
            modusign_status=ModusignStatus.DRAFT,
            modusign_draft_id="01KYZ1RCJ5SCBQ62HFTKWM26MF",
            requested_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        agreement_id=uuid4(),
        agreement_version=1,
        idempotency_key=uuid4(),
    )
    document_id = "dd655b70-8dcf-11f1-812b-d19927853d2e"

    fake_modusign = FakeDocumentListModusignAdapter(
        documents=[
            ModusignDocumentStatus(
                id=document_id,
                status=ModusignStatus.COMPLETED,
                metadata=ModusignWebhookService.build_signature_metadata(
                    signature_id=signature_id, webhook_secret=RECONCILE_WEBHOOK_SECRET
                ),
            )
        ]
    )

    async def override_contract_service():
        return ContractService(
            adapter,
            signatures=SignatureReconciler(
                repository=adapter,
                modusign=fake_modusign,
                webhook_secret=RECONCILE_WEBHOOK_SECRET,
            ),
        )

    app.dependency_overrides[get_contract_service] = override_contract_service

    response = await client.get("/api/v1/contracts", headers=authorization_header())

    assert response.status_code == 200
    contracts = {item["id"]: item for item in response.json()["data"]}
    assert contracts[str(signed_id)]["status"] == "SIGNED"
    assert contracts[str(untouched_id)]["status"] == "DRAFT"
    assert adapter.mock_contracts[signed_id].status == ContractStatus.SIGNED
    assert "SIGNATURE_COMPLETED" in [
        event.event_type
        for event in adapter.mock_audit_events
        if event.contract_id == signed_id
    ]

    # One listing serves the whole page: a DRAFT contract has no pending
    # signature, so it must not cost an extra vendor call.
    assert fake_modusign.listed == 1


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

    deletion = await client.delete(
        f"/api/v1/contracts/{foreign_contract}", headers=authorization_header()
    )
    assert deletion.status_code == 404
    assert deletion.json()["error"]["code"] == "NOT_FOUND"
    assert foreign_contract in adapter.mock_contracts


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


async def test_timeline_returns_contract_lifecycle_events(contract_context) -> None:
    client, adapter = contract_context
    contract_id = UUID((await create_contract(client, "계약 상태 타임라인"))["id"])
    created_at = datetime(2026, 7, 31, 1, tzinfo=UTC)
    expected_event_types = [
        "CONTRACT_STARTED",
        "CONTRACT_COMPLETED",
        "CONTRACT_RENEWAL_DUE",
    ]
    adapter._mock_audit_events.extend(
        MockAuditEvent(
            id=uuid4(),
            contract_id=contract_id,
            event_type=event_type,
            actor_type="SYSTEM",
            summary=None,
            created_at=created_at,
        )
        for event_type in expected_event_types
    )

    response = await client.get(
        f"/api/v1/contracts/{contract_id}/timeline",
        headers=authorization_header(),
    )

    assert response.status_code == 200
    returned_event_types = [
        event["event_type"]
        for event in response.json()["data"]
        if event["event_type"] in expected_event_types
    ]
    assert sorted(returned_event_types) == sorted(expected_event_types)


async def test_contract_apis_require_valid_owner_authentication(contract_context) -> None:
    client, _adapter = contract_context

    response = await client.get("/api/v1/contracts")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"


async def test_live_contract_detail_loads_understood_term(monkeypatch) -> None:
    contract_id = uuid4()
    contract_row = {
        "id": str(contract_id),
        "owner_id": str(OWNER_ID),
        "title": "Live 계약",
        "counterparty_name": "부산홍보대행",
        "status": "DRAFT",
        "signed_date": None,
        "start_date": None,
        "end_date": None,
        "termination_notice_date": None,
        "renewal_type": None,
        "total_amount": None,
        "modusign_document_id": None,
        "created_at": "2026-07-31T00:00:00+00:00",
        "updated_at": "2026-07-31T00:00:00+00:00",
    }
    understood_term_row = {
        "contract_id": str(contract_id),
        "duration_text": "1년",
        "monthly_amount": 500_000,
        "total_amount": 6_000_000,
        "refund_text": "중도해지 시 일부 환불",
        "termination_text": "중도해지 가능",
        "source_type": "USER_MEMORY",
    }

    class FakeResponse:
        def __init__(self, data) -> None:
            self.data = data

    class FakeQuery:
        def __init__(self, table_name: str) -> None:
            self.table_name = table_name

        def select(self, _columns: str):
            return self

        def eq(self, _column: str, _value: str):
            return self

        def limit(self, _count: int):
            return self

        def execute(self):
            if self.table_name == "contracts":
                return FakeResponse([contract_row])
            if self.table_name == "understood_terms":
                return FakeResponse([understood_term_row])
            if self.table_name == "renewal_decisions":
                return FakeResponse([])
            raise AssertionError(f"예상하지 못한 테이블 조회: {self.table_name}")

    class FakeClient:
        def __init__(self) -> None:
            self.tables: list[str] = []

        def table(self, table_name: str):
            self.tables.append(table_name)
            return FakeQuery(table_name)

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

    detail = await adapter.get(owner_id=OWNER_ID, contract_id=contract_id)

    assert detail is not None
    assert detail.understood_term is not None
    assert detail.understood_term.contract_id == contract_id
    assert detail.understood_term.duration_text == "1년"
    assert fake_client.tables == [
        "contracts",
        "understood_terms",
        "renewal_decisions",
    ]


def test_contract_detail_openapi_uses_understood_term_schema() -> None:
    contract_schema = app.openapi()["components"]["schemas"]["Contract"]
    understood_term_schema = contract_schema["properties"]["understood_term"]

    assert any(
        schema.get("$ref", "").endswith("/UnderstoodTerm")
        for schema in understood_term_schema["anyOf"]
    )
