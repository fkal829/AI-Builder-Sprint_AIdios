"""P2-C-1 repository boundary for `PerformanceReport` revision persistence.

The schema (`app/schemas/performance.py`) came out of the P2-0 common-contract
PR (#66) and is the shared source of truth for both P2-B and P2-C — it already
embeds each revision's flags/inquiry drafts and enforces the append-only
invariants (version sequencing, `corrected_from_revision_id` chain,
`current_revision` correctness) via Pydantic validators. This Protocol only
covers what P2-C owns on top of that: appending an already-validated revision
and reading the report back. Until P2-B's upload/extract migration lands,
implementations are in-memory fakes (see tests).
"""

from typing import Protocol
from uuid import UUID

from app.schemas.performance import PerformanceReport, PerformanceReportRevision


class PerformanceReportRepository(Protocol):
    async def get_report(self, *, report_id: UUID) -> PerformanceReport | None: ...

    async def append_revision(
        self, *, report_id: UUID, revision: PerformanceReportRevision
    ) -> PerformanceReport:
        """Append an already-validated revision to the report's history and
        make it current. Never mutates a previously stored revision."""
        ...
