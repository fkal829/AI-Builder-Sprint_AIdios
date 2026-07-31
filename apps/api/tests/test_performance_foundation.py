import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_performance_access_guard
from app.core.enums import ContractStatus, IdempotencyOperation, PerformanceReportStatus
from app.core.exceptions import IdempotencyConflict, InvalidDocument, ResourceNotFound
from app.repositories.contracts import ContractRecord
from app.repositories.documents import DocumentRecord
from app.repositories.performance import PerformanceReportAccess
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.performance import (
    PerformanceAccessGuard,
    performance_upload_idempotency_payload,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000014")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
REPORT_ID = UUID("00000000-0000-4000-8000-000000000071")
DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000081")
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def make_adapter() -> SupabaseAdapter:
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token="local-demo-owner-token",
        clock=lambda: NOW,
    )
    adapter._mock_contracts[CONTRACT_ID] = ContractRecord(
        id=CONTRACT_ID,
        owner_id=OWNER_ID,
        title="광고효과 공통 기반 계약",
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
    adapter._mock_documents[DOCUMENT_ID] = performance_document()
    adapter._mock_performance_reports[REPORT_ID] = PerformanceReportAccess(
        id=REPORT_ID,
        contract_id=CONTRACT_ID,
        period="2026-08",
        source_document_id=DOCUMENT_ID,
        status=PerformanceReportStatus.UPLOADED,
    )
    return adapter


def performance_document() -> DocumentRecord:
    return DocumentRecord(
        id=DOCUMENT_ID,
        contract_id=CONTRACT_ID,
        type=DocumentType.PERFORMANCE_REPORT,
        parse_status=DocumentParseStatus.PENDING,
        storage_path=f"{OWNER_ID}/{CONTRACT_ID}/{DOCUMENT_ID}/source.pdf",
        content_type="application/pdf",
        size_bytes=128,
        page_count=1,
        created_at=NOW,
    )


async def test_supabase_mock_implements_the_owner_scoped_access_repository() -> None:
    adapter = make_adapter()
    guard = PerformanceAccessGuard(adapter)

    context = await guard.require_report(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        for_write=True,
    )

    assert context.report.id == REPORT_ID
    assert context.source_document.id == DOCUMENT_ID
    assert await adapter.has_performance_report_for_period(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        period="2026-08",
    )
    assert not await adapter.has_performance_report_for_period(
        owner_id=OTHER_OWNER_ID,
        contract_id=CONTRACT_ID,
        period="2026-08",
    )
    with pytest.raises(ResourceNotFound):
        await guard.require_report(
            owner_id=OTHER_OWNER_ID,
            contract_id=CONTRACT_ID,
            report_id=REPORT_ID,
        )


async def test_dependency_wires_the_real_supabase_adapter_to_the_guard() -> None:
    adapter = make_adapter()

    guard = await get_performance_access_guard(adapter)
    contract = await guard.require_contract(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        for_write=True,
    )

    assert isinstance(guard, PerformanceAccessGuard)
    assert contract.status is ContractStatus.SIGNED


async def test_generic_document_repository_cannot_create_performance_reports() -> None:
    adapter = make_adapter()
    before_documents = adapter.mock_documents
    before_events = adapter.mock_audit_events

    with pytest.raises(InvalidDocument, match="전용 업로드 API"):
        await adapter.create_document_with_audit(
            owner_id=OWNER_ID,
            record=performance_document(),
        )

    assert adapter.mock_documents == before_documents
    assert adapter.mock_audit_events == before_events


def test_upload_idempotency_payload_contains_only_the_canonical_file_identity() -> None:
    content = b"%PDF-1.7\nperformance-report"

    payload = performance_upload_idempotency_payload(
        period=" 2026-08 ",
        content=content,
        verified_content_type="application/pdf",
    )

    assert payload == {
        "period": "2026-08",
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "content_type": "application/pdf",
        "size_bytes": len(content),
    }
    assert content not in payload.values()
    with pytest.raises(ValueError, match="빈 광고효과"):
        performance_upload_idempotency_payload(
            period="2026-08",
            content=b"",
            verified_content_type="application/pdf",
        )
    with pytest.raises(ValueError, match="PDF, PNG, JPEG"):
        performance_upload_idempotency_payload(
            period="2026-08",
            content=b"text",
            verified_content_type="text/plain",
        )


async def test_all_three_performance_writes_have_isolated_idempotency_namespaces() -> None:
    adapter = make_adapter()
    service = IdempotencyService(
        adapter,
        now=lambda: NOW,
        pending_replay_delay_seconds=0,
    )
    key = uuid4()
    calls: list[IdempotencyOperation] = []

    async def execute(operation: IdempotencyOperation, request_payload: object):
        async def perform() -> IdempotentOutcome[dict[str, str]]:
            calls.append(operation)
            return IdempotentOutcome(
                status_code=200,
                response={"operation": operation.value},
                replay_payload={"operation": operation.value},
            )

        return await service.execute(
            owner_id=OWNER_ID,
            operation=operation,
            resource_id=CONTRACT_ID,
            key=key,
            request_payload=request_payload,
            perform=perform,
            replay=lambda payload: {"operation": str(payload["operation"])},
        )

    upload_payload = performance_upload_idempotency_payload(
        period="2026-08",
        content=b"%PDF-1.7 report",
        verified_content_type="application/pdf",
    )
    first_upload = await execute(IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD, upload_payload)
    replayed_upload = await execute(
        IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD,
        dict(upload_payload),
    )
    await execute(IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT, {"report_id": REPORT_ID})
    await execute(
        IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM,
        {"report_id": REPORT_ID, "expected_revision": 0},
    )

    assert first_upload.replayed is False
    assert replayed_upload.replayed is True
    assert calls == [
        IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD,
        IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT,
        IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM,
    ]
    assert {record.operation for record in adapter.mock_idempotency_records} == {
        IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD,
        IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT,
        IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM,
    }

    changed_upload = performance_upload_idempotency_payload(
        period="2026-08",
        content=b"%PDF-1.7 changed",
        verified_content_type="application/pdf",
    )
    with pytest.raises(IdempotencyConflict):
        await execute(IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD, changed_upload)


class FakeQuery:
    def __init__(self, *, table: str, rows: list[dict], calls: list[tuple]) -> None:
        self._table = table
        self._rows = rows
        self._calls = calls

    def select(self, columns: str):
        self._calls.append((self._table, "select", columns))
        return self

    def eq(self, column: str, value: str):
        self._calls.append((self._table, "eq", column, value))
        return self

    def limit(self, value: int):
        self._calls.append((self._table, "limit", value))
        return self

    def execute(self):
        self._calls.append((self._table, "execute"))
        return SimpleNamespace(data=self._rows)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.rows = {
            "contracts": [
                {"id": str(CONTRACT_ID), "owner_id": str(OWNER_ID), "status": "SIGNED"}
            ],
            "performance_reports": [
                {
                    "id": str(REPORT_ID),
                    "contract_id": str(CONTRACT_ID),
                    "period": "2026-08",
                    "source_document_id": str(DOCUMENT_ID),
                    "status": "UPLOADED",
                }
            ],
            "documents": [
                {
                    "id": str(DOCUMENT_ID),
                    "contract_id": str(CONTRACT_ID),
                    "type": "PERFORMANCE_REPORT",
                    "parse_status": "PENDING",
                    "storage_path": "private/source.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 128,
                    "page_count": 1,
                    "created_at": NOW.isoformat(),
                }
            ],
        }

    def table(self, name: str) -> FakeQuery:
        self.calls.append((name, "table"))
        return FakeQuery(table=name, rows=self.rows[name], calls=self.calls)


async def test_supabase_live_queries_apply_owner_filters_in_the_database_query(
    monkeypatch,
) -> None:
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = make_adapter()
    fake_client = FakeClient()
    adapter.mode = "live"
    adapter._client = fake_client  # type: ignore[assignment]

    contract = await adapter.get_owned_performance_contract(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
    )
    report = await adapter.get_owned_performance_report(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
    )
    document = await adapter.get_owned_performance_source_document(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        document_id=DOCUMENT_ID,
    )
    exists = await adapter.has_performance_report_for_period(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        period="2026-08",
    )

    assert contract is not None and contract.owner_id == OWNER_ID
    assert report is not None and report.contract_id == CONTRACT_ID
    assert document is not None and document.type is DocumentType.PERFORMANCE_REPORT
    assert exists
    assert ("contracts", "eq", "owner_id", str(OWNER_ID)) in fake_client.calls
    assert (
        "performance_reports",
        "eq",
        "contracts.owner_id",
        str(OWNER_ID),
    ) in fake_client.calls
    assert ("documents", "eq", "contracts.owner_id", str(OWNER_ID)) in fake_client.calls
