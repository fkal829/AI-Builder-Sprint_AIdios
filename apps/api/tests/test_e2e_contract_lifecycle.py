"""C-11: representative P0 vertical flow, driven end to end through the real
HTTP API (no direct repository shortcuts for any step C owns). Only two gaps
outside C's ownership are patched directly on the mock repository, each
documented at the patch site:

- `contract.signed_date`: the mock Upstage evidence set (B's adapter) has no
  canned value for `CONTRACT_SIGNED_DATE`, so canonical promotion never fills
  it from analysis. A real contract PDF would carry this; our blank fixture
  PDF cannot.
- `contract.end_date` right before the renewal-decision step: the mock
  contract's real end date (2027-07-31, from mock evidence) is far outside
  any D-30/D-14/D-7 review window relative to the test's real wall clock, so
  it's nudged into the window to exercise C-9 as part of this flow.
"""

from dataclasses import replace
from datetime import date, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from app.adapters.modusign import ModusignAdapter, ModusignDocumentStatus
from app.adapters.solar import SolarReviewAdapter
from app.adapters.supabase import SupabaseAdapter
from app.adapters.upstage import UpstageAdapter
from app.api.dependencies import (
    get_analysis_service,
    get_modusign_adapter,
    get_modusign_webhook_service,
    get_supabase_adapter,
)
from app.core.enums import ContractStatus, InternalSignatureStatus, ModusignStatus
from app.main import app
from app.services.analysis import AnalysisService
from app.services.webhooks import ModusignWebhookService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000098")
BEARER_TOKEN = "e2e-lifecycle-owner-token-000000"
WEBHOOK_SECRET = "e2e-lifecycle-webhook-secret"
MODUSIGN_DOCUMENT_ID = "e2e-modusign-document-id"


def make_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


class _FakeModusignStatusAdapter:
    """Stands in for the vendor's GET /documents/{id} during webhook processing."""

    def __init__(self, document: ModusignDocumentStatus) -> None:
        self.document = document

    async def get_document_status(self, *, document_id: str) -> ModusignDocumentStatus:
        return self.document


@pytest.fixture
async def lifecycle_context(monkeypatch):
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    # The upload path's deterministic PDF page counter is exercised directly;
    # run only its thread handoff inline so the sandboxed test process does not
    # leave Python's default executor waiting during event-loop shutdown.
    monkeypatch.setattr("app.services.documents.asyncio.to_thread", run_inline)
    repository = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    analysis_service = AnalysisService(
        adapter=UpstageAdapter(mode="mock", api_key="", base_url="https://api.upstage.ai"),
        reviewer=SolarReviewAdapter(mode="mock", api_key="", base_url="https://api.upstage.ai"),
        contracts=repository,
        documents=repository,
        understood_terms=repository,
        analyses=repository,
        storage=repository,
    )
    # Real .env in this repo is wired to MODUSIGN_MODE=live with real vendor
    # credentials. Force mock mode here so an automated test run never makes
    # a live network call to Modusign.
    mock_modusign_adapter = ModusignAdapter(mode="mock", account_email="", api_key="")

    async def override_repository():
        return repository

    async def override_analysis_service():
        return analysis_service

    async def override_modusign_adapter():
        return mock_modusign_adapter

    app.dependency_overrides[get_supabase_adapter] = override_repository
    app.dependency_overrides[get_analysis_service] = override_analysis_service
    app.dependency_overrides[get_modusign_adapter] = override_modusign_adapter
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, repository
    finally:
        app.dependency_overrides.clear()


def auth_headers(*, idempotency_key: UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)
    return headers


async def test_representative_contract_flows_end_to_end_through_the_real_api(
    lifecycle_context,
) -> None:
    client, repository = lifecycle_context

    # 1. Create the contract.
    created = await client.post(
        "/api/v1/contracts",
        headers=auth_headers(),
        json={"title": "광안리 카페 SNS 광고대행 계약", "counterparty_name": "부산홍보대행"},
    )
    assert created.status_code == 201
    contract_id = UUID(created.json()["data"]["id"])
    assert created.json()["data"]["status"] == "DRAFT"

    # 2. Upload the original contract PDF.
    uploaded = await client.post(
        f"/api/v1/contracts/{contract_id}/documents",
        headers=auth_headers(),
        data={"type": "CONTRACT"},
        files={"file": ("contract.pdf", make_pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["data"]["id"]

    # 3. Save the owner's understood terms (deliberately different from the
    # mock extraction's canned values, so analysis produces MISMATCH signals).
    understood = await client.put(
        f"/api/v1/contracts/{contract_id}/understood-terms",
        headers=auth_headers(),
        json={
            "duration_text": "1년",
            "monthly_amount": 400_000,
            "total_amount": 4_800_000,
            "refund_text": "중도해지 시 일부 환불",
            "termination_text": "중도해지 가능",
            "source_type": "USER_MEMORY",
        },
    )
    assert understood.status_code == 200

    # 4. Start analysis. In mock mode the background task runs to completion
    # before this call returns (ASGITransport executes BackgroundTasks
    # in-process), so the repository already reflects COMPLETED afterward
    # even though the HTTP response body still shows the initial QUEUED state.
    analysis_started = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": document_id, "supporting_document_ids": []},
    )
    assert analysis_started.status_code == 202
    assert analysis_started.json()["data"]["status"] == "QUEUED"
    task_id = UUID(analysis_started.json()["data"]["id"])
    task = repository.mock_analysis_tasks[task_id]
    assert task.status.value == "COMPLETED"
    assert repository.mock_contracts[contract_id].status == ContractStatus.REVIEW_REQUIRED
    assert repository.mock_contracts[contract_id].total_amount == 6_000_000
    assert contract_id in repository.mock_obligations
    assert repository.mock_obligations[contract_id].status.value == "PENDING"

    # B's mock evidence has no CONTRACT_SIGNED_DATE candidate (see module
    # docstring), so canonical promotion never sets it. A real signed
    # contract PDF would carry this; patch it in directly here.
    repository._mock_contracts[contract_id] = replace(
        repository._mock_contracts[contract_id],
        signed_date=date(2026, 8, 1),
    )

    # 5. Fetch the analysis result via the real GET endpoint and pick 3 of
    # the 18 generated review items to drive through adjustment/confirm.
    analysis_result = await client.get(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(),
    )
    assert analysis_result.status_code == 200
    review_items = analysis_result.json()["data"]["result"]["review_items"]
    assert len(review_items) == 18
    accepted_item, countered_item, rejected_item = (
        review_items[0]["id"],
        review_items[1]["id"],
        review_items[2]["id"],
    )

    # 6. Select the 3 items (COMPROMISE for the one headed to a
    # counterproposal, REQUEST for the other two).
    for item_id, choice in (
        (accepted_item, "REQUEST"),
        (countered_item, "COMPROMISE"),
        (rejected_item, "REQUEST"),
    ):
        patched = await client.patch(
            f"/api/v1/contracts/{contract_id}/review-items/{item_id}",
            headers=auth_headers(),
            json={"user_choice": choice},
        )
        assert patched.status_code == 200
        assert patched.json()["data"]["status"] == "SELECTED"

    # 7. Draft the adjustment request from those 3 items.
    draft = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "review_item_ids": [accepted_item, countered_item, rejected_item],
            "expires_in_hours": 72,
        },
    )
    assert draft.status_code == 201
    adjustment_id = draft.json()["data"]["id"]
    assert draft.json()["data"]["status"] == "DRAFT"

    # 8. Send it — this is the explicit, user-confirmed dispatch step.
    sent = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_id}/send",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"confirmed": True},
    )
    assert sent.status_code == 200
    assert sent.json()["data"]["status"] == "SENT"
    assert repository.mock_contracts[contract_id].status == ContractStatus.NEGOTIATING
    token = sent.json()["data"]["public_url"].rsplit("/", maxsplit=1)[-1]

    # 9. Agency opens the public link and views the request (no auth).
    opened = await client.get(f"/api/v1/public/adjustment-requests/{token}")
    assert opened.status_code == 200
    public_items = opened.json()["data"]["items"]
    assert len(public_items) == 3
    public_id_by_review_item = dict(
        zip(
            [accepted_item, countered_item, rejected_item],
            (item["item_id"] for item in public_items),
            strict=True,
        )
    )

    # 10. Agency responds: accept one, counter one, reject one.
    responded = await client.post(
        f"/api/v1/public/adjustment-requests/{token}/responses",
        json={
            "responses": [
                {
                    "item_id": public_id_by_review_item[accepted_item],
                    "decision": "ACCEPT",
                    "counter_text": None,
                    "reason": None,
                },
                {
                    "item_id": public_id_by_review_item[countered_item],
                    "decision": "COUNTER",
                    "counter_text": "촬영 안전 조항은 유지하되 통보 기한을 7일로 조정 요청합니다.",
                    "reason": "현장 일정상 30일 전 통보는 어렵습니다.",
                },
                {
                    "item_id": public_id_by_review_item[rejected_item],
                    "decision": "REJECT",
                    "counter_text": None,
                    "reason": "원계약 조건을 유지하고 싶습니다.",
                },
            ]
        },
    )
    assert responded.status_code == 201
    assert responded.json()["data"] == {"submitted": True}

    # Duplicate submission on the same token must be rejected (idempotency
    # boundary explicitly called out in C-11's required-test list).
    duplicate_response = await client.post(
        f"/api/v1/public/adjustment-requests/{token}/responses",
        json={
            "responses": [
                {
                    "item_id": public_id_by_review_item[accepted_item],
                    "decision": "ACCEPT",
                    "counter_text": None,
                    "reason": None,
                },
                {
                    "item_id": public_id_by_review_item[countered_item],
                    "decision": "ACCEPT",
                    "counter_text": None,
                    "reason": None,
                },
                {
                    "item_id": public_id_by_review_item[rejected_item],
                    "decision": "ACCEPT",
                    "counter_text": None,
                    "reason": None,
                },
            ]
        },
    )
    assert duplicate_response.status_code == 409

    # 11. Owner confirms the final clauses.
    confirmed = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-confirmation",
        headers=auth_headers(),
        json={
            "adjustment_request_id": adjustment_id,
            "confirmed_items": [
                {"review_item_id": accepted_item, "resolution": "ACCEPT_REQUEST"},
                {"review_item_id": countered_item, "resolution": "ACCEPT_COUNTERPROPOSAL"},
                {"review_item_id": rejected_item, "resolution": "KEEP_ORIGINAL"},
            ],
            "confirmed": True,
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "CONFIRMED"
    assert repository.mock_contracts[contract_id].status == ContractStatus.READY_TO_SIGN

    # A rejected transition: an already-CONFIRMED request cannot be resent.
    resend_after_confirm = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_id}/send",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"confirmed": True},
    )
    assert resend_after_confirm.status_code == 409

    # 12. Generate the agreement PDF from the confirmed clauses.
    agreement_created = await client.post(
        f"/api/v1/contracts/{contract_id}/agreement",
        headers=auth_headers(idempotency_key=uuid4()),
    )
    assert agreement_created.status_code == 201
    agreement = agreement_created.json()["data"]
    assert agreement["contract_id"] == str(contract_id)
    assert len(agreement["clauses"]) == 3

    agreement_fetched = await client.get(
        f"/api/v1/contracts/{contract_id}/agreement",
        headers=auth_headers(),
    )
    assert agreement_fetched.status_code == 200
    assert agreement_fetched.json()["data"] == agreement

    # 13. Create the embedded signature draft (mock Modusign, no live call).
    embedded_draft = await client.post(
        f"/api/v1/contracts/{contract_id}/signature-embedded-drafts",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "agreement_id": agreement["id"],
            "agreement_version": agreement["version"],
            "confirmed": True,
            "signers": [
                {
                    "role": "OWNER",
                    "name": "김대표",
                    "signing_method": {"type": "EMAIL", "value": "owner@example.com"},
                },
                {
                    "role": "AGENCY",
                    "name": "박대행",
                    "signing_method": {"type": "EMAIL", "value": "agency@example.com"},
                },
            ],
        },
    )
    assert embedded_draft.status_code == 201
    signature_id = UUID(embedded_draft.json()["data"]["signature"]["id"])
    assert embedded_draft.json()["data"]["signature"]["status"] == "EDITING"
    assert repository.mock_contracts[contract_id].status == ContractStatus.READY_TO_SIGN

    # 14. The user places signature fields and sends in the Modusign editor.
    # Modusign then calls our webhook. Wire a fake vendor status double that
    # carries this real signature_id's HMAC proof, matching exactly what
    # ModusignAdapter.create_embedded_draft would have sent as metadata in
    # live mode.
    fake_status_adapter = _FakeModusignStatusAdapter(
        ModusignDocumentStatus(
            id=MODUSIGN_DOCUMENT_ID,
            status=ModusignStatus.ON_GOING,
            metadata=ModusignWebhookService.build_signature_metadata(
                signature_id=signature_id,
                webhook_secret=WEBHOOK_SECRET,
            ),
        )
    )
    webhook_service = ModusignWebhookService(
        repository=repository,
        modusign=fake_status_adapter,
        webhook_secret=WEBHOOK_SECRET,
    )

    async def override_webhook_service():
        return webhook_service

    app.dependency_overrides[get_modusign_webhook_service] = override_webhook_service

    started_webhook = await client.post(
        "/api/v1/webhooks/modusign",
        headers={"X-Modusign-Webhook-Secret": WEBHOOK_SECRET},
        json={
            "event": {"id": "e2e-event-start", "type": "document_started"},
            "document": {"id": MODUSIGN_DOCUMENT_ID},
        },
    )
    assert started_webhook.status_code == 204
    assert (
        repository.mock_signatures[signature_id].signature.status == InternalSignatureStatus.SIGNING
    )
    assert repository.mock_contracts[contract_id].status == ContractStatus.SIGNING

    # A rejected webhook: wrong secret must never touch state.
    wrong_secret = await client.post(
        "/api/v1/webhooks/modusign",
        headers={"X-Modusign-Webhook-Secret": "not-the-secret"},
        json={
            "event": {"id": "e2e-event-bad-secret", "type": "document_started"},
            "document": {"id": MODUSIGN_DOCUMENT_ID},
        },
    )
    assert wrong_secret.status_code == 401
    assert (
        repository.mock_signatures[signature_id].signature.status == InternalSignatureStatus.SIGNING
    )

    # Duplicate delivery of the same start event must not create a second
    # audit event or change state again.
    audit_events_before_duplicate = len(repository.mock_audit_events)
    duplicate_webhook = await client.post(
        "/api/v1/webhooks/modusign",
        headers={"X-Modusign-Webhook-Secret": WEBHOOK_SECRET},
        json={
            "event": {"id": "e2e-event-start", "type": "document_started"},
            "document": {"id": MODUSIGN_DOCUMENT_ID},
        },
    )
    assert duplicate_webhook.status_code == 204
    assert len(repository.mock_audit_events) == audit_events_before_duplicate

    fake_status_adapter.document = replace(
        fake_status_adapter.document, status=ModusignStatus.COMPLETED
    )
    completed_webhook = await client.post(
        "/api/v1/webhooks/modusign",
        headers={"X-Modusign-Webhook-Secret": WEBHOOK_SECRET},
        json={
            "event": {"id": "e2e-event-complete", "type": "document_all_signed"},
            "document": {"id": MODUSIGN_DOCUMENT_ID},
        },
    )
    assert completed_webhook.status_code == 204
    assert (
        repository.mock_signatures[signature_id].signature.status
        == InternalSignatureStatus.COMPLETED
    )
    assert repository.mock_contracts[contract_id].status == ContractStatus.SIGNED

    # 15. Representative obligation is still there from step 4, unaffected
    # by the signing flow.
    obligations = await client.get(
        f"/api/v1/contracts/{contract_id}/obligations",
        headers=auth_headers(),
    )
    assert obligations.status_code == 200
    assert len(obligations.json()["data"]) == 1
    assert obligations.json()["data"][0]["status"] == "PENDING"

    # 16. Dashboard reflects the whole flow: one signed/committed contract,
    # the 3 confirmed clauses split agreed/rejected, 15 signals still open,
    # 1 pending obligation.
    dashboard = await client.get("/api/v1/dashboard", headers=auth_headers())
    assert dashboard.status_code == 200
    data = dashboard.json()["data"]
    assert data["total"] == 1
    assert data["signing"] == 0
    assert data["completed"] == 0
    assert data["total_committed"] == 6_000_000
    assert data["adjustment_requested_clauses"] == 3
    assert data["adjustment_agreed_clauses"] == 2
    assert data["adjustment_rejected_clauses"] == 1
    assert data["obligation_pending"] == 1
    assert data["unresolved_signals"] == 15
    assert data["most_common_signal"] == "MISSING"

    # 17. Renewal signal: nudge end_date into the D-30 review window
    # (relative to the test's real wall clock — see module docstring) and
    # confirm the renewal-decision endpoint and dashboard's expiring_soon
    # both pick it up as part of the same lifecycle.
    repository._mock_contracts[contract_id] = replace(
        repository._mock_contracts[contract_id],
        end_date=date.today() + timedelta(days=10),
    )
    renewal = await client.put(
        f"/api/v1/contracts/{contract_id}/renewal-decision",
        headers=auth_headers(),
        json={"decision": "RENEW_SAME_TERMS", "confirmed": True},
    )
    assert renewal.status_code == 200
    assert renewal.json()["data"]["decision"] == "RENEW_SAME_TERMS"

    dashboard_after_renewal_signal = await client.get("/api/v1/dashboard", headers=auth_headers())
    assert dashboard_after_renewal_signal.json()["data"]["expiring_soon"] == 1
