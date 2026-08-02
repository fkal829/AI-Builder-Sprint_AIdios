from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import (
    get_performance_report_extraction_service,
    get_performance_report_upload_service,
    get_supabase_adapter,
)
from app.core.enums import ContractStatus, IdempotencyOperation, PerformanceReportStatus
from app.core.exceptions import ExternalStorageFailure
from app.main import app
from app.repositories.contracts import ContractRecord
from app.repositories.documents import DocumentRecord
from app.schemas.documents import DocumentParseStatus
from app.schemas.performance import PerformanceExtractedPayload
from app.services.idempotency import IdempotencyService
from app.services.performance_extraction import (
    PerformanceDocumentParseError,
    PerformanceMetricMappingError,
    PerformanceReportExtractionService,
)
from app.services.performance_upload import PerformanceReportUploadService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


@dataclass
class MutableClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


@dataclass
class StubExtractor:
    result: object
    error: Exception | None = None
    calls: list[DocumentRecord] = field(default_factory=list)

    async def __call__(self, source_document: DocumentRecord) -> object:
        self.calls.append(source_document)
        if self.error is not None:
            raise self.error
        return self.result


def make_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def extracted_payload() -> PerformanceExtractedPayload:
    def candidate(label: str, value: int) -> dict[str, Any]:
        return {
            "value": value,
            "source_page": 1,
            "source_text": f"{label}: {value}",
            "confidence": 0.98,
            "verification_status": "VERIFIED",
        }

    return PerformanceExtractedPayload.model_validate(
        {
            "impressions": candidate("노출 수", 3200),
            "likes": candidate("좋아요", 180),
            "comments": candidate("댓글", 21),
            "reach": candidate("도달", 2800),
            "saves": candidate("저장", 33),
            "shares": candidate("공유", 12),
            "follower_net_change": candidate("팔로워 순증", 47),
            "published_content_count": candidate("게시물 수", 4),
        }
    )


def make_adapter(clock: MutableClock) -> SupabaseAdapter:
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
        clock=clock,
    )
    adapter._mock_contracts[CONTRACT_ID] = ContractRecord(
        id=CONTRACT_ID,
        owner_id=OWNER_ID,
        title="광고효과 지표 추출 계약",
        counterparty_name="부산홍보대행",
        status=ContractStatus.SIGNED,
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
    return adapter


@pytest.fixture
async def extraction_context(monkeypatch: pytest.MonkeyPatch):
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.services.documents.asyncio.to_thread", run_inline)
    clock = MutableClock()
    adapter = make_adapter(clock)
    extractor = StubExtractor(result=extracted_payload())
    idempotency = IdempotencyService(
        adapter,
        now=clock,
        completion_retry_delay_seconds=0,
        pending_replay_delay_seconds=0,
    )
    upload_service = PerformanceReportUploadService(
        access_repository=adapter,
        upload_repository=adapter,
        storage=adapter,
        idempotency=idempotency,
        max_size_bytes=4096,
        max_pdf_pages=2,
        now=clock,
    )
    extraction_service = PerformanceReportExtractionService(
        repository=adapter,
        idempotency=idempotency,
        extractor=extractor,
        now=clock,
    )

    async def override_adapter():
        return adapter

    async def override_upload_service():
        return upload_service

    async def override_extraction_service():
        return extraction_service

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_performance_report_upload_service] = override_upload_service
    app.dependency_overrides[get_performance_report_extraction_service] = (
        override_extraction_service
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, adapter, extractor, clock
    finally:
        app.dependency_overrides.clear()


def auth_headers(*, key: UUID | str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    return headers


async def upload_report(
    client: AsyncClient,
    *,
    period: str = "2026-08",
) -> UUID:
    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/performance-reports",
        headers=auth_headers(key=uuid4()),
        data={"period": period},
        files={"file": ("private-report.pdf", make_pdf(), "application/pdf")},
    )
    assert response.status_code == 201
    return UUID(response.json()["data"]["id"])


async def post_extract(
    client: AsyncClient,
    report_id: UUID | str,
    *,
    key: UUID | str | None = None,
    contract_id: UUID | str = CONTRACT_ID,
    authorized: bool = True,
):
    headers = (
        auth_headers(key=key or uuid4()) if authorized else {"Idempotency-Key": str(key or uuid4())}
    )
    return await client.post(
        f"/api/v1/contracts/{contract_id}/performance-reports/{report_id}/extract",
        headers=headers,
    )


async def test_extracts_ten_grounded_metrics_and_replays_the_complete_response(
    extraction_context,
) -> None:
    client, adapter, extractor, _clock = extraction_context
    report_id = await upload_report(client)
    key = uuid4()

    first = await post_extract(client, report_id, key=key)
    replay = await post_extract(client, report_id, key=key)

    assert first.status_code == replay.status_code == 200
    assert first.headers["Cache-Control"] == replay.headers["Cache-Control"] == "no-store"
    assert first.json() == replay.json()
    assert first.headers["X-Request-ID"] == replay.headers["X-Request-ID"]
    assert first.json()["requestId"] == first.headers["X-Request-ID"]
    report = first.json()["data"]
    assert report["status"] == "EXTRACTED"
    assert report["current_revision"] is None
    assert report["revision_count"] == 0
    assert report["revisions"] == []
    assert "extraction_attempt_id" not in report
    assert "extraction_started_at" not in report
    assert set(report["extracted_payload"]) == {
        "ad_spend",
        "impressions",
        "clicks",
        "likes",
        "comments",
        "reach",
        "saves",
        "shares",
        "follower_net_change",
        "published_content_count",
    }
    assert report["extracted_payload"]["ad_spend"]["verification_status"] == "NOT_FOUND"
    assert report["extracted_payload"]["clicks"]["verification_status"] == "NOT_FOUND"
    assert report["extracted_payload"]["impressions"] == {
        "value": 3200,
        "source_page": 1,
        "source_text": "노출 수: 3200",
        "confidence": 0.98,
        "verification_status": "VERIFIED",
    }
    assert len(extractor.calls) == 1
    assert adapter.mock_performance_reports[report_id].status is PerformanceReportStatus.EXTRACTED
    assert [event.event_type for event in adapter.mock_audit_events].count(
        "PERFORMANCE_REPORT_EXTRACTED"
    ) == 1


@pytest.mark.parametrize(
    ("error", "expected_parse_status"),
    [
        (PerformanceDocumentParseError("parse failed"), DocumentParseStatus.FAILED),
        (PerformanceMetricMappingError("mapping failed"), DocumentParseStatus.COMPLETED),
    ],
)
async def test_parse_and_solar_failures_replay_502_without_fixed_fallback(
    extraction_context,
    error: Exception,
    expected_parse_status: DocumentParseStatus,
) -> None:
    client, adapter, extractor, _clock = extraction_context
    report_id = await upload_report(client)
    extractor.error = error
    key = uuid4()

    first = await post_extract(client, report_id, key=key)
    replay = await post_extract(client, report_id, key=key)

    assert first.status_code == replay.status_code == 502
    assert first.json() == replay.json()
    assert first.headers["X-Request-ID"] == replay.headers["X-Request-ID"]
    assert first.headers["Cache-Control"] == replay.headers["Cache-Control"] == "no-store"
    assert first.json()["error"]["code"] == "REPORT_EXTRACT_FAILED"
    assert len(extractor.calls) == 1
    stored_report = adapter.mock_performance_reports[report_id]
    source = adapter.mock_documents[stored_report.source_document_id]
    assert stored_report.status is PerformanceReportStatus.UPLOADED
    assert stored_report.extracted_payload is None
    assert source.parse_status is expected_parse_status


async def test_auth_ownership_and_uuid_failures_do_not_call_ai(extraction_context) -> None:
    client, _adapter, extractor, _clock = extraction_context
    report_id = await upload_report(client)

    responses = [
        await post_extract(client, report_id, authorized=False),
        await post_extract(client, uuid4()),
        await post_extract(client, report_id, contract_id=uuid4()),
        await post_extract(client, report_id, key="not-a-uuid"),
        await post_extract(client, "not-a-uuid"),
    ]

    assert [response.status_code for response in responses] == [401, 404, 404, 422, 422]
    assert all(response.headers["Cache-Control"] == "no-store" for response in responses)
    assert extractor.calls == []


async def test_terminal_report_and_active_attempt_return_409_without_duplicate_ai(
    extraction_context,
) -> None:
    client, adapter, extractor, clock = extraction_context
    completed_report_id = await upload_report(client)
    first = await post_extract(client, completed_report_id)
    assert first.status_code == 200

    terminal = await post_extract(client, completed_report_id)

    active_report_id = await upload_report(client, period="2026-09")
    active_attempt = uuid4()
    claim = await adapter.claim_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=active_report_id,
        attempt_id=active_attempt,
        idempotency_key=active_attempt,
        started_at=clock(),
        stale_before=clock() - timedelta(minutes=15),
    )
    in_progress = await post_extract(client, active_report_id, key=uuid4())

    assert terminal.status_code == 409
    assert terminal.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert in_progress.status_code == 409
    assert in_progress.json()["error"]["code"] == "REPORT_EXTRACTION_IN_PROGRESS"
    assert len(extractor.calls) == 1
    assert claim.outcome == "CLAIMED"


async def test_persistence_admission_failure_is_safe_503_and_abandons_the_key(
    extraction_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, extractor, _clock = extraction_context
    report_id = await upload_report(client)

    async def unavailable_claim(**_kwargs):
        raise ExternalStorageFailure("private database detail")

    monkeypatch.setattr(
        adapter,
        "claim_performance_report_extraction",
        unavailable_claim,
    )
    response = await post_extract(client, report_id)

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "private database detail" not in response.text
    assert extractor.calls == []
    assert not any(
        record.operation is IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT
        for record in adapter.mock_idempotency_records
    )


async def test_private_source_storage_failure_is_retryable_safe_503(
    extraction_context,
) -> None:
    client, adapter, extractor, _clock = extraction_context
    report_id = await upload_report(client)
    extractor.error = ExternalStorageFailure("private storage credential must not leak")

    response = await post_extract(client, report_id)

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "private storage credential" not in response.text
    assert len(extractor.calls) == 1
    stored_report = adapter.mock_performance_reports[report_id]
    source = adapter.mock_documents[stored_report.source_document_id]
    assert stored_report.status is PerformanceReportStatus.UPLOADED
    assert source.parse_status is DocumentParseStatus.FAILED
    assert not any(
        record.operation is IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT
        for record in adapter.mock_idempotency_records
    )


async def test_contract_status_is_rechecked_before_ai(extraction_context) -> None:
    client, adapter, extractor, _clock = extraction_context
    report_id = await upload_report(client)
    adapter._mock_contracts[CONTRACT_ID] = replace(
        adapter._mock_contracts[CONTRACT_ID],
        status=ContractStatus.DRAFT,
    )

    response = await post_extract(client, report_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert extractor.calls == []
