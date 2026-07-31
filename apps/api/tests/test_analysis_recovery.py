import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.adapters.supabase import SupabaseAdapter
from app.core.config import Settings
from app.core.enums import AnalysisStatus, ContractStatus
from app.core.errors import ErrorCode
from app.repositories.analysis import AnalysisTaskRecord, QueuedAnalysisJob
from app.repositories.contracts import ContractRecord
from app.repositories.documents import DocumentRecord
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.services.analysis_recovery import AnalysisRecoveryService
from app.workers.analysis_recovery import parse_args

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
NOW = datetime(2026, 7, 31, 9, tzinfo=UTC)
DEFAULT_DOCUMENT_ID = UUID(int=900)
QUEUED_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260730330004_add_analysis_recovery_scan.sql"
)
PROCESSING_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260730330006_fail_stale_processing_analysis.sql"
)


def make_adapter(*, mode: str = "mock") -> SupabaseAdapter:
    return SupabaseAdapter(
        mode=mode,
        url="https://example.supabase.co" if mode == "live" else "",
        service_role_key="service-role-key" if mode == "live" else "",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
        clock=lambda: NOW,
    )


def seed_contract(adapter: SupabaseAdapter, *, contract_id: UUID, owner_id: UUID) -> None:
    adapter._mock_contracts[contract_id] = ContractRecord(
        id=contract_id,
        owner_id=owner_id,
        title="복구 대상 계약",
        counterparty_name="가상 대행사",
        status=ContractStatus.ANALYZING,
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


def seed_task(
    adapter: SupabaseAdapter,
    *,
    task_id: UUID,
    contract_id: UUID,
    created_at: datetime,
    status: AnalysisStatus = AnalysisStatus.QUEUED,
    document_id: UUID = DEFAULT_DOCUMENT_ID,
    supporting_document_ids: tuple[UUID, ...] = (),
) -> None:
    adapter._mock_analysis_tasks[task_id] = AnalysisTaskRecord(
        id=task_id,
        contract_id=contract_id,
        document_id=document_id,
        supporting_document_ids=supporting_document_ids,
        status=status,
        attempt_count=0 if status == AnalysisStatus.QUEUED else 1,
        error_code=None,
        result=None,
        created_at=created_at,
        updated_at=created_at,
    )


def seed_document(
    adapter: SupabaseAdapter,
    *,
    document_id: UUID,
    contract_id: UUID,
    parse_status: DocumentParseStatus = DocumentParseStatus.PROCESSING,
    document_type: DocumentType = DocumentType.CONTRACT,
) -> None:
    adapter._mock_documents[document_id] = DocumentRecord(
        id=document_id,
        contract_id=contract_id,
        type=document_type,
        parse_status=parse_status,
        storage_path=f"contracts/{contract_id}/{document_id}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        page_count=1,
        created_at=NOW - timedelta(days=1),
    )


async def test_mock_scan_applies_stale_cutoff_limit_order_and_owner_context() -> None:
    adapter = make_adapter()
    first_contract = UUID(int=101)
    second_contract = UUID(int=102)
    third_contract = UUID(int=103)
    for contract_id, owner_id in (
        (first_contract, OWNER_ID),
        (second_contract, OTHER_OWNER_ID),
        (third_contract, OWNER_ID),
    ):
        seed_contract(adapter, contract_id=contract_id, owner_id=owner_id)

    stale = NOW - timedelta(minutes=1)
    seed_task(
        adapter,
        task_id=UUID(int=2),
        contract_id=second_contract,
        created_at=stale,
    )
    seed_task(
        adapter,
        task_id=UUID(int=1),
        contract_id=first_contract,
        created_at=stale,
    )
    seed_task(
        adapter,
        task_id=UUID(int=3),
        contract_id=third_contract,
        created_at=NOW - timedelta(seconds=59),
    )
    seed_task(
        adapter,
        task_id=UUID(int=4),
        contract_id=third_contract,
        created_at=stale - timedelta(seconds=1),
        status=AnalysisStatus.PROCESSING,
    )

    jobs = await adapter.list_stale_queued_analysis_jobs(
        stale_before=stale,
        limit=2,
    )

    assert [(job.owner_id, job.task_id) for job in jobs] == [
        (OWNER_ID, UUID(int=1)),
        (OTHER_OWNER_ID, UUID(int=2)),
    ]
    assert all(job.created_at == stale for job in jobs)


async def test_mock_mark_processing_is_atomic_when_two_workers_scan_same_job() -> None:
    adapter = make_adapter()
    contract_id = UUID(int=101)
    task_id = UUID(int=1)
    seed_contract(adapter, contract_id=contract_id, owner_id=OWNER_ID)
    seed_task(
        adapter,
        task_id=task_id,
        contract_id=contract_id,
        created_at=NOW - timedelta(minutes=2),
    )

    jobs = await adapter.list_stale_queued_analysis_jobs(
        stale_before=NOW - timedelta(minutes=1),
        limit=10,
    )
    first, second = await asyncio.gather(
        *(adapter.mark_analysis_processing(task_id=job.task_id) for job in (jobs[0], jobs[0]))
    )

    assert [result is not None for result in (first, second)].count(True) == 1
    assert adapter.mock_analysis_tasks[task_id].status == AnalysisStatus.PROCESSING


async def test_mock_timeout_fails_only_stale_processing_with_document_and_audit() -> None:
    adapter = make_adapter()
    stale_contract_id = UUID(int=101)
    active_contract_id = UUID(int=102)
    stale_task_id = UUID(int=1)
    active_task_id = UUID(int=2)
    stale_document_id = UUID(int=901)
    active_document_id = UUID(int=902)
    supporting_document_id = UUID(int=903)
    cutoff = NOW - timedelta(hours=4)
    for contract_id in (stale_contract_id, active_contract_id):
        seed_contract(adapter, contract_id=contract_id, owner_id=OWNER_ID)
    seed_document(
        adapter,
        document_id=stale_document_id,
        contract_id=stale_contract_id,
    )
    seed_document(
        adapter,
        document_id=active_document_id,
        contract_id=active_contract_id,
    )
    seed_document(
        adapter,
        document_id=supporting_document_id,
        contract_id=stale_contract_id,
        document_type=DocumentType.PROPOSAL,
    )
    seed_task(
        adapter,
        task_id=stale_task_id,
        contract_id=stale_contract_id,
        document_id=stale_document_id,
        supporting_document_ids=(supporting_document_id,),
        created_at=cutoff,
        status=AnalysisStatus.PROCESSING,
    )
    seed_task(
        adapter,
        task_id=active_task_id,
        contract_id=active_contract_id,
        document_id=active_document_id,
        created_at=cutoff + timedelta(seconds=1),
        status=AnalysisStatus.PROCESSING,
    )

    failed = await adapter.fail_stale_processing_analysis_jobs(
        stale_before=cutoff,
        limit=10,
    )

    assert [task.id for task in failed] == [stale_task_id]
    timed_out = adapter.mock_analysis_tasks[stale_task_id]
    assert timed_out.status == AnalysisStatus.FAILED
    assert timed_out.error_code == ErrorCode.DOCUMENT_PARSE_FAILED
    assert timed_out.attempt_count == 1
    assert timed_out.updated_at == NOW
    assert adapter.mock_documents[stale_document_id].parse_status == DocumentParseStatus.FAILED
    assert adapter.mock_documents[supporting_document_id].parse_status == DocumentParseStatus.FAILED
    assert adapter.mock_analysis_tasks[active_task_id].status == AnalysisStatus.PROCESSING
    assert adapter.mock_documents[active_document_id].parse_status == DocumentParseStatus.PROCESSING
    assert adapter.mock_contracts[stale_contract_id].status == ContractStatus.ANALYZING
    failure_events = [
        event
        for event in adapter.mock_audit_events
        if event.contract_id == stale_contract_id and event.event_type == "ANALYSIS_FAILED"
    ]
    assert len(failure_events) == 1

    replay = await adapter.fail_stale_processing_analysis_jobs(
        stale_before=cutoff,
        limit=10,
    )
    assert replay == ()
    assert len(adapter.mock_audit_events) == 1


async def test_mock_processing_timeout_is_atomic_across_workers() -> None:
    adapter = make_adapter()
    contract_id = UUID(int=101)
    task_id = UUID(int=1)
    document_id = UUID(int=901)
    seed_contract(adapter, contract_id=contract_id, owner_id=OWNER_ID)
    seed_document(adapter, document_id=document_id, contract_id=contract_id)
    seed_task(
        adapter,
        task_id=task_id,
        contract_id=contract_id,
        document_id=document_id,
        created_at=NOW - timedelta(hours=5),
        status=AnalysisStatus.PROCESSING,
    )

    first, second = await asyncio.gather(
        *(
            adapter.fail_stale_processing_analysis_jobs(
                stale_before=NOW - timedelta(hours=4),
                limit=10,
            )
            for _ in range(2)
        )
    )

    assert sorted((len(first), len(second))) == [0, 1]
    assert len(adapter.mock_audit_events) == 1


async def test_mock_pipeline_failure_marks_primary_and_supporting_documents_failed() -> None:
    adapter = make_adapter()
    contract_id = UUID(int=101)
    task_id = UUID(int=1)
    document_id = UUID(int=901)
    supporting_document_id = UUID(int=902)
    seed_contract(adapter, contract_id=contract_id, owner_id=OWNER_ID)
    seed_document(adapter, document_id=document_id, contract_id=contract_id)
    seed_document(
        adapter,
        document_id=supporting_document_id,
        contract_id=contract_id,
        document_type=DocumentType.MESSAGE,
    )
    seed_task(
        adapter,
        task_id=task_id,
        contract_id=contract_id,
        document_id=document_id,
        supporting_document_ids=(supporting_document_id,),
        created_at=NOW - timedelta(minutes=1),
        status=AnalysisStatus.PROCESSING,
    )

    failed = await adapter.fail_analysis_with_audit(
        task_id=task_id,
        attempt_count=1,
        error_code=ErrorCode.ANALYSIS_SCHEMA_INVALID,
    )

    assert failed is not None
    assert failed.error_code == ErrorCode.ANALYSIS_SCHEMA_INVALID
    assert adapter.mock_documents[document_id].parse_status == DocumentParseStatus.FAILED
    assert adapter.mock_documents[supporting_document_id].parse_status == DocumentParseStatus.FAILED
    assert [event.event_type for event in adapter.mock_audit_events] == ["ANALYSIS_FAILED"]


async def test_processing_timeout_opens_existing_explicit_restart_path() -> None:
    adapter = make_adapter()
    contract_id = UUID(int=101)
    task_id = UUID(int=1)
    restarted_task_id = UUID(int=2)
    document_id = UUID(int=901)
    seed_contract(adapter, contract_id=contract_id, owner_id=OWNER_ID)
    seed_document(adapter, document_id=document_id, contract_id=contract_id)
    seed_task(
        adapter,
        task_id=task_id,
        contract_id=contract_id,
        document_id=document_id,
        created_at=NOW - timedelta(hours=5),
        status=AnalysisStatus.PROCESSING,
    )
    await adapter.fail_stale_processing_analysis_jobs(
        stale_before=NOW - timedelta(hours=4),
        limit=10,
    )
    restart = AnalysisTaskRecord(
        id=restarted_task_id,
        contract_id=contract_id,
        document_id=document_id,
        supporting_document_ids=(),
        status=AnalysisStatus.QUEUED,
        attempt_count=0,
        error_code=None,
        result=None,
        created_at=NOW + timedelta(seconds=1),
        updated_at=NOW + timedelta(seconds=1),
    )

    saved = await adapter.start_analysis_with_audit(
        owner_id=OWNER_ID,
        task=restart,
        restart=True,
    )

    assert saved == restart
    assert adapter.mock_analysis_tasks[restarted_task_id].status == AnalysisStatus.QUEUED
    assert [event.event_type for event in adapter.mock_audit_events] == [
        "ANALYSIS_FAILED",
        "ANALYSIS_RESTARTED",
    ]


class FakeAnalysisRepository:
    def __init__(
        self,
        jobs: tuple[QueuedAnalysisJob, ...],
        *,
        timed_out: tuple[AnalysisTaskRecord, ...] = (),
    ) -> None:
        self.jobs = jobs
        self.timed_out = timed_out
        self.calls: list[tuple[datetime, int]] = []
        self.timeout_calls: list[tuple[datetime, int]] = []

    async def fail_stale_processing_analysis_jobs(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[AnalysisTaskRecord, ...]:
        self.timeout_calls.append((stale_before, limit))
        return self.timed_out

    async def list_stale_queued_analysis_jobs(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[QueuedAnalysisJob, ...]:
        self.calls.append((stale_before, limit))
        return self.jobs


class FakeProcessor:
    def __init__(self, *, fail_task_id: UUID | None = None) -> None:
        self.calls: list[tuple[UUID, UUID]] = []
        self.fail_task_id = fail_task_id

    async def process(self, *, owner_id: UUID, task_id: UUID) -> None:
        self.calls.append((owner_id, task_id))
        if task_id == self.fail_task_id:
            raise RuntimeError("simulated worker failure")


async def test_recovery_worker_empty_queue_is_a_noop() -> None:
    repository = FakeAnalysisRepository(())
    processor = FakeProcessor()
    service = AnalysisRecoveryService(
        analyses=repository,
        processor=processor,
        now=lambda: NOW,
    )

    result = await service.run_once(
        stale_after=timedelta(seconds=60),
        processing_timeout=timedelta(hours=4),
        batch_size=10,
    )

    assert result.candidates == result.dispatched == result.failed == result.timed_out == 0
    assert result.cutoff == NOW - timedelta(seconds=60)
    assert result.processing_cutoff == NOW - timedelta(hours=4)
    assert repository.calls == [(result.cutoff, 10)]
    assert repository.timeout_calls == [(result.processing_cutoff, 10)]
    assert processor.calls == []


async def test_recovery_worker_propagates_tenant_owner_and_continues_after_failure() -> None:
    first_task_id = UUID(int=1)
    second_task_id = UUID(int=2)
    repository = FakeAnalysisRepository(
        (
            QueuedAnalysisJob(OWNER_ID, first_task_id, NOW - timedelta(minutes=2)),
            QueuedAnalysisJob(OTHER_OWNER_ID, second_task_id, NOW - timedelta(minutes=1)),
        )
    )
    processor = FakeProcessor(fail_task_id=first_task_id)
    service = AnalysisRecoveryService(
        analyses=repository,
        processor=processor,
        now=lambda: NOW,
    )

    result = await service.run_once(
        stale_after=timedelta(seconds=60),
        processing_timeout=timedelta(hours=4),
        batch_size=2,
    )

    assert processor.calls == [
        (OWNER_ID, first_task_id),
        (OTHER_OWNER_ID, second_task_id),
    ]
    assert (result.candidates, result.dispatched, result.failed) == (2, 1, 1)


async def test_live_scan_uses_stale_cutoff_and_batch_rpc(monkeypatch) -> None:
    calls = []
    task_id = UUID(int=1)

    class FakeClient:
        def rpc(self, name, params):
            calls.append((name, params))
            return SimpleNamespace(
                execute=lambda: SimpleNamespace(
                    data=[
                        {
                            "owner_id": str(OWNER_ID),
                            "task_id": str(task_id),
                            "created_at": "2026-07-31T08:58:00+00:00",
                        }
                    ]
                )
            )

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.create_client", lambda *_args: FakeClient())
    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = make_adapter(mode="live")

    jobs = await adapter.list_stale_queued_analysis_jobs(
        stale_before=NOW - timedelta(minutes=1),
        limit=10,
    )

    assert jobs == (
        QueuedAnalysisJob(
            owner_id=OWNER_ID,
            task_id=task_id,
            created_at=datetime(2026, 7, 31, 8, 58, tzinfo=UTC),
        ),
    )
    assert calls == [
        (
            "list_stale_queued_analysis_jobs",
            {"p_stale_before": "2026-07-31T08:59:00+00:00", "p_limit": 10},
        )
    ]


async def test_live_processing_timeout_uses_atomic_batch_rpc(monkeypatch) -> None:
    calls = []
    task_id = UUID(int=1)
    contract_id = UUID(int=101)
    document_id = UUID(int=901)

    class FakeClient:
        def rpc(self, name, params):
            calls.append((name, params))
            return SimpleNamespace(
                execute=lambda: SimpleNamespace(
                    data=[
                        {
                            "id": str(task_id),
                            "contract_id": str(contract_id),
                            "document_id": str(document_id),
                            "supporting_document_ids": [],
                            "status": "FAILED",
                            "attempt_count": 1,
                            "error_code": "DOCUMENT_PARSE_FAILED",
                            "result": None,
                            "created_at": "2026-07-31T03:00:00+00:00",
                            "updated_at": "2026-07-31T09:00:00+00:00",
                        }
                    ]
                )
            )

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.create_client", lambda *_args: FakeClient())
    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = make_adapter(mode="live")

    failed = await adapter.fail_stale_processing_analysis_jobs(
        stale_before=NOW - timedelta(hours=4),
        limit=10,
    )

    assert len(failed) == 1
    assert failed[0].status == AnalysisStatus.FAILED
    assert failed[0].error_code == ErrorCode.DOCUMENT_PARSE_FAILED
    assert calls == [
        (
            "fail_stale_processing_analysis_jobs",
            {"p_stale_before": "2026-07-31T05:00:00+00:00", "p_limit": 10},
        )
    ]


def test_recovery_worker_cli_supports_explicit_one_shot_and_loop_boundary() -> None:
    assert parse_args(["--once"]).once is True
    assert parse_args(["--loop"]).loop is True
    assert parse_args(["--interval-seconds", "15"]).interval_seconds == 15
    assert parse_args(["--processing-timeout-seconds", "14400"]).processing_timeout_seconds == 14400
    with pytest.raises(SystemExit):
        parse_args(["--once", "--loop"])
    with pytest.raises(SystemExit):
        parse_args(["--processing-timeout-seconds", "59"])


def test_recovery_scan_migration_is_ordered_limited_and_service_only() -> None:
    sql = QUEUED_MIGRATION.read_text(encoding="utf-8")

    assert "analysis_tasks_queued_recovery_idx" in sql
    assert "function public.list_stale_queued_analysis_jobs" in sql
    assert "contracts.owner_id" in sql
    assert "tasks.status = 'QUEUED'" in sql
    assert "tasks.created_at <= p_stale_before" in sql
    assert "order by tasks.created_at asc, tasks.id asc" in sql
    assert "limit p_limit" in sql
    assert "mark_analysis_processing" not in sql
    assert "to service_role" in sql


def test_processing_timeout_migration_is_atomic_limited_and_race_safe() -> None:
    sql = PROCESSING_MIGRATION.read_text(encoding="utf-8")

    assert "analysis_tasks_processing_recovery_idx" in sql
    assert "function public.fail_stale_processing_analysis_jobs" in sql
    assert "tasks.status = 'PROCESSING'" in sql
    assert "tasks.updated_at <= p_stale_before" in sql
    assert "order by tasks.updated_at asc, tasks.id asc" in sql
    assert "for update of tasks skip locked" in sql
    assert "limit p_limit" in sql
    assert "status = 'PROCESSING'" in sql
    assert "updated_at <= p_stale_before" in sql
    assert "error_code = 'DOCUMENT_PARSE_FAILED'" in sql
    assert "set parse_status = 'FAILED'" in sql
    assert "function public.fail_analysis_with_audit" in sql
    assert sql.count("or id = any(") == 2
    assert "'ANALYSIS_FAILED'" in sql
    assert "to service_role" in sql


def test_processing_timeout_default_is_four_hours() -> None:
    settings = Settings(_env_file=None)

    assert settings.analysis_recovery_processing_timeout_seconds == 14400
