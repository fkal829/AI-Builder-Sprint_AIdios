import json
from base64 import b64decode
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response

from app.adapters.modusign import ModusignAdapter, ModusignAdapterError
from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_modusign_adapter, get_supabase_adapter
from app.core.enums import ContractStatus, InternalSignatureStatus, ModusignStatus
from app.main import app
from app.repositories.agreements import AgreementRecord
from app.schemas.agreements import (
    AGREEMENT_TITLE,
    Agreement,
    AgreementClause,
    AgreementConditionSummary,
    OriginalContractReference,
)
from app.schemas.signatures import SignatureSigner

OWNER_ID = UUID("00000000-0000-4000-8000-000000000027")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000046")
BEARER_TOKEN = "local-demo-owner-token"


class FailingModusignAdapter:
    async def create_embedded_draft(self, **_kwargs):
        raise ModusignAdapterError("vendor unavailable")


@pytest.fixture
async def signature_context():
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    modusign = ModusignAdapter(
        account_email="",
        api_key="",
        mode="mock",
    )

    async def override_adapter():
        return adapter

    async def override_modusign():
        return modusign

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_modusign_adapter] = override_modusign
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


async def ready_contract_with_agreement(
    client: AsyncClient,
    adapter: SupabaseAdapter,
) -> tuple[UUID, Agreement]:
    created = await client.post(
        "/api/v1/contracts",
        headers=owner_headers(),
        json={"title": "Signature contract", "counterparty_name": "Agency"},
    )
    assert created.status_code == 201
    contract_id = UUID(created.json()["data"]["id"])
    contract = replace(
        adapter._mock_contracts[contract_id],
        status=ContractStatus.READY_TO_SIGN,
        signed_date=date(2026, 7, 1),
    )
    adapter._mock_contracts[contract_id] = contract
    agreement = Agreement(
        id=uuid4(),
        version=1,
        contract_id=contract_id,
        title=AGREEMENT_TITLE,
        original_contract=OriginalContractReference(
            title=contract.title,
            signed_date=date(2026, 7, 1),
            document_id=uuid4(),
        ),
        condition_summary=AgreementConditionSummary(
            term_and_payment="Verified term and payment.",
            deliverables_and_reporting="Verified deliverables.",
            termination_and_renewal="Verified renewal.",
            rights_safety_and_liability="Verified safety.",
        ),
        clauses=[
            AgreementClause(
                review_item_id=uuid4(),
                category="TERM_AND_PAYMENT",
                outcome="AGREED",
                disposition="AGREED",
                before="Before",
                after="After",
            )
        ],
        unchanged_terms_policy="Unchanged terms remain effective.",
        signature_roles=["OWNER", "AGENCY"],
    )
    adapter._mock_agreements[contract_id] = AgreementRecord(
        agreement=agreement,
        adjustment_request_id=uuid4(),
        pdf_storage_path=f"{OWNER_ID}/{contract_id}/agreements/{agreement.id}/v1/source.pdf",
        pdf_sha256=sha256(b"%PDF-1.4 test PDF").hexdigest(),
        pdf_size_bytes=17,
        pdf_page_count=1,
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    await adapter.upload_private_object(
        path=adapter._mock_agreements[contract_id].pdf_storage_path,
        content=b"%PDF-1.4 test PDF",
        content_type="application/pdf",
    )
    return contract_id, agreement


def request_payload(agreement: Agreement) -> dict:
    return {
        "agreement_id": str(agreement.id),
        "agreement_version": agreement.version,
        "confirmed": True,
        "signers": [
            {
                "role": "OWNER",
                "name": "Owner Name",
                "signing_method": {"type": "EMAIL", "value": "owner@example.com"},
            },
            {
                "role": "AGENCY",
                "name": "Agency Name",
                "signing_method": {"type": "KAKAO", "value": "01012345678"},
            },
        ],
    }


async def test_creates_embedded_draft_without_contacts_or_auto_sending(signature_context) -> None:
    client, adapter = signature_context
    contract_id, agreement = await ready_contract_with_agreement(client, adapter)
    key = uuid4()
    path = f"/api/v1/contracts/{contract_id}/signature-embedded-drafts"

    created = await client.post(
        path,
        headers=owner_headers(idempotency_key=key),
        json=request_payload(agreement),
    )

    assert created.status_code == 201
    draft = created.json()["data"]
    signature = draft["signature"]
    assert signature["status"] == "EDITING"
    assert signature["modusign_status"] == "DRAFT"
    assert signature["modusign_draft_id"].startswith("mock-modusign-draft-")
    assert draft["editor_url"].startswith("https://mock.modusign.local/embedded-draft/")
    assert created.headers["Cache-Control"] == "no-store"
    assert "owner@example.com" not in created.text
    assert "01012345678" not in created.text
    assert adapter.mock_contracts[contract_id].status == ContractStatus.READY_TO_SIGN
    assert (
        [event.event_type for event in adapter.mock_audit_events][-1]
        == "SIGNATURE_DRAFT_CREATED"
    )

    replay = await client.post(
        path,
        headers=owner_headers(idempotency_key=key),
        json=request_payload(agreement),
    )
    assert replay.status_code == 409
    assert len(adapter.mock_signatures) == 1

    retrieved = await client.get(
        f"/api/v1/contracts/{contract_id}/signature",
        headers=owner_headers(),
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["data"] == signature


async def test_rejects_invalid_signer_set_and_preserves_ready_contract(signature_context) -> None:
    client, adapter = signature_context
    contract_id, agreement = await ready_contract_with_agreement(client, adapter)
    payload = request_payload(agreement)
    payload["signers"][1]["role"] = "OWNER"

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/signature-embedded-drafts",
        headers=owner_headers(idempotency_key=uuid4()),
        json=payload,
    )

    assert response.status_code == 422
    assert adapter.mock_contracts[contract_id].status == ContractStatus.READY_TO_SIGN
    assert not adapter.mock_signatures


async def test_vendor_failure_is_recorded_without_starting_contract(signature_context) -> None:
    client, adapter = signature_context
    contract_id, agreement = await ready_contract_with_agreement(client, adapter)

    async def override_modusign():
        return FailingModusignAdapter()

    app.dependency_overrides[get_modusign_adapter] = override_modusign
    key = uuid4()
    response = await client.post(
        f"/api/v1/contracts/{contract_id}/signature-embedded-drafts",
        headers=owner_headers(idempotency_key=key),
        json=request_payload(agreement),
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODUSIGN_REQUEST_FAILED"
    assert adapter.mock_contracts[contract_id].status == ContractStatus.READY_TO_SIGN
    signature = next(iter(adapter.mock_signatures.values())).signature
    assert signature.status == InternalSignatureStatus.FAILED
    assert signature.modusign_document_id is None

    repeated = await client.post(
        f"/api/v1/contracts/{contract_id}/signature-embedded-drafts",
        headers=owner_headers(idempotency_key=key),
        json=request_payload(agreement),
    )
    assert repeated.status_code == 502
    assert len(adapter.mock_signatures) == 1


async def test_tampered_stored_agreement_pdf_is_never_sent_to_modusign(signature_context) -> None:
    client, adapter = signature_context
    contract_id, agreement = await ready_contract_with_agreement(client, adapter)
    stored = adapter.mock_agreements[contract_id]
    adapter._mock_objects[stored.pdf_storage_path] = b"%PDF-1.4 altered artifact"

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/signature-embedded-drafts",
        headers=owner_headers(idempotency_key=uuid4()),
        json=request_payload(agreement),
    )

    assert response.status_code == 502
    assert adapter.mock_signatures == {}


async def test_live_adapter_creates_embedded_draft_with_pdf_and_basic_auth() -> None:
    captured: dict[str, object] = {}

    def handler(request: Request) -> Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return Response(
            201,
            json={
                "id": "vendor-draft-id",
                "expiry": "2026-08-01T12:00:00.000Z",
                "embeddedUrl": "https://app.modusign.co.kr/embedded-draft/test?at=secret",
            },
        )

    agreement = Agreement.model_construct(id=uuid4(), version=1, title=AGREEMENT_TITLE)
    signer = SignatureSigner.model_validate(request_payload(agreement)["signers"][0])
    async with AsyncClient(
        base_url="https://api.modusign.co.kr",
        transport=MockTransport(handler),
    ) as http_client:
        modusign = ModusignAdapter(
            account_email="account@example.com",
            api_key="test-key",
            mode="live",
            client=http_client,
        )
        draft = await modusign.create_embedded_draft(
            document_title=f"{agreement.title} v{agreement.version}",
            document_pdf=b"%PDF-1.4 test PDF",
            signers=[signer],
            redirect_url="https://app.example.com/contracts/signature-complete",
        )

    assert draft.id == "vendor-draft-id"
    assert draft.expires_at == datetime(2026, 8, 1, 12, tzinfo=UTC)
    assert captured["path"] == "/embedded-drafts"
    assert str(captured["authorization"]).startswith("Basic ")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["redirectUrl"] == "https://app.example.com/contracts/signature-complete"
    assert body["file"]["extension"] == "pdf"
    assert b64decode(body["file"]["base64"]).startswith(b"%PDF-")
    participant = body["participants"][0]
    assert participant["type"] == "SIGNER"
    assert participant["role"] == "OWNER"
    assert participant["signingOrder"] == 1


async def test_live_adapter_reads_document_status_and_metadata() -> None:
    def handler(request: Request) -> Response:
        assert request.url.path == "/documents/vendor-document-id"
        return Response(
            200,
            json={
                "id": "vendor-document-id",
                "status": "ON_GOING",
                "metadatas": [
                    {"key": "aidos_signature_id", "value": "signature-id"},
                    {"key": "aidos_signature_proof", "value": "proof"},
                ],
            },
        )

    async with AsyncClient(
        base_url="https://api.modusign.co.kr",
        transport=MockTransport(handler),
    ) as http_client:
        modusign = ModusignAdapter(
            account_email="account@example.com",
            api_key="test-key",
            mode="live",
            client=http_client,
        )
        document = await modusign.get_document_status(document_id="vendor-document-id")

    assert document.id == "vendor-document-id"
    assert document.status == ModusignStatus.ON_GOING
    assert document.metadata == {
        "aidos_signature_id": "signature-id",
        "aidos_signature_proof": "proof",
    }
