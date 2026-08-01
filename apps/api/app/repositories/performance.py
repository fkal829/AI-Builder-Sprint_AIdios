"""Repository boundaries shared by the P2-B and P2-C performance work."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.core.enums import ContractStatus, PerformanceReportStatus
from app.repositories.documents import DocumentRecord
from app.schemas.documents import DocumentParseStatus
from app.schemas.performance import (
    PerformanceExtractedPayload,
    PerformanceReport,
    PerformanceReportRevision,
)

PerformanceExtractionClaimOutcome = Literal[
    "CLAIMED",
    "RECOVERED",
    "IN_PROGRESS",
    "INVALID_STATUS",
    "NOT_FOUND",
]
PerformanceExtractionApplyOutcome = Literal[
    "APPLIED",
    "STALE",
    "INVALID_STATUS",
    "NOT_FOUND",
]
PerformanceReportUploadOutcome = Literal[
    "CREATED",
    "REPLAYED",
    "PERIOD_ALREADY_EXISTS",
    "INVALID_STATUS",
    "NOT_FOUND",
    "CONFLICT",
]


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
    """Owner-scoped report projection shared by access and extraction operations."""

    id: UUID
    contract_id: UUID
    period: str
    source_document_id: UUID
    status: PerformanceReportStatus
    extracted_payload: PerformanceExtractedPayload | None = None
    current_revision_id: UUID | None = None
    revision_count: int = 0
    extraction_attempt_id: UUID | None = None
    extraction_started_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.extraction_attempt_id is None) != (self.extraction_started_at is None):
            raise ValueError("추출 attempt ID와 시작 시각은 함께 존재해야 합니다.")
        if self.extraction_started_at is not None and self.extraction_started_at.tzinfo is None:
            raise ValueError("추출 attempt 시작 시각은 시간대 정보를 포함해야 합니다.")
        if (self.created_at is None) != (self.updated_at is None):
            raise ValueError("성과 리포트 생성·수정 시각은 함께 존재해야 합니다.")
        if self.created_at is not None:
            if self.created_at.tzinfo is None or self.updated_at is None:
                raise ValueError("성과 리포트 시각은 시간대 정보를 포함해야 합니다.")
            if self.updated_at.tzinfo is None or self.updated_at < self.created_at:
                raise ValueError("성과 리포트 수정 시각은 생성 시각보다 빠를 수 없습니다.")
            if self.extraction_started_at is not None and not (
                self.created_at <= self.extraction_started_at <= self.updated_at
            ):
                raise ValueError("추출 attempt 시각은 리포트 생성·수정 시각 범위에 있어야 합니다.")

        if self.status is PerformanceReportStatus.UPLOADED:
            if self.extracted_payload is not None:
                raise ValueError("UPLOADED 리포트에는 추출 payload가 없어야 합니다.")
        elif self.extracted_payload is None:
            raise ValueError("EXTRACTED 이후 리포트에는 추출 payload가 필요합니다.")

        if self.status in {
            PerformanceReportStatus.UPLOADED,
            PerformanceReportStatus.EXTRACTED,
        }:
            if self.current_revision_id is not None or self.revision_count != 0:
                raise ValueError("UPLOADED·EXTRACTED 리포트에는 revision이 없어야 합니다.")
        elif self.current_revision_id is None or self.revision_count < 1:
            raise ValueError("확정된 리포트에는 현재 revision이 필요합니다.")


@dataclass(frozen=True)
class PerformanceExtractionClaim:
    outcome: PerformanceExtractionClaimOutcome
    report: PerformanceReportAccess | None = None
    source_document: DocumentRecord | None = None


@dataclass(frozen=True)
class PerformanceExtractionApplyResult:
    outcome: PerformanceExtractionApplyOutcome
    report: PerformanceReportAccess | None = None
    source_document: DocumentRecord | None = None


@dataclass(frozen=True)
class PerformanceReportUploadResult:
    """Result of the atomic private Document + report + audit append."""

    outcome: PerformanceReportUploadOutcome
    report: PerformanceReportAccess | None = None
    source_document: DocumentRecord | None = None


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


class PerformanceReportUploadRepository(Protocol):
    """Atomic upload metadata boundary for the planned 16.2 endpoint.

    Storage bytes are uploaded outside this boundary. The implementation must
    append the private source Document, the UPLOADED report, and exactly one
    non-sensitive PERFORMANCE_REPORT_UPLOADED audit event in one transaction.
    Reusing the pre-generated IDs with identical immutable metadata recovers an
    ambiguous committed response without appending another row or event.
    """

    async def create_performance_report_upload_with_audit(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        period: str,
        source_document: DocumentRecord,
    ) -> PerformanceReportUploadResult: ...


class PerformanceExtractionRepository(PerformanceAccessRepository, Protocol):
    """Atomic boundary for one explicit performance-report extraction attempt."""

    async def claim_performance_report_extraction(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        idempotency_key: UUID,
        started_at: datetime,
        stale_before: datetime,
    ) -> PerformanceExtractionClaim: ...

    async def complete_performance_report_extraction(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        extracted_payload: PerformanceExtractedPayload,
        completed_at: datetime,
    ) -> PerformanceExtractionApplyResult: ...

    async def fail_performance_report_extraction(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        attempt_id: UUID,
        document_parse_status: DocumentParseStatus,
        failed_at: datetime,
    ) -> PerformanceExtractionApplyResult: ...


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
