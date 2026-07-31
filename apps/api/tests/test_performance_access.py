from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.core.enums import (
    ContractStatus,
    IdempotencyOperation,
    PerformanceReportStatus,
)
from app.core.errors import ErrorCode
from app.core.exceptions import PerformanceReportPeriodAlreadyExists, ResourceNotFound
from app.repositories.documents import DocumentRecord
from app.repositories.performance import PerformanceContractAccess, PerformanceReportAccess
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.services.performance import (
    PERFORMANCE_IDEMPOTENCY_OPERATION_BY_ACTION,
    PERFORMANCE_WRITE_CONTRACT_STATUSES,
    PerformanceAccessGuard,
    PerformanceReportIdentity,
    PerformanceWriteAction,
    normalize_performance_period,
    performance_idempotency_operation,
)
from app.services.state_machine import InvalidStatusTransition

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000014")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
REPORT_ID = UUID("00000000-0000-4000-8000-000000000071")
DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000081")
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


class FakePerformanceAccessRepository:
    def __init__(
        self,
        *,
        status: ContractStatus = ContractStatus.SIGNED,
        period_exists: bool = False,
        document_type: DocumentType = DocumentType.PERFORMANCE_REPORT,
        document_contract_id: UUID = CONTRACT_ID,
        report_contract_id: UUID = CONTRACT_ID,
    ) -> None:
        self.contract = PerformanceContractAccess(
            id=CONTRACT_ID,
            owner_id=OWNER_ID,
            status=status,
        )
        self.report = PerformanceReportAccess(
            id=REPORT_ID,
            contract_id=report_contract_id,
            period="2026-08",
            source_document_id=DOCUMENT_ID,
            status=PerformanceReportStatus.UPLOADED,
        )
        self.document = DocumentRecord(
            id=DOCUMENT_ID,
            contract_id=document_contract_id,
            type=document_type,
            parse_status=DocumentParseStatus.PENDING,
            storage_path=f"{OWNER_ID}/{CONTRACT_ID}/{DOCUMENT_ID}/source.pdf",
            content_type="application/pdf",
            size_bytes=128,
            page_count=1,
            created_at=NOW,
        )
        self.period_exists = period_exists
        self.calls: list[tuple[str, UUID, UUID]] = []

    async def get_owned_performance_contract(self, *, owner_id: UUID, contract_id: UUID):
        self.calls.append(("contract", owner_id, contract_id))
        if owner_id != OWNER_ID or contract_id != CONTRACT_ID:
            return None
        return self.contract

    async def get_owned_performance_report(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
    ):
        self.calls.append(("report", owner_id, contract_id))
        if owner_id != OWNER_ID or contract_id != CONTRACT_ID or report_id != REPORT_ID:
            return None
        return self.report

    async def get_owned_performance_source_document(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_id: UUID,
    ):
        self.calls.append(("document", owner_id, contract_id))
        if owner_id != OWNER_ID or contract_id != CONTRACT_ID or document_id != DOCUMENT_ID:
            return None
        return self.document

    async def has_performance_report_for_period(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        period: str,
    ) -> bool:
        self.calls.append((f"period:{period}", owner_id, contract_id))
        return self.period_exists


def test_performance_write_statuses_and_idempotency_namespaces_are_exact() -> None:
    assert PERFORMANCE_WRITE_CONTRACT_STATUSES == {
        ContractStatus.SIGNED,
        ContractStatus.IN_PROGRESS,
        ContractStatus.RENEWAL_DUE,
        ContractStatus.COMPLETED,
    }
    assert dict(PERFORMANCE_IDEMPOTENCY_OPERATION_BY_ACTION) == {
        PerformanceWriteAction.UPLOAD: IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD,
        PerformanceWriteAction.EXTRACT: IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT,
        PerformanceWriteAction.CONFIRM: IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM,
    }
    assert performance_idempotency_operation(
        PerformanceWriteAction.EXTRACT
    ) is IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT
    with pytest.raises(TypeError):
        PERFORMANCE_IDEMPOTENCY_OPERATION_BY_ACTION[
            PerformanceWriteAction.UPLOAD
        ] = IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM  # type: ignore[index]


@pytest.mark.parametrize("status", sorted(PERFORMANCE_WRITE_CONTRACT_STATUSES, key=str))
async def test_write_guard_accepts_only_the_four_approved_contract_statuses(
    status: ContractStatus,
) -> None:
    repository = FakePerformanceAccessRepository(status=status)
    original_status = repository.contract.status

    contract = await PerformanceAccessGuard(repository).require_contract(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        for_write=True,
    )

    assert contract.status is status
    assert repository.contract.status is original_status
    assert repository.calls == [("contract", OWNER_ID, CONTRACT_ID)]


@pytest.mark.parametrize(
    "status",
    [status for status in ContractStatus if status not in PERFORMANCE_WRITE_CONTRACT_STATUSES],
)
async def test_write_guard_rejects_other_contract_statuses(status: ContractStatus) -> None:
    repository = FakePerformanceAccessRepository(status=status)

    with pytest.raises(InvalidStatusTransition) as caught:
        await PerformanceAccessGuard(repository).require_contract(
            owner_id=OWNER_ID,
            contract_id=CONTRACT_ID,
            for_write=True,
        )

    assert caught.value.code is ErrorCode.INVALID_STATUS_TRANSITION


async def test_read_guard_allows_an_owned_contract_in_any_status() -> None:
    repository = FakePerformanceAccessRepository(status=ContractStatus.DRAFT)

    contract = await PerformanceAccessGuard(repository).require_contract(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
    )

    assert contract.status is ContractStatus.DRAFT


async def test_foreign_owner_and_cross_contract_report_are_hidden_as_not_found() -> None:
    guard = PerformanceAccessGuard(FakePerformanceAccessRepository())
    with pytest.raises(ResourceNotFound):
        await guard.require_contract(owner_id=OTHER_OWNER_ID, contract_id=CONTRACT_ID)

    mismatched = FakePerformanceAccessRepository(report_contract_id=uuid4())
    with pytest.raises(ResourceNotFound):
        await PerformanceAccessGuard(mismatched).require_report(
            owner_id=OWNER_ID,
            contract_id=CONTRACT_ID,
            report_id=REPORT_ID,
        )


@pytest.mark.parametrize(
    ("document_type", "document_contract_id"),
    [
        (DocumentType.CONTRACT, CONTRACT_ID),
        (DocumentType.PERFORMANCE_REPORT, UUID("00000000-0000-4000-8000-000000000042")),
    ],
)
async def test_report_requires_same_contract_performance_source_document(
    document_type: DocumentType,
    document_contract_id: UUID,
) -> None:
    repository = FakePerformanceAccessRepository(
        document_type=document_type,
        document_contract_id=document_contract_id,
    )

    with pytest.raises(ResourceNotFound):
        await PerformanceAccessGuard(repository).require_report(
            owner_id=OWNER_ID,
            contract_id=CONTRACT_ID,
            report_id=REPORT_ID,
        )


async def test_report_guard_returns_fully_validated_context_without_contract_mutation() -> None:
    repository = FakePerformanceAccessRepository(status=ContractStatus.IN_PROGRESS)
    guard = PerformanceAccessGuard(repository)

    context = await guard.require_report(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        report_id=REPORT_ID,
        for_write=True,
    )

    assert context.contract.status is ContractStatus.IN_PROGRESS
    assert context.report.contract_id == context.contract.id
    assert context.source_document.id == context.report.source_document_id
    assert context.source_document.type is DocumentType.PERFORMANCE_REPORT
    assert repository.contract.status is ContractStatus.IN_PROGRESS


def test_period_identity_normalizes_whitespace_and_rejects_invalid_months() -> None:
    identity = PerformanceReportIdentity(contract_id=CONTRACT_ID, period=" 2026-08 ")

    assert identity.period == "2026-08"
    assert normalize_performance_period("2026-12") == "2026-12"
    for invalid in ("2026-00", "2026-13", "26-08", "2026-8", "２０２６-08"):
        with pytest.raises(ValueError):
            PerformanceReportIdentity(contract_id=CONTRACT_ID, period=invalid)


async def test_month_duplicate_is_mapped_to_the_approved_conflict() -> None:
    repository = FakePerformanceAccessRepository(period_exists=True)

    with pytest.raises(PerformanceReportPeriodAlreadyExists) as caught:
        await PerformanceAccessGuard(repository).require_available_identity(
            owner_id=OWNER_ID,
            contract_id=CONTRACT_ID,
            period=" 2026-08 ",
        )

    assert caught.value.status_code == 409
    assert caught.value.code is ErrorCode.REPORT_PERIOD_ALREADY_EXISTS
    assert repository.calls[-1] == ("period:2026-08", OWNER_ID, CONTRACT_ID)


async def test_available_identity_is_owner_scoped_and_preserves_contract_status() -> None:
    repository = FakePerformanceAccessRepository(status=ContractStatus.COMPLETED)

    contract, identity = await PerformanceAccessGuard(repository).require_available_identity(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        period="2026-08",
    )

    assert contract.status is ContractStatus.COMPLETED
    assert identity == PerformanceReportIdentity(contract_id=CONTRACT_ID, period="2026-08")
    assert repository.contract.status is ContractStatus.COMPLETED
