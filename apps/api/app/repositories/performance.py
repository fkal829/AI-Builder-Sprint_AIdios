"""Repository boundaries shared by the P2-B and P2-C performance work."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.enums import ContractStatus, PerformanceReportStatus
from app.repositories.documents import DocumentRecord
from app.schemas.performance import PerformanceReport, PerformanceReportRevision


@dataclass(frozen=True)
class PerformanceContractAccess:
    """Owner-scoped contract fields needed by the performance feature.

    This projection deliberately exposes no contract mutation method. Performance
    report writes may inspect ``status`` but must never transition it.
    """

    id: UUID
    owner_id: UUID
    status: ContractStatus


@dataclass(frozen=True)
class PerformanceReportAccess:
    """Minimum owner-scoped report projection used before every report operation."""

    id: UUID
    contract_id: UUID
    period: str
    source_document_id: UUID
    status: PerformanceReportStatus


class PerformanceAccessRepository(Protocol):
    """Read-only access boundary shared by all four performance APIs.

    Implementations must apply the owner filter in the same query as the contract
    or report lookup. Returning ``None`` hides both missing and foreign resources.
    The database unique constraint remains the final concurrency-safe guard for a
    contract/month identity; ``has_performance_report_for_period`` is a preflight.
    """

    async def get_owned_performance_contract(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> PerformanceContractAccess | None: ...

    async def get_owned_performance_report(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
    ) -> PerformanceReportAccess | None: ...

    async def get_owned_performance_source_document(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_id: UUID,
    ) -> DocumentRecord | None: ...

    async def has_performance_report_for_period(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        period: str,
    ) -> bool: ...


class PerformanceReportRepository(Protocol):
    """Append-only revision boundary owned by P2-C."""

    async def get_report(self, *, report_id: UUID) -> PerformanceReport | None: ...

    async def append_revision(
        self,
        *,
        report_id: UUID,
        revision: PerformanceReportRevision,
    ) -> PerformanceReport:
        """Append a validated revision and make it current without changing history."""

        ...
