from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.adapters.supabase import SupabaseAdapter
from app.core.enums import ContractStatus, PerformanceReportStatus
from app.core.exceptions import ExternalStorageFailure
from app.repositories.contracts import ContractRecord
from app.repositories.documents import DocumentRecord
from app.schemas.documents import DocumentParseStatus, DocumentType

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260801030000_add_performance_report_upload_audit.sql"
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000014")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
REPORT_ID = UUID("00000000-0000-4000-8000-000000000071")
DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000081")
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def make_adapter(*, status: ContractStatus = ContractStatus.SIGNED) -> SupabaseAdapter:
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
        title="성과 리포트 업로드 감사 계약",
        counterparty_name="부산홍보대행",
        status=status,
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


def source_document(
    *,
    document_id: UUID = DOCUMENT_ID,
    storage_path: str | None = None,
) -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        contract_id=CONTRACT_ID,
        type=DocumentType.PERFORMANCE_REPORT,
        parse_status=DocumentParseStatus.PENDING,
        storage_path=(
            storage_path or f"{OWNER_ID}/{CONTRACT_ID}/performance/{document_id}/private-source.pdf"
        ),
        content_type="application/pdf",
        size_bytes=512,
        page_count=2,
        created_at=NOW,
    )


def test_upload_rpc_atomically_appends_only_safe_audit_metadata() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = sql.split(
        "create function public.create_performance_report_upload_with_audit",
        maxsplit=1,
    )[1].split("$$;", maxsplit=1)[0]

    assert "security definer" in body
    assert "set search_path = ''" in body
    assert "contract.owner_id = p_owner_id" in body
    assert body.count("insert into public.documents") == 1
    assert body.count("insert into public.performance_reports") == 1
    assert body.count("insert into public.audit_events") == 1
    assert (
        body.index("insert into public.documents")
        < body.index("insert into public.performance_reports")
        < body.index("insert into public.audit_events")
    )
    assert "'PERFORMANCE_REPORT'" in body
    assert "'PENDING'" in body
    assert "'UPLOADED'" in body
    assert "'PERFORMANCE_REPORT_UPLOADED'" in body

    audit_insert = body.split("insert into public.audit_events", maxsplit=1)[1].split(
        "return jsonb_build_object",
        maxsplit=1,
    )[0]
    assert "payload" in audit_insert
    assert "'{}'::jsonb" in audit_insert
    for sensitive_parameter in (
        "p_storage_path",
        "p_content_type",
        "p_size_bytes",
        "p_page_count",
        "p_period",
        "p_document_id",
        "p_report_id",
    ):
        assert sensitive_parameter not in audit_insert


def test_upload_rpc_recovers_replay_and_restricts_direct_or_public_writes() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = sql.split(
        "create function public.create_performance_report_upload_with_audit",
        maxsplit=1,
    )[1].split("$$;", maxsplit=1)[0]

    assert body.index("'outcome', 'REPLAYED'") < body.index("v_contract.status not in")
    assert body.index("'outcome', 'PERIOD_ALREADY_EXISTS'") < body.index(
        "insert into public.documents"
    )
    assert "revoke insert on table public.performance_reports from service_role" in sql
    assert "from public, anon, authenticated" in sql and ") to service_role" in sql


async def test_mock_create_and_replay_append_exactly_one_complete_unit() -> None:
    adapter = make_adapter()
    document = source_document()

    created = await adapter.create_performance_report_upload_with_audit(
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        period="2026-08",
        source_document=document,
    )
    replayed = await adapter.create_performance_report_upload_with_audit(
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        period="2026-08",
        source_document=document,
    )

    assert created.outcome == "CREATED"
    assert replayed.outcome == "REPLAYED"
    assert created.source_document == replayed.source_document == document
    assert created.report == replayed.report
    assert created.report is not None
    assert created.report.status is PerformanceReportStatus.UPLOADED
    assert adapter.mock_documents == {DOCUMENT_ID: document}
    assert set(adapter.mock_performance_reports) == {REPORT_ID}
    assert [event.event_type for event in adapter.mock_audit_events] == [
        "PERFORMANCE_REPORT_UPLOADED"
    ]
    upload_event = adapter.mock_audit_events[0]
    assert upload_event.payload == {}
    event_text = repr(upload_event)
    assert document.storage_path not in event_text
    assert "2026-08" not in event_text


@pytest.mark.parametrize(
    ("owner_id", "status", "expected_outcome"),
    [
        (OTHER_OWNER_ID, ContractStatus.SIGNED, "NOT_FOUND"),
        (OWNER_ID, ContractStatus.DRAFT, "INVALID_STATUS"),
    ],
)
async def test_mock_auth_and_status_rejections_leave_no_partial_rows(
    owner_id: UUID,
    status: ContractStatus,
    expected_outcome: str,
) -> None:
    adapter = make_adapter(status=status)

    result = await adapter.create_performance_report_upload_with_audit(
        owner_id=owner_id,
        report_id=REPORT_ID,
        period="2026-08",
        source_document=source_document(),
    )

    assert result.outcome == expected_outcome
    assert adapter.mock_documents == {}
    assert adapter.mock_performance_reports == {}
    assert adapter.mock_audit_events == ()


async def test_mock_period_duplicate_leaves_original_unit_unchanged() -> None:
    adapter = make_adapter()
    original = source_document()
    await adapter.create_performance_report_upload_with_audit(
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        period="2026-08",
        source_document=original,
    )
    other_document = source_document(document_id=uuid4())

    duplicate = await adapter.create_performance_report_upload_with_audit(
        owner_id=OWNER_ID,
        report_id=uuid4(),
        period="2026-08",
        source_document=other_document,
    )

    assert duplicate.outcome == "PERIOD_ALREADY_EXISTS"
    assert adapter.mock_documents == {DOCUMENT_ID: original}
    assert set(adapter.mock_performance_reports) == {REPORT_ID}
    assert len(adapter.mock_audit_events) == 1


async def test_mock_audit_construction_failure_cannot_leave_partial_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = make_adapter()

    def fail_audit_event(**_kwargs):
        raise RuntimeError("audit append failed")

    monkeypatch.setattr("app.adapters.supabase.MockAuditEvent", fail_audit_event)

    with pytest.raises(RuntimeError, match="audit append failed"):
        await adapter.create_performance_report_upload_with_audit(
            owner_id=OWNER_ID,
            report_id=REPORT_ID,
            period="2026-08",
            source_document=source_document(),
        )

    assert adapter.mock_documents == {}
    assert adapter.mock_performance_reports == {}
    assert adapter.mock_audit_events == ()


class FakeRpc:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def execute(self):
        return SimpleNamespace(data=self._payload)


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, params: dict) -> FakeRpc:
        self.calls.append((name, params))
        return FakeRpc(self.payload)


async def test_live_adapter_calls_only_the_atomic_upload_rpc(monkeypatch) -> None:
    document = source_document()
    payload = {
        "outcome": "CREATED",
        "source_document": {
            "id": str(document.id),
            "contract_id": str(document.contract_id),
            "type": "PERFORMANCE_REPORT",
            "parse_status": "PENDING",
            "storage_path": document.storage_path,
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
            "page_count": document.page_count,
            "created_at": NOW.isoformat(),
        },
        "report": {
            "id": str(REPORT_ID),
            "contract_id": str(CONTRACT_ID),
            "period": "2026-08",
            "source_document_id": str(DOCUMENT_ID),
            "status": "UPLOADED",
            "extracted_payload": None,
            "current_revision_id": None,
            "revision_count": 0,
            "extraction_attempt_id": None,
            "extraction_started_at": None,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        },
    }
    adapter = make_adapter()
    fake_client = FakeClient(payload)
    adapter.mode = "live"
    adapter._client = fake_client  # type: ignore[assignment]

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)

    result = await adapter.create_performance_report_upload_with_audit(
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        period="2026-08",
        source_document=document,
    )

    assert result.outcome == "CREATED"
    assert result.report is not None and result.report.id == REPORT_ID
    assert result.source_document == document
    assert len(fake_client.calls) == 1
    rpc_name, params = fake_client.calls[0]
    assert rpc_name == "create_performance_report_upload_with_audit"
    assert params == {
        "p_owner_id": str(OWNER_ID),
        "p_document_id": str(DOCUMENT_ID),
        "p_report_id": str(REPORT_ID),
        "p_contract_id": str(CONTRACT_ID),
        "p_period": "2026-08",
        "p_storage_path": document.storage_path,
        "p_content_type": "application/pdf",
        "p_size_bytes": 512,
        "p_page_count": 2,
        "p_created_at": NOW.isoformat(),
    }


async def test_live_adapter_rejects_a_success_payload_for_different_upload(
    monkeypatch,
) -> None:
    document = source_document()
    payload = {
        "outcome": "CREATED",
        "source_document": {
            "id": str(document.id),
            "contract_id": str(document.contract_id),
            "type": "PERFORMANCE_REPORT",
            "parse_status": "PENDING",
            "storage_path": "another/private/source.pdf",
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
            "page_count": document.page_count,
            "created_at": NOW.isoformat(),
        },
        "report": {
            "id": str(REPORT_ID),
            "contract_id": str(CONTRACT_ID),
            "period": "2026-08",
            "source_document_id": str(DOCUMENT_ID),
            "status": "UPLOADED",
            "extracted_payload": None,
            "current_revision_id": None,
            "revision_count": 0,
            "extraction_attempt_id": None,
            "extraction_started_at": None,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        },
    }
    adapter = make_adapter()
    adapter.mode = "live"
    adapter._client = FakeClient(payload)  # type: ignore[assignment]

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)

    with pytest.raises(ExternalStorageFailure, match="요청과 일치하지 않습니다"):
        await adapter.create_performance_report_upload_with_audit(
            owner_id=OWNER_ID,
            report_id=REPORT_ID,
            period="2026-08",
            source_document=document,
        )
