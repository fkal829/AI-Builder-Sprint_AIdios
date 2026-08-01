"""Attempt-level guarantees for performance-report metric extraction."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.adapters.supabase import SupabaseAdapter
from app.core.enums import ContractStatus, IdempotencyOperation, PerformanceReportStatus
from app.core.errors import ErrorCode
from app.core.exceptions import (
    PerformanceReportExtractFailed,
    PerformanceReportExtractionInProgress,
    ResourceNotFound,
)
from app.repositories.contracts import ContractRecord
from app.repositories.documents import DocumentRecord
from app.repositories.performance import PerformanceReportAccess
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.performance import PerformanceExtractedPayload
from app.services.idempotency import IdempotencyService, request_fingerprint
from app.services.performance_extraction import (
    PerformanceDocumentParseError,
    PerformanceMetricMappingError,
    PerformanceReportExtractionService,
)
from app.services.state_machine import InvalidStatusTransition

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
REPORT_ID = UUID("00000000-0000-4000-8000-000000000071")
DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000081")
INITIAL_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


@dataclass
class MutableClock:
    value: datetime = INITIAL_TIME

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


@dataclass
class StubExtractor:
    result: object | None = None
    error: Exception | None = None
    calls: list[DocumentRecord] = field(default_factory=list)

    async def __call__(self, document: DocumentRecord) -> object:
        self.calls.append(document)
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class BlockingExtractor:
    result: object
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    calls: list[DocumentRecord] = field(default_factory=list)

    async def __call__(self, document: DocumentRecord) -> object:
        self.calls.append(document)
        self.started.set()
        await self.release.wait()
        return self.result


def extracted_payload(*, offset: int = 0) -> PerformanceExtractedPayload:
    def candidate(name: str, value: int) -> dict[str, Any]:
        return {
            "value": value,
            "source_page": 1,
            "source_text": f"{name}: {value}",
            "confidence": 0.98,
            "verification_status": "VERIFIED",
        }

    return PerformanceExtractedPayload.model_validate(
        {
            "impressions": candidate("노출", 1000 + offset),
            "likes": candidate("좋아요", 80 + offset),
            "comments": candidate("댓글", 12 + offset),
            "reach": candidate("도달", 900 + offset),
            "saves": candidate("저장", 20 + offset),
            "shares": candidate("공유", 7 + offset),
            "follower_net_change": candidate("팔로워 순증", 15 + offset),
            "published_content_count": candidate("게시물 수", 4 + offset),
        }
    )


def make_adapter(
    clock: MutableClock,
    *,
    contract_status: ContractStatus = ContractStatus.SIGNED,
    report_status: PerformanceReportStatus = PerformanceReportStatus.UPLOADED,
    document_type: DocumentType = DocumentType.PERFORMANCE_REPORT,
) -> SupabaseAdapter:
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token="local-demo-owner-token",
        clock=clock,
    )
    adapter._mock_contracts[CONTRACT_ID] = ContractRecord(
        id=CONTRACT_ID,
        owner_id=OWNER_ID,
        title="광고효과 추출 테스트 계약",
        counterparty_name="부산홍보대행",
        status=contract_status,
        signed_date=None,
        start_date=None,
        end_date=None,
        termination_notice_date=None,
        renewal_type=None,
        total_amount=None,
        understood_term=None,
        renewal_decision=None,
        modusign_document_id=None,
        created_at=INITIAL_TIME,
        updated_at=INITIAL_TIME,
    )
    adapter._mock_documents[DOCUMENT_ID] = DocumentRecord(
        id=DOCUMENT_ID,
        contract_id=CONTRACT_ID,
        type=document_type,
        parse_status=(
            DocumentParseStatus.COMPLETED
            if report_status is PerformanceReportStatus.EXTRACTED
            else DocumentParseStatus.PENDING
        ),
        storage_path=f"{OWNER_ID}/{CONTRACT_ID}/{DOCUMENT_ID}/source.pdf",
        content_type="application/pdf",
        size_bytes=128,
        page_count=1,
        created_at=INITIAL_TIME,
    )
    adapter._mock_performance_reports[REPORT_ID] = PerformanceReportAccess(
        id=REPORT_ID,
        contract_id=CONTRACT_ID,
        period="2026-08",
        source_document_id=DOCUMENT_ID,
        status=report_status,
        extracted_payload=(
            extracted_payload()
            if report_status is PerformanceReportStatus.EXTRACTED
            else None
        ),
        created_at=INITIAL_TIME,
        updated_at=INITIAL_TIME,
    )
    return adapter


def make_service(
    adapter: SupabaseAdapter,
    extractor: StubExtractor,
    clock: MutableClock,
) -> PerformanceReportExtractionService:
    return PerformanceReportExtractionService(
        adapter,
        IdempotencyService(
            adapter,
            now=clock,
            pending_replay_delay_seconds=0,
        ),
        extractor,
        now=clock,
    )


async def extract_with_key(
    service: PerformanceReportExtractionService,
    key: UUID,
):
    return await service.extract(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        idempotency_key=key,
    )


async def test_claim_success_and_same_key_replay_without_network(monkeypatch) -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    payload = extracted_payload()
    extractor = StubExtractor(result=payload.model_dump(mode="json"))
    service = make_service(adapter, extractor, clock)
    key = uuid4()

    def reject_live_client():
        raise AssertionError("mock extraction must not initialize a live client")

    monkeypatch.setattr(adapter, "_require_live_client", reject_live_client)

    first = await extract_with_key(service, key)
    replay = await extract_with_key(service, key)
    repeated_completion = await adapter.complete_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        attempt_id=key,
        extracted_payload=payload,
        completed_at=clock(),
    )

    assert first.status_code == 200
    assert first.replayed is False
    assert replay.status_code == 200
    assert replay.replayed is True
    assert repeated_completion.outcome == "APPLIED"
    assert replay.response == first.response
    assert len(extractor.calls) == 1
    assert extractor.calls[0].parse_status is DocumentParseStatus.PROCESSING

    report = adapter.mock_performance_reports[REPORT_ID]
    document = adapter.mock_documents[DOCUMENT_ID]
    assert report.status is PerformanceReportStatus.EXTRACTED
    assert report.extracted_payload == payload
    assert report.current_revision_id is None
    assert report.revision_count == 0
    assert report.extraction_attempt_id == key
    assert document.parse_status is DocumentParseStatus.COMPLETED

    events = [
        event
        for event in adapter.mock_audit_events
        if event.event_type == "PERFORMANCE_REPORT_EXTRACTED"
    ]
    assert len(events) == 1
    assert events[0].actor_type == "SYSTEM"
    records = adapter.mock_idempotency_records
    assert len(records) == 1
    assert records[0].key == key
    assert records[0].response_status == 200
    assert records[0].response_payload is not None
    assert records[0].response_payload["outcome"] == "SUCCESS"


async def test_concurrent_same_key_calls_execute_the_extractor_once() -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    extractor = BlockingExtractor(result=extracted_payload())
    service = PerformanceReportExtractionService(
        adapter,
        IdempotencyService(
            adapter,
            now=clock,
            pending_replay_delay_seconds=0.001,
        ),
        extractor,
        now=clock,
    )
    key = uuid4()

    first_task = asyncio.create_task(extract_with_key(service, key))
    await extractor.started.wait()
    replay_task = asyncio.create_task(extract_with_key(service, key))
    await asyncio.sleep(0.01)
    extractor.release.set()
    first, replay = await asyncio.gather(first_task, replay_task)

    assert len(extractor.calls) == 1
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.response == first.response


async def test_repeated_claim_for_same_attempt_is_response_loss_safe() -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    attempt_id = uuid4()

    first = await adapter.claim_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        attempt_id=attempt_id,
        idempotency_key=attempt_id,
        started_at=clock(),
        stale_before=clock() - timedelta(minutes=15),
    )
    clock.advance(timedelta(seconds=1))
    replay = await adapter.claim_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        attempt_id=attempt_id,
        idempotency_key=attempt_id,
        started_at=clock(),
        stale_before=clock() - timedelta(minutes=15),
    )

    assert first.outcome == replay.outcome == "CLAIMED"
    assert replay.report == first.report
    assert replay.source_document == first.source_document
    assert adapter.mock_audit_events == ()


async def test_different_key_before_fifteen_minutes_returns_in_progress() -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    old_attempt = uuid4()
    claim = await adapter.claim_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        attempt_id=old_attempt,
        idempotency_key=old_attempt,
        started_at=clock(),
        stale_before=clock() - timedelta(minutes=15),
    )
    assert claim.outcome == "CLAIMED"

    clock.advance(timedelta(minutes=14, seconds=59))
    extractor = StubExtractor(result=extracted_payload())
    new_key = uuid4()

    with pytest.raises(PerformanceReportExtractionInProgress) as error:
        await extract_with_key(make_service(adapter, extractor, clock), new_key)

    assert error.value.status_code == 409
    assert error.value.code is ErrorCode.REPORT_EXTRACTION_IN_PROGRESS
    assert extractor.calls == []
    assert adapter.mock_performance_reports[REPORT_ID].extraction_attempt_id == old_attempt
    assert adapter.mock_documents[DOCUMENT_ID].parse_status is DocumentParseStatus.PROCESSING
    assert adapter.mock_idempotency_records == ()


async def test_exact_fifteen_minutes_recovers_and_old_attempt_becomes_noop() -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    old_attempt = uuid4()
    old_idempotency = await adapter.claim_idempotency(
        owner_id=OWNER_ID,
        operation=IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT,
        resource_id=REPORT_ID,
        key=old_attempt,
        request_hash=request_fingerprint(
            {"contract_id": CONTRACT_ID, "report_id": REPORT_ID}
        ),
        created_at=clock(),
    )
    assert old_idempotency.outcome == "NEW"
    claim = await adapter.claim_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        attempt_id=old_attempt,
        idempotency_key=old_attempt,
        started_at=clock(),
        stale_before=clock() - timedelta(minutes=15),
    )
    assert claim.outcome == "CLAIMED"

    clock.advance(timedelta(minutes=15))
    payload = extracted_payload()
    extractor = StubExtractor(result=payload)
    service = make_service(adapter, extractor, clock)
    new_key = uuid4()

    result = await extract_with_key(service, new_key)
    late_completion = await adapter.complete_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        attempt_id=old_attempt,
        extracted_payload=extracted_payload(offset=100),
        completed_at=clock(),
    )
    late_failure = await adapter.fail_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        attempt_id=old_attempt,
        document_parse_status=DocumentParseStatus.FAILED,
        failed_at=clock(),
    )
    replay = await extract_with_key(service, new_key)

    assert result.status_code == 200
    assert result.replayed is False
    assert replay.replayed is True
    assert late_completion.outcome == "STALE"
    assert late_failure.outcome == "STALE"
    assert len(extractor.calls) == 1
    assert adapter.mock_performance_reports[REPORT_ID].extracted_payload == payload
    assert {record.key for record in adapter.mock_idempotency_records} == {new_key}

    event_types = [event.event_type for event in adapter.mock_audit_events]
    assert event_types.count("PERFORMANCE_REPORT_EXTRACTION_RECOVERED") == 1
    assert event_types.count("PERFORMANCE_REPORT_EXTRACTED") == 1


async def test_parse_failure_is_stored_as_502_and_replayed() -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    extractor = StubExtractor(error=PerformanceDocumentParseError("parse failed"))
    service = make_service(adapter, extractor, clock)
    key = uuid4()

    for _ in range(2):
        with pytest.raises(PerformanceReportExtractFailed) as error:
            await extract_with_key(service, key)
        assert error.value.status_code == 502
        assert error.value.code is ErrorCode.REPORT_EXTRACT_FAILED

    repeated_failure = await adapter.fail_performance_report_extraction(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        attempt_id=key,
        document_parse_status=DocumentParseStatus.FAILED,
        failed_at=clock(),
    )

    assert len(extractor.calls) == 1
    assert repeated_failure.outcome == "APPLIED"
    report = adapter.mock_performance_reports[REPORT_ID]
    assert report.status is PerformanceReportStatus.UPLOADED
    assert report.extracted_payload is None
    assert report.extraction_attempt_id == key
    assert adapter.mock_documents[DOCUMENT_ID].parse_status is DocumentParseStatus.FAILED
    assert not any(
        event.event_type == "PERFORMANCE_REPORT_EXTRACTED"
        for event in adapter.mock_audit_events
    )
    records = adapter.mock_idempotency_records
    assert len(records) == 1
    assert records[0].response_status == 502
    assert records[0].response_payload == {
        "outcome": "FAILED",
        "error_code": ErrorCode.REPORT_EXTRACT_FAILED.value,
    }


async def test_parse_failure_requires_a_new_key_for_explicit_retry() -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    failed_key = uuid4()
    failed_service = make_service(
        adapter,
        StubExtractor(error=PerformanceDocumentParseError("parse failed")),
        clock,
    )

    with pytest.raises(PerformanceReportExtractFailed):
        await extract_with_key(failed_service, failed_key)

    clock.advance(timedelta(seconds=1))
    retry_extractor = StubExtractor(result=extracted_payload())
    retried = await extract_with_key(
        make_service(adapter, retry_extractor, clock),
        uuid4(),
    )

    assert retried.status_code == 200
    assert retried.response.status is PerformanceReportStatus.EXTRACTED
    assert len(retry_extractor.calls) == 1
    assert adapter.mock_documents[DOCUMENT_ID].parse_status is DocumentParseStatus.COMPLETED


async def test_unclassified_extractor_error_is_failed_once_and_replayed() -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    extractor = StubExtractor(error=TimeoutError("unexpected adapter timeout"))
    service = make_service(adapter, extractor, clock)
    key = uuid4()

    for _ in range(2):
        with pytest.raises(PerformanceReportExtractFailed):
            await extract_with_key(service, key)

    assert len(extractor.calls) == 1
    assert adapter.mock_documents[DOCUMENT_ID].parse_status is DocumentParseStatus.FAILED
    assert adapter.mock_idempotency_records[0].response_status == 502


async def test_completion_persistence_error_does_not_run_ai_twice(monkeypatch) -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    extractor = StubExtractor(result=extracted_payload())
    service = make_service(adapter, extractor, clock)
    key = uuid4()

    async def fail_completion(**_kwargs):
        raise RuntimeError("completion storage unavailable")

    monkeypatch.setattr(
        adapter,
        "complete_performance_report_extraction",
        fail_completion,
    )

    for _ in range(2):
        with pytest.raises(PerformanceReportExtractFailed):
            await extract_with_key(service, key)

    assert len(extractor.calls) == 1
    assert adapter.mock_performance_reports[REPORT_ID].status is PerformanceReportStatus.UPLOADED
    assert adapter.mock_documents[DOCUMENT_ID].parse_status is DocumentParseStatus.PROCESSING
    assert adapter.mock_idempotency_records[0].response_status == 502


@pytest.mark.parametrize("failure_kind", ["mapping", "schema"])
async def test_mapping_and_schema_failures_keep_report_uploaded_and_replay_502(
    failure_kind: str,
) -> None:
    clock = MutableClock()
    adapter = make_adapter(clock)
    extractor = (
        StubExtractor(error=PerformanceMetricMappingError("mapping failed"))
        if failure_kind == "mapping"
        else StubExtractor(result={"impressions": "invalid"})
    )
    service = make_service(adapter, extractor, clock)
    key = uuid4()

    for _ in range(2):
        with pytest.raises(PerformanceReportExtractFailed) as error:
            await extract_with_key(service, key)
        assert error.value.status_code == 502
        assert error.value.code is ErrorCode.REPORT_EXTRACT_FAILED

    assert len(extractor.calls) == 1
    report = adapter.mock_performance_reports[REPORT_ID]
    assert report.status is PerformanceReportStatus.UPLOADED
    assert report.extracted_payload is None
    assert report.extraction_attempt_id == key
    assert adapter.mock_documents[DOCUMENT_ID].parse_status is DocumentParseStatus.COMPLETED
    assert adapter.mock_idempotency_records[0].response_status == 502


async def test_wrong_source_type_is_hidden_as_not_found() -> None:
    clock = MutableClock()
    adapter = make_adapter(clock, document_type=DocumentType.CONTRACT)
    extractor = StubExtractor(result=extracted_payload())

    with pytest.raises(ResourceNotFound) as error:
        await extract_with_key(make_service(adapter, extractor, clock), uuid4())

    assert error.value.status_code == 404
    assert extractor.calls == []
    assert adapter.mock_idempotency_records == ()


@pytest.mark.parametrize("invalid_case", ["contract", "report"])
async def test_invalid_contract_or_report_status_is_rejected_before_extraction(
    invalid_case: str,
) -> None:
    clock = MutableClock()
    adapter = (
        make_adapter(clock, contract_status=ContractStatus.DRAFT)
        if invalid_case == "contract"
        else make_adapter(clock, report_status=PerformanceReportStatus.EXTRACTED)
    )
    extractor = StubExtractor(result=extracted_payload())

    with pytest.raises(InvalidStatusTransition):
        await extract_with_key(make_service(adapter, extractor, clock), uuid4())

    assert extractor.calls == []
    assert adapter.mock_idempotency_records == ()
