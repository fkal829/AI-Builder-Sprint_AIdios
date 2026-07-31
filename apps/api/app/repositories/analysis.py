from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.core.enums import AnalysisStatus
from app.core.errors import ErrorCode
from app.schemas.analysis import Analysis


@dataclass(frozen=True)
class AnalysisTaskRecord:
    id: UUID
    contract_id: UUID
    document_id: UUID
    supporting_document_ids: tuple[UUID, ...]
    status: AnalysisStatus
    attempt_count: int
    error_code: ErrorCode | None
    result: Analysis | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class QueuedAnalysisJob:
    """A stale queued task together with the owner context needed to process it."""

    owner_id: UUID
    task_id: UUID
    created_at: datetime


class AnalysisRepository(Protocol):
    async def fail_stale_processing_analysis_jobs(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[AnalysisTaskRecord, ...]: ...

    async def list_stale_queued_analysis_jobs(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[QueuedAnalysisJob, ...]: ...

    async def get_latest_analysis_task(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> AnalysisTaskRecord | None: ...

    async def start_analysis_with_audit(
        self,
        *,
        owner_id: UUID,
        task: AnalysisTaskRecord,
        restart: bool,
    ) -> AnalysisTaskRecord | None: ...

    async def mark_analysis_processing(
        self,
        *,
        task_id: UUID,
    ) -> AnalysisTaskRecord | None: ...

    async def complete_analysis_with_audit(
        self,
        *,
        task_id: UUID,
        attempt_count: int,
        result: Analysis,
    ) -> AnalysisTaskRecord | None: ...

    async def fail_analysis_with_audit(
        self,
        *,
        task_id: UUID,
        attempt_count: int,
        error_code: ErrorCode,
    ) -> AnalysisTaskRecord | None: ...
