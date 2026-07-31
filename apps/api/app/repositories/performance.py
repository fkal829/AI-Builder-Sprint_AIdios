"""P2-C-1 repository boundary for revision/flag/inquiry-draft storage.

`PerformanceReport` (upload, extraction, status UPLOADED/EXTRACTED) is P2-B's
schema and migration. This Protocol only covers what P2-C owns — appending an
immutable revision and reading it back — so P2-C-3/P2-C-4 can build the
confirm/correct and aggregation APIs against it once P2-B's foundation lands.
Until then, implementations are in-memory fakes (see tests).
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.schemas.performance import (
    PerformanceFlag,
    PerformanceInquiryDraft,
    PerformanceReportRevision,
)


class PerformanceRevisionRepository(Protocol):
    async def append_revision(
        self,
        *,
        revision: PerformanceReportRevision,
        flags: Sequence[PerformanceFlag],
        inquiry_drafts: Sequence[PerformanceInquiryDraft],
    ) -> PerformanceReportRevision:
        """Store a new revision (plus its flags and inquiry drafts) and make
        it the report's current revision. Never mutates a prior revision."""
        ...

    async def get_current_revision(
        self, *, report_id: UUID
    ) -> PerformanceReportRevision | None: ...

    async def list_revisions(
        self, *, report_id: UUID
    ) -> Sequence[PerformanceReportRevision]:
        """Version-ascending, append-only history for one report."""
        ...

    async def list_flags_for_revision(
        self, *, report_revision_id: UUID
    ) -> Sequence[PerformanceFlag]: ...

    async def get_inquiry_draft(
        self, *, flag_id: UUID
    ) -> PerformanceInquiryDraft | None: ...
