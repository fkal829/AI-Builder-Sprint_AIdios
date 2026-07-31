import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.repositories.analysis import AnalysisRepository

logger = logging.getLogger(__name__)


class AnalysisTaskProcessor(Protocol):
    async def process(self, *, owner_id: UUID, task_id: UUID) -> None: ...


@dataclass(frozen=True)
class AnalysisRecoveryRun:
    cutoff: datetime
    processing_cutoff: datetime
    candidates: int
    dispatched: int
    failed: int
    timed_out: int


class AnalysisRecoveryService:
    """Recover queued tasks and close processing tasks that exceeded their timeout."""

    def __init__(
        self,
        *,
        analyses: AnalysisRepository,
        processor: AnalysisTaskProcessor,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._analyses = analyses
        self._processor = processor
        self._now = now or (lambda: datetime.now(UTC))

    async def run_once(
        self,
        *,
        stale_after: timedelta,
        processing_timeout: timedelta,
        batch_size: int,
    ) -> AnalysisRecoveryRun:
        if stale_after.total_seconds() < 0:
            raise ValueError("stale_after must not be negative.")
        if processing_timeout.total_seconds() <= 0:
            raise ValueError("processing_timeout must be positive.")
        if not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be between 1 and 100.")

        now = self._now()
        if now.tzinfo is None:
            raise ValueError("Recovery clock must return a timezone-aware datetime.")
        cutoff = now - stale_after
        processing_cutoff = now - processing_timeout
        timed_out_tasks = await self._analyses.fail_stale_processing_analysis_jobs(
            stale_before=processing_cutoff,
            limit=batch_size,
        )
        jobs = await self._analyses.list_stale_queued_analysis_jobs(
            stale_before=cutoff,
            limit=batch_size,
        )

        dispatched = 0
        failed = 0
        for job in jobs:
            try:
                await self._processor.process(owner_id=job.owner_id, task_id=job.task_id)
            except Exception as error:  # Worker boundary: one bad task must not starve the batch.
                failed += 1
                logger.error(
                    "analysis_recovery_job_failed task_id=%s error_type=%s",
                    job.task_id,
                    type(error).__name__,
                )
            else:
                dispatched += 1

        return AnalysisRecoveryRun(
            cutoff=cutoff,
            processing_cutoff=processing_cutoff,
            candidates=len(jobs),
            dispatched=dispatched,
            failed=failed,
            timed_out=len(timed_out_tasks),
        )
