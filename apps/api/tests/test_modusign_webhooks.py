from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.modusign import ModusignDocumentStatus
from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_modusign_webhook_service, get_supabase_adapter
from app.core.enums import ContractStatus, InternalSignatureStatus, ModusignStatus
from app.main import app
from app.repositories.contracts import ContractRecord
from app.repositories.signatures import SignatureRecord
from app.schemas.signatures import Signature
from app.services.webhooks import ModusignWebhookService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000071")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000072")
BEARER_TOKEN = "local-demo-owner-token"
WEBHOOK_SECRET = "test-modusign-webhook-secret"
NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class FakeModusignStatusAdapter:
    def __init__(self, document: ModusignDocumentStatus) -> None:
        self.document = document
        self.calls: list[str] = []

    async def get_document_status(self, *, document_id: str) -> ModusignDocumentStatus:
        self.calls.append(document_id)
        return self.document


@pytest.fixture
async def webhook_context():
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    contract_id = uuid4()
    adapter._mock_owned_contracts.add((OWNER_ID, contract_id))
    adapter._mock_contracts[contract_id] = ContractRecord(
        id=contract_id,
        owner_id=OWNER_ID,
        title="Webhook contract",
        counterparty_name="Agency",
        status=ContractStatus.READY_TO_SIGN,
        signed_date=None,
        start_date=None,
        end_date=None,
        termination_notice_date=None,
        renewal_type=None,
        total_amount=None,
        understood_term=None,
        renewal_decision=None,
        modusign_document_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    signature_id = uuid4()
    adapter._mock_signatures[signature_id] = SignatureRecord(
        signature=Signature(
            id=signature_id,
            contract_id=contract_id,
            status=InternalSignatureStatus.EDITING,
            modusign_status=ModusignStatus.DRAFT,
            modusign_draft_id="modusign-draft-id",
            requested_at=NOW,
        ),
        agreement_id=uuid4(),
        agreement_version=1,
        idempotency_key=uuid4(),
    )
    service = ModusignWebhookService(
        repository=adapter,
        modusign=FakeModusignStatusAdapter(
            ModusignDocumentStatus(
                id="modusign-document-id",
                status=ModusignStatus.ON_GOING,
                metadata=ModusignWebhookService.build_signature_metadata(
                    signature_id=signature_id,
                    webhook_secret=WEBHOOK_SECRET,
                ),
            )
        ),
        webhook_secret=WEBHOOK_SECRET,
        now=lambda: NOW,
    )

    async def override_adapter():
        return adapter

    async def override_webhook_service():
        return service

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_modusign_webhook_service] = override_webhook_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, adapter, service, contract_id, signature_id
    finally:
        app.dependency_overrides.clear()


def webhook_payload(*, event_id: str, event_type: str = "document_started") -> dict:
    return {
        "event": {"id": event_id, "type": event_type},
        "document": {
            "id": "modusign-document-id",
            "requester": {"email": "must-not-be-persisted@example.com"},
        },
    }


async def test_webhook_authenticates_deduplicates_and_reconciles_signature(webhook_context) -> None:
    client, adapter, service, contract_id, signature_id = webhook_context
    headers = {"X-Modusign-Webhook-Secret": WEBHOOK_SECRET}

    first = await client.post(
        "/api/v1/webhooks/modusign",
        headers=headers,
        json=webhook_payload(event_id="vendor-event-start"),
    )

    assert first.status_code == 204
    signature = adapter.mock_signatures[signature_id].signature
    assert signature.status == InternalSignatureStatus.SIGNING
    assert signature.modusign_status == ModusignStatus.ON_GOING
    assert signature.modusign_document_id == "modusign-document-id"
    assert signature.last_event_id == "event:vendor-event-start"
    assert adapter.mock_contracts[contract_id].status == ContractStatus.SIGNING
    assert [event.event_type for event in adapter.mock_audit_events] == ["SIGNATURE_STARTED"]
    stored = next(iter(adapter.mock_modusign_webhook_events.values()))
    assert stored.processed_at == NOW
    assert "must-not-be-persisted@example.com" not in str(stored)

    duplicate = await client.post(
        "/api/v1/webhooks/modusign",
        headers=headers,
        json=webhook_payload(event_id="vendor-event-start"),
    )

    assert duplicate.status_code == 204
    assert len(adapter.mock_modusign_webhook_events) == 1
    assert [event.event_type for event in adapter.mock_audit_events] == ["SIGNATURE_STARTED"]
    assert service._modusign.calls == ["modusign-document-id"]


async def test_terminal_status_wins_over_late_out_of_order_webhook(webhook_context) -> None:
    client, adapter, service, contract_id, signature_id = webhook_context
    headers = {"X-Modusign-Webhook-Secret": WEBHOOK_SECRET}
    status_adapter = service._modusign

    started = await client.post(
        "/api/v1/webhooks/modusign",
        headers=headers,
        json=webhook_payload(event_id="vendor-event-start"),
    )
    assert started.status_code == 204

    status_adapter.document = replace(
        status_adapter.document,
        status=ModusignStatus.COMPLETED,
    )
    completed = await client.post(
        "/api/v1/webhooks/modusign",
        headers=headers,
        json=webhook_payload(event_id="vendor-event-complete", event_type="document_all_signed"),
    )
    assert completed.status_code == 204
    assert (
        adapter.mock_signatures[signature_id].signature.status
        == InternalSignatureStatus.COMPLETED
    )
    assert adapter.mock_contracts[contract_id].status == ContractStatus.SIGNED

    status_adapter.document = replace(
        status_adapter.document,
        status=ModusignStatus.ON_GOING,
    )
    late = await client.post(
        "/api/v1/webhooks/modusign",
        headers=headers,
        json=webhook_payload(event_id="vendor-event-late"),
    )
    assert late.status_code == 204
    assert (
        adapter.mock_signatures[signature_id].signature.status
        == InternalSignatureStatus.COMPLETED
    )
    assert adapter.mock_contracts[contract_id].status == ContractStatus.SIGNED
    assert [event.event_type for event in adapter.mock_audit_events] == [
        "SIGNATURE_STARTED",
        "SIGNATURE_COMPLETED",
    ]


async def test_completed_status_recovers_when_started_webhook_arrives_late(webhook_context) -> None:
    client, adapter, service, contract_id, signature_id = webhook_context
    status_adapter = service._modusign
    status_adapter.document = replace(
        status_adapter.document,
        status=ModusignStatus.COMPLETED,
    )

    response = await client.post(
        "/api/v1/webhooks/modusign",
        headers={"X-Modusign-Webhook-Secret": WEBHOOK_SECRET},
        json=webhook_payload(event_id="vendor-event-complete", event_type="document_all_signed"),
    )

    assert response.status_code == 204
    assert (
        adapter.mock_signatures[signature_id].signature.status
        == InternalSignatureStatus.COMPLETED
    )
    assert adapter.mock_contracts[contract_id].status == ContractStatus.SIGNED
    assert [event.event_type for event in adapter.mock_audit_events] == ["SIGNATURE_COMPLETED"]


async def test_rejects_invalid_webhook_secret_without_persisting_event(webhook_context) -> None:
    client, adapter, _service, _contract_id, _signature_id = webhook_context

    response = await client.post(
        "/api/v1/webhooks/modusign",
        headers={"X-Modusign-Webhook-Secret": "wrong-secret"},
        json=webhook_payload(event_id="vendor-event-invalid"),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "WEBHOOK_AUTH_FAILED"
    assert not adapter.mock_modusign_webhook_events
