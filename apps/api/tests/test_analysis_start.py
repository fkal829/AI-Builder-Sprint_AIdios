import asyncio
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from app.adapters.base import ParsedDocument, ParsedPage
from app.adapters.supabase import SupabaseAdapter
from app.adapters.upstage import UpstageAdapter, UpstageExtractionError
from app.api.dependencies import get_analysis_service, get_supabase_adapter
from app.core.enums import AnalysisStatus, ContractStatus, ExtractedField
from app.main import app
from app.services.analysis import AnalysisService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"


def make_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


class AlwaysInvalidExtractAdapter:
    def __init__(self) -> None:
        self.extract_calls = 0

    async def parse_document(self, *, content: bytes, content_type: str) -> ParsedDocument:
        return ParsedDocument(
            pages=(ParsedPage(number=1, text="테스트 계약 원문"),),
            model="fake-parse",
        )

    async def extract_terms(
        self,
        *,
        content: bytes,
        content_type: str,
        parsed_document: ParsedDocument,
        target_fields,
    ):
        self.extract_calls += 1
        raise UpstageExtractionError("invalid schema")


@pytest.fixture
async def analysis_context(monkeypatch):
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

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
        adapter=UpstageAdapter(
            mode="mock",
            api_key="",
            base_url="https://api.upstage.ai",
        ),
        contracts=repository,
        documents=repository,
        understood_terms=repository,
        analyses=repository,
        storage=repository,
    )

    async def override_repository():
        return repository

    async def override_analysis_service():
        return analysis_service

    app.dependency_overrides[get_supabase_adapter] = override_repository
    app.dependency_overrides[get_analysis_service] = override_analysis_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, repository, analysis_service
    finally:
        app.dependency_overrides.clear()


def auth_headers(*, idempotency_key: UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)
    return headers


async def create_contract(client: AsyncClient) -> UUID:
    response = await asyncio.wait_for(
        client.post(
            "/api/v1/contracts",
            headers=auth_headers(),
            json={
                "title": "광안리 카페 SNS 광고대행 계약",
                "counterparty_name": "부산홍보대행",
            },
        ),
        timeout=10,
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["data"]["id"])


async def upload_document(
    client: AsyncClient,
    *,
    contract_id: UUID,
    document_type: str = "CONTRACT",
) -> UUID:
    response = await asyncio.wait_for(
        client.post(
            f"/api/v1/contracts/{contract_id}/documents",
            headers=auth_headers(),
            data={"type": document_type},
            files={"file": ("contract.pdf", make_pdf(), "application/pdf")},
        ),
        timeout=10,
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["data"]["id"])


async def save_understood_terms(
    client: AsyncClient,
    *,
    contract_id: UUID,
    duration_text: str = "1년",
    termination_text: str = "중도해지 가능",
) -> None:
    response = await asyncio.wait_for(
        client.put(
            f"/api/v1/contracts/{contract_id}/understood-terms",
            headers=auth_headers(),
            json={
                "duration_text": duration_text,
                "monthly_amount": 400000,
                "total_amount": 4800000,
                "refund_text": "중도해지 시 일부 환불",
                "termination_text": termination_text,
                "source_type": "USER_MEMORY",
            },
        ),
        timeout=10,
    )
    assert response.status_code == 200


async def test_starts_idempotent_analysis_and_processes_mock_result(analysis_context) -> None:
    client, repository, _service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    await save_understood_terms(client, contract_id=contract_id)
    key = uuid4()

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=key),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["data"]["status"] == "QUEUED"
    assert body["data"]["attempt_count"] == 0
    assert body["data"]["supporting_document_ids"] == []
    task_id = UUID(body["data"]["id"])

    completed = repository.mock_analysis_tasks[task_id]
    assert completed.status == AnalysisStatus.COMPLETED
    assert completed.attempt_count == 2
    assert completed.result is not None
    assert completed.result.extracted_terms
    assert {term.field for term in completed.result.extracted_terms} == set(ExtractedField)
    assert any(
        term.source_page is not None
        and term.source_text is not None
        and term.confidence > 0
        for term in completed.result.extracted_terms
    )
    assert repository.mock_contracts[contract_id].status == ContractStatus.REVIEW_REQUIRED
    assert repository.mock_contracts[contract_id].start_date.isoformat() == "2026-08-01"
    assert repository.mock_contracts[contract_id].end_date.isoformat() == "2027-07-31"
    assert repository.mock_contracts[contract_id].total_amount == 6_000_000
    obligation = repository.mock_obligations[contract_id]
    assert obligation.title == "인스타그램 SNS 홍보 콘텐츠 12건"
    assert obligation.due_date.isoformat() == "2026-08-20"
    assert obligation.source_page == 1
    assert obligation.source_text
    assert obligation.confidence > 0
    assert [event.event_type for event in repository.mock_audit_events].count(
        "ANALYSIS_STARTED"
    ) == 1
    assert [event.event_type for event in repository.mock_audit_events].count(
        "ANALYSIS_COMPLETED"
    ) == 1
    assert [event.event_type for event in repository.mock_audit_events].count(
        "OBLIGATION_CREATED"
    ) == 1

    replay = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=key),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )
    assert replay.status_code == 202
    assert replay.json() == body
    assert len(repository.mock_analysis_tasks) == 1


async def test_compares_understood_duration_and_termination(analysis_context) -> None:
    client, repository, _service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    await save_understood_terms(
        client,
        contract_id=contract_id,
        duration_text="5년",
        termination_text="중도해지 불가능",
    )

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )

    task = repository.mock_analysis_tasks[UUID(response.json()["data"]["id"])]
    assert task.result is not None
    explanations = {item.plain_explanation for item in task.result.review_items}
    assert "사용자가 이해한 계약기간과 계약 원문의 계약기간이 다릅니다." in explanations
    assert (
        "사용자가 이해한 중도해지 가능 여부와 계약 원문의 조건이 다릅니다."
        in explanations
    )


async def test_rejects_different_request_for_same_idempotency_key(
    analysis_context,
) -> None:
    client, _repository, _service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    support_id = await upload_document(
        client,
        contract_id=contract_id,
        document_type="PROPOSAL",
    )
    key = uuid4()

    first = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=key),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )
    conflict = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=key),
        json={
            "document_id": str(document_id),
            "supporting_document_ids": [str(support_id)],
        },
    )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_requires_latest_contract_document_and_valid_support_type(
    analysis_context,
) -> None:
    client, _repository, _service = analysis_context
    contract_id = await create_contract(client)
    older_document_id = await upload_document(client, contract_id=contract_id)
    latest_document_id = await upload_document(client, contract_id=contract_id)

    old_response = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(older_document_id), "supporting_document_ids": []},
    )
    wrong_support_response = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "document_id": str(latest_document_id),
            "supporting_document_ids": [str(older_document_id)],
        },
    )

    assert old_response.status_code == 422
    assert wrong_support_response.status_code == 422
    assert old_response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_failed_analysis_can_only_be_restarted_explicitly_with_new_key(
    analysis_context,
) -> None:
    client, repository, service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    failing_adapter = AlwaysInvalidExtractAdapter()
    service.adapter = failing_adapter

    first = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )
    first_task_id = UUID(first.json()["data"]["id"])
    assert repository.mock_analysis_tasks[first_task_id].status == AnalysisStatus.FAILED
    assert repository.mock_contracts[contract_id].status == ContractStatus.ANALYZING
    assert failing_adapter.extract_calls == 2

    restarted = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )

    assert first.status_code == 202
    assert restarted.status_code == 202
    assert len(repository.mock_analysis_tasks) == 2
    assert [event.event_type for event in repository.mock_audit_events].count(
        "ANALYSIS_RESTARTED"
    ) == 1


async def test_analysis_start_requires_auth_and_idempotency_header(analysis_context) -> None:
    client, _repository, _service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    payload = {"document_id": str(document_id), "supporting_document_ids": []}

    no_auth = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers={"Idempotency-Key": str(uuid4())},
        json=payload,
    )
    no_key = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(),
        json=payload,
    )

    assert no_auth.status_code == 401
    assert no_key.status_code == 422


def test_fastapi_openapi_exposes_analysis_start_contract() -> None:
    operation = app.openapi()["paths"]["/api/v1/contracts/{contract_id}/analysis"]["post"]

    assert operation["responses"]["202"]
    assert any(
        parameter["name"] == "Idempotency-Key"
        and parameter["in"] == "header"
        and parameter["required"] is True
        for parameter in operation["parameters"]
    )
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/AnalysisStartRequest")
