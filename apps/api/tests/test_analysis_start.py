import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from app.adapters.base import ParsedDocument, ParsedPage
from app.adapters.solar import SolarReviewAdapter
from app.adapters.supabase import SupabaseAdapter
from app.adapters.upstage import UpstageAdapter, UpstageExtractionError
from app.api.dependencies import get_analysis_service, get_supabase_adapter
from app.core.enums import (
    AnalysisStatus,
    ContractStatus,
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
    ObligationStatus,
    ReviewSignalType,
    VerificationStatus,
)
from app.core.exceptions import ExternalStorageFailure
from app.main import app
from app.repositories.analysis import AnalysisTaskRecord
from app.schemas.analysis import ExtractedTermCandidate
from app.services.analysis import ANALYSIS_FIELDS, AnalysisService

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


class MissingSolarOutputAdapter:
    async def generate_review_content(self, *, items):
        return []


class RoundTrackingExtractAdapter:
    def __init__(self) -> None:
        self.extract_calls: list[tuple[str, tuple[ExtractedField, ...]]] = []

    async def parse_document(
        self,
        *,
        content: bytes,
        content_type: str,
    ) -> ParsedDocument:
        del content_type
        text = content.decode("utf-8")
        return ParsedDocument(
            pages=(ParsedPage(number=1, text=text),),
            model="round-tracking-parse",
        )

    async def extract_terms(
        self,
        *,
        content: bytes,
        content_type: str,
        parsed_document: ParsedDocument,
        target_fields,
    ):
        del content_type
        label = content.decode("utf-8")
        self.extract_calls.append((label, target_fields))
        if ExtractedField.CONTRACT_START_DATE not in target_fields:
            return []
        return [
            ExtractedTermCandidate(
                field=ExtractedField.CONTRACT_START_DATE,
                value_type=ExtractedValueType.DATE,
                value=("2026-08-01" if label == "contract-evidence" else "2026-09-01"),
                source_page=1,
                source_text=parsed_document.pages[0].text,
                confidence=0.9,
                verification_status=VerificationStatus.VERIFIED,
            )
        ]


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
        reviewer=SolarReviewAdapter(
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
    assert completed.result.review_items
    assert all(
        item.detection_method.value == "HYBRID"
        and item.model_confidence is not None
        and item.model_limitations is not None
        for item in completed.result.review_items
    )
    assert (
        len(
            {
                (
                    item.suggestion_accept,
                    item.suggestion_compromise,
                    item.suggestion_request,
                )
                for item in completed.result.review_items
            }
        )
        > 1
    )
    assert {term.field for term in completed.result.extracted_terms} == set(ExtractedField)
    assert any(
        term.source_page is not None and term.source_text is not None and term.confidence > 0
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
    assert obligation.status == ObligationStatus.PENDING
    assert obligation.evidence_url is None
    assert obligation.submitted_at is None
    assert obligation.reviewed_at is None
    assert obligation.payment_condition_met is False
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


async def test_analysis_start_failure_is_persisted_and_replayed_with_request_id(
    analysis_context,
    monkeypatch,
) -> None:
    client, repository, _service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    key = uuid4()
    calls = 0

    async def fail_start(**_kwargs):
        nonlocal calls
        calls += 1
        raise ExternalStorageFailure("private database detail")

    monkeypatch.setattr(repository, "start_analysis_with_audit", fail_start)
    request = {
        "document_id": str(document_id),
        "supporting_document_ids": [],
    }

    first = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=key),
        json=request,
    )
    replay = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=key),
        json=request,
    )

    assert first.status_code == replay.status_code == 503
    assert replay.json() == first.json()
    assert first.json()["error"] == {
        "code": "ANALYSIS_START_FAILED",
        "message": "분석 작업을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    }
    assert first.json()["requestId"] == first.headers["X-Request-ID"]
    assert replay.json()["requestId"] == replay.headers["X-Request-ID"]
    assert calls == 1
    assert repository.mock_analysis_tasks == {}


async def test_get_queued_analysis_is_read_only(
    analysis_context,
    monkeypatch,
) -> None:
    client, repository, service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    now = datetime.now(UTC)
    task = AnalysisTaskRecord(
        id=uuid4(),
        contract_id=contract_id,
        document_id=document_id,
        supporting_document_ids=(),
        status=AnalysisStatus.QUEUED,
        attempt_count=0,
        error_code=None,
        result=None,
        created_at=now,
        updated_at=now,
    )
    repository._mock_analysis_tasks[task.id] = task

    async def fail_if_processed(**_kwargs) -> None:
        raise AssertionError("최근 분석 조회는 작업을 실행하면 안 됩니다.")

    monkeypatch.setattr(service, "process", fail_if_processed)

    response = await client.get(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "QUEUED"
    assert repository.mock_analysis_tasks[task.id].status == AnalysisStatus.QUEUED


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
    explanations = [item.plain_explanation for item in task.result.review_items]
    assert any(
        explanation.startswith("사용자가 이해한 계약기간과 계약 원문의 계약기간이 다릅니다.")
        for explanation in explanations
    )
    assert any(
        explanation.startswith("사용자가 이해한 중도해지 가능 여부와 계약 원문의 조건이 다릅니다.")
        for explanation in explanations
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


async def test_evaluator_uses_two_task_rounds_across_supporting_documents(
    analysis_context,
) -> None:
    client, repository, service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    support_id = await upload_document(
        client,
        contract_id=contract_id,
        document_type="PROPOSAL",
    )
    contract_document = repository.mock_documents[document_id]
    support_document = repository.mock_documents[support_id]
    repository._mock_objects[contract_document.storage_path] = b"contract-evidence"
    repository._mock_objects[support_document.storage_path] = b"support-evidence"
    tracking_adapter = RoundTrackingExtractAdapter()
    service.adapter = tracking_adapter

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "document_id": str(document_id),
            "supporting_document_ids": [str(support_id)],
        },
    )

    task = repository.mock_analysis_tasks[UUID(response.json()["data"]["id"])]
    assert response.status_code == 202
    assert task.status == AnalysisStatus.COMPLETED
    assert task.attempt_count == 2
    assert [label for label, _fields in tracking_adapter.extract_calls] == [
        "contract-evidence",
        "support-evidence",
        "contract-evidence",
        "support-evidence",
    ]
    first_round = tracking_adapter.extract_calls[:2]
    second_round = tracking_adapter.extract_calls[2:]
    assert all(fields == ANALYSIS_FIELDS for _label, fields in first_round)
    assert all(ExtractedField.CONTRACT_START_DATE not in fields for _label, fields in second_round)
    assert task.result is not None
    start_date_terms = [
        term
        for term in task.result.extracted_terms
        if term.field == ExtractedField.CONTRACT_START_DATE
    ]
    assert {term.source_type for term in start_date_terms} == {
        ExtractedSourceType.CONTRACT_DOCUMENT,
        ExtractedSourceType.DOCUMENTED_EXPLANATION,
    }
    contract_term = next(
        term
        for term in start_date_terms
        if term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT
    )
    support_term = next(
        term
        for term in start_date_terms
        if term.source_type == ExtractedSourceType.DOCUMENTED_EXPLANATION
    )
    comparison = next(
        item
        for item in task.result.review_items
        if support_term.id in item.related_extracted_term_ids
    )
    assert comparison.type == ReviewSignalType.MISMATCH
    assert comparison.related_extracted_term_ids == [
        contract_term.id,
        support_term.id,
    ]
    assert comparison.source_document_id == document_id
    assert comparison.plain_explanation.startswith(
        "선택 자료에서 문서로 확인된 계약 시작일 설명과 계약 문서상 조건이 다릅니다."
    )


async def test_invalid_solar_output_fails_analysis_without_partial_review_items(
    analysis_context,
) -> None:
    client, repository, service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    service.reviewer = MissingSolarOutputAdapter()

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )

    task = repository.mock_analysis_tasks[UUID(response.json()["data"]["id"])]
    assert response.status_code == 202
    assert task.status == AnalysisStatus.FAILED
    assert task.error_code.value == "ANALYSIS_SCHEMA_INVALID"
    assert task.result is None
    assert not repository.mock_review_items


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


async def test_gets_latest_completed_analysis_result(analysis_context) -> None:
    client, _repository, _service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    await save_understood_terms(client, contract_id=contract_id)

    started = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )
    task_id = started.json()["data"]["id"]

    response = await client.get(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["id"] == task_id
    assert body["data"]["status"] == "COMPLETED"
    assert body["data"]["attempt_count"] == 2
    assert body["data"]["error_code"] is None
    assert body["data"]["result"]["contract_id"] == str(contract_id)
    assert body["data"]["result"]["extracted_terms"]
    assert body["data"]["result"]["review_items"]


async def test_gets_newest_analysis_task_by_creation_time(analysis_context) -> None:
    client, repository, _service = analysis_context
    contract_id = await create_contract(client)
    document_id = uuid4()
    first_created_at = datetime(2026, 7, 31, 9, tzinfo=UTC)
    queued = AnalysisTaskRecord(
        id=uuid4(),
        contract_id=contract_id,
        document_id=document_id,
        supporting_document_ids=(),
        status=AnalysisStatus.QUEUED,
        attempt_count=0,
        error_code=None,
        result=None,
        created_at=first_created_at,
        updated_at=first_created_at,
    )
    processing = AnalysisTaskRecord(
        id=uuid4(),
        contract_id=contract_id,
        document_id=document_id,
        supporting_document_ids=(),
        status=AnalysisStatus.PROCESSING,
        attempt_count=1,
        error_code=None,
        result=None,
        created_at=first_created_at + timedelta(seconds=1),
        updated_at=first_created_at + timedelta(seconds=2),
    )
    repository._mock_analysis_tasks[queued.id] = queued
    repository._mock_analysis_tasks[processing.id] = processing

    response = await client.get(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "id": str(processing.id),
        "contract_id": str(contract_id),
        "document_id": str(document_id),
        "supporting_document_ids": [],
        "status": "PROCESSING",
        "attempt_count": 1,
        "error_code": None,
        "result": None,
        "created_at": "2026-07-31T09:00:01Z",
        "updated_at": "2026-07-31T09:00:02Z",
    }


async def test_gets_latest_failed_analysis_result(analysis_context) -> None:
    client, _repository, service = analysis_context
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    service.adapter = AlwaysInvalidExtractAdapter()

    await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )
    restarted = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )

    response = await client.get(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == restarted.json()["data"]["id"]
    assert response.json()["data"]["status"] == "FAILED"
    assert response.json()["data"]["attempt_count"] == 2
    assert response.json()["data"]["error_code"] == "ANALYSIS_SCHEMA_INVALID"
    assert response.json()["data"]["result"] is None


async def test_get_analysis_handles_not_found_auth_and_invalid_contract_id(
    analysis_context,
) -> None:
    client, _repository, _service = analysis_context
    contract_id = await create_contract(client)

    no_task = await client.get(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(),
    )
    unknown_contract = await client.get(
        f"/api/v1/contracts/{uuid4()}/analysis",
        headers=auth_headers(),
    )
    no_auth = await client.get(f"/api/v1/contracts/{contract_id}/analysis")
    invalid_contract_id = await client.get(
        "/api/v1/contracts/not-a-uuid/analysis",
        headers=auth_headers(),
    )

    assert no_task.status_code == 404
    assert unknown_contract.status_code == 404
    assert no_auth.status_code == 401
    assert invalid_contract_id.status_code == 422


def test_fastapi_openapi_exposes_analysis_get_contract() -> None:
    operation = app.openapi()["paths"]["/api/v1/contracts/{contract_id}/analysis"]["get"]

    assert operation["responses"]["200"]
    assert operation["responses"]["401"]
    assert operation["responses"]["404"]
    assert operation["responses"]["422"]
    assert "requestBody" not in operation


async def complete_analysis_for_review(
    client: AsyncClient,
    repository: SupabaseAdapter,
) -> tuple[UUID, UUID, UUID]:
    contract_id = await create_contract(client)
    document_id = await upload_document(client, contract_id=contract_id)
    await save_understood_terms(client, contract_id=contract_id)
    started = await client.post(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"document_id": str(document_id), "supporting_document_ids": []},
    )
    task_id = UUID(started.json()["data"]["id"])
    result = repository.mock_analysis_tasks[task_id].result
    assert result is not None
    assert result.review_items
    return contract_id, task_id, result.review_items[0].id


async def test_updates_review_selection_and_mirrors_analysis_result(
    analysis_context,
) -> None:
    client, repository, _service = analysis_context
    contract_id, task_id, item_id = await complete_analysis_for_review(
        client,
        repository,
    )

    compromise = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/{item_id}",
        headers=auth_headers(),
        json={"user_choice": "COMPROMISE"},
    )
    replay = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/{item_id}",
        headers=auth_headers(),
        json={"user_choice": "COMPROMISE"},
    )
    request_choice = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/{item_id}",
        headers=auth_headers(),
        json={"user_choice": "REQUEST"},
    )
    accept = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/{item_id}",
        headers=auth_headers(),
        json={"user_choice": "ACCEPT"},
    )
    blocked = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/{item_id}",
        headers=auth_headers(),
        json={"user_choice": "ACCEPT"},
    )

    assert compromise.status_code == 200
    assert compromise.json()["data"]["status"] == "SELECTED"
    assert compromise.json()["data"]["user_choice"] == "COMPROMISE"
    assert replay.status_code == 200
    assert request_choice.status_code == 200
    assert request_choice.json()["data"]["status"] == "SELECTED"
    assert request_choice.json()["data"]["user_choice"] == "REQUEST"
    assert accept.status_code == 200
    assert accept.json()["data"]["status"] == "RESOLVED"
    assert accept.json()["data"]["user_choice"] == "ACCEPT"
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    selection_events = [
        event
        for event in repository.mock_audit_events
        if event.event_type == "REVIEW_ITEM_SELECTION_UPDATED"
    ]
    assert len(selection_events) == 3
    assert repository.mock_review_item_details[item_id].status.value == "RESOLVED"
    assert repository.mock_review_items[item_id].user_choice.value == "ACCEPT"
    mirrored = repository.mock_analysis_tasks[task_id].result
    assert mirrored is not None
    mirrored_item = next(item for item in mirrored.review_items if item.id == item_id)
    assert mirrored_item.status.value == "RESOLVED"
    assert mirrored_item.user_choice.value == "ACCEPT"

    latest = await client.get(
        f"/api/v1/contracts/{contract_id}/analysis",
        headers=auth_headers(),
    )
    latest_item = next(
        item
        for item in latest.json()["data"]["result"]["review_items"]
        if item["id"] == str(item_id)
    )
    assert latest_item["status"] == "RESOLVED"
    assert latest_item["user_choice"] == "ACCEPT"


async def test_rejects_review_selection_after_adjustment_send(
    analysis_context,
) -> None:
    client, repository, _service = analysis_context
    contract_id, _task_id, item_id = await complete_analysis_for_review(
        client,
        repository,
    )
    selected = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/{item_id}",
        headers=auth_headers(),
        json={"user_choice": "REQUEST"},
    )
    draft = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests",
        headers=auth_headers(idempotency_key=uuid4()),
        json={
            "review_item_ids": [str(item_id)],
            "expires_in_hours": 24,
        },
    )
    adjustment_id = draft.json()["data"]["id"]
    sent = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_id}/send",
        headers=auth_headers(idempotency_key=uuid4()),
        json={"confirmed": True},
    )

    blocked = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/{item_id}",
        headers=auth_headers(),
        json={"user_choice": "COMPROMISE"},
    )

    assert selected.status_code == 200
    assert draft.status_code == 201
    assert sent.status_code == 200
    assert repository.mock_review_item_details[item_id].status.value == "SENT"
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert [event.event_type for event in repository.mock_audit_events].count(
        "REVIEW_ITEM_SELECTION_UPDATED"
    ) == 1


async def test_review_selection_handles_not_found_auth_and_validation(
    analysis_context,
) -> None:
    client, repository, _service = analysis_context
    contract_id, _task_id, item_id = await complete_analysis_for_review(
        client,
        repository,
    )
    other_contract_id = await create_contract(client)
    path = f"/api/v1/contracts/{contract_id}/review-items/{item_id}"

    wrong_contract = await client.patch(
        f"/api/v1/contracts/{other_contract_id}/review-items/{item_id}",
        headers=auth_headers(),
        json={"user_choice": "REQUEST"},
    )
    unknown_item = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/{uuid4()}",
        headers=auth_headers(),
        json={"user_choice": "REQUEST"},
    )
    no_auth = await client.patch(path, json={"user_choice": "REQUEST"})
    invalid_choice = await client.patch(
        path,
        headers=auth_headers(),
        json={"user_choice": "OTHER"},
    )
    invalid_item_id = await client.patch(
        f"/api/v1/contracts/{contract_id}/review-items/not-a-uuid",
        headers=auth_headers(),
        json={"user_choice": "REQUEST"},
    )

    assert wrong_contract.status_code == 404
    assert unknown_item.status_code == 404
    assert no_auth.status_code == 401
    assert invalid_choice.status_code == 422
    assert invalid_item_id.status_code == 422


def test_fastapi_openapi_exposes_review_item_update_contract() -> None:
    operation = app.openapi()["paths"]["/api/v1/contracts/{contract_id}/review-items/{item_id}"][
        "patch"
    ]

    assert operation["responses"]["200"]
    assert operation["responses"]["401"]
    assert operation["responses"]["404"]
    assert operation["responses"]["409"]
    assert operation["responses"]["422"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/ReviewItemUpdate")
