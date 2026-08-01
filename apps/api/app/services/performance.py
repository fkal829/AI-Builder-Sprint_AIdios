import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from app.core.enums import ContractStatus, IdempotencyOperation
from app.core.exceptions import PerformanceReportPeriodAlreadyExists, ResourceNotFound
from app.repositories.documents import DocumentRecord
from app.repositories.performance import (
    PerformanceAccessRepository,
    PerformanceContractAccess,
    PerformanceReportAccess,
)
from app.schemas.documents import DocumentType
from app.services.state_machine import InvalidStatusTransition

PERFORMANCE_WRITE_CONTRACT_STATUSES: Final[frozenset[ContractStatus]] = frozenset(
    {
        ContractStatus.SIGNED,
        ContractStatus.IN_PROGRESS,
        ContractStatus.RENEWAL_DUE,
        ContractStatus.COMPLETED,
    }
)


class PerformanceWriteAction(StrEnum):
    UPLOAD = "UPLOAD"
    EXTRACT = "EXTRACT"
    CONFIRM = "CONFIRM"


PERFORMANCE_IDEMPOTENCY_OPERATION_BY_ACTION: Final[
    Mapping[PerformanceWriteAction, IdempotencyOperation]
] = MappingProxyType(
    {
        PerformanceWriteAction.UPLOAD: IdempotencyOperation.PERFORMANCE_REPORT_UPLOAD,
        PerformanceWriteAction.EXTRACT: IdempotencyOperation.PERFORMANCE_REPORT_EXTRACT,
        PerformanceWriteAction.CONFIRM: IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM,
    }
)

_PERFORMANCE_PERIOD = re.compile(
    r"^(?:[1-9][0-9]{3}|0[1-9][0-9]{2}|00[1-9][0-9]|000[1-9])-(0[1-9]|1[0-2])$"
)
PERFORMANCE_REPORT_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {"application/pdf", "image/png", "image/jpeg"}
)


@dataclass(frozen=True)
class PerformanceReportIdentity:
    """The only logical report identity supported by P2: contract and calendar month."""

    contract_id: UUID
    period: str

    def __post_init__(self) -> None:
        normalized = normalize_performance_period(self.period)
        object.__setattr__(self, "period", normalized)


@dataclass(frozen=True)
class PerformanceReportContext:
    """Validated owner, contract, report and private source-document relationship."""

    contract: PerformanceContractAccess
    report: PerformanceReportAccess
    source_document: DocumentRecord


def normalize_performance_period(period: str) -> str:
    """Return the canonical YYYY-MM identity used for unique checks and fingerprints."""

    if not isinstance(period, str):
        raise TypeError("성과 리포트 월은 문자열이어야 합니다.")
    normalized = period.strip()
    if _PERFORMANCE_PERIOD.fullmatch(normalized) is None:
        raise ValueError("성과 리포트 월은 YYYY-MM 형식이어야 합니다.")
    return normalized


def performance_idempotency_operation(action: PerformanceWriteAction) -> IdempotencyOperation:
    """Map each performance write to its shared idempotency namespace."""

    return PERFORMANCE_IDEMPOTENCY_OPERATION_BY_ACTION[action]


def performance_upload_idempotency_payload(
    *,
    period: str,
    content: bytes,
    verified_content_type: str,
) -> dict[str, str | int]:
    """Build the safe canonical multipart identity consumed by IdempotencyService.

    ``verified_content_type`` must be the MIME obtained after magic-byte validation.
    The raw report is never retained in the idempotency record or returned payload.
    """

    normalized_period = normalize_performance_period(period)
    if not content:
        raise ValueError("빈 광고효과 리포트는 멱등 요청으로 처리할 수 없습니다.")
    if verified_content_type not in PERFORMANCE_REPORT_CONTENT_TYPES:
        raise ValueError("검증된 PDF, PNG, JPEG MIME만 사용할 수 있습니다.")
    return {
        "period": normalized_period,
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "content_type": verified_content_type,
        "size_bytes": len(content),
    }


class PerformanceAccessGuard:
    """Central owner/status/source guard for the planned performance endpoints.

    The guard only depends on a read-only contract projection. Consequently no
    report operation routed through this foundation can transition Contract.status.
    """

    def __init__(self, repository: PerformanceAccessRepository) -> None:
        self._repository = repository

    async def require_contract(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        for_write: bool = False,
    ) -> PerformanceContractAccess:
        contract = await self._repository.get_owned_performance_contract(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if contract is None or contract.id != contract_id or contract.owner_id != owner_id:
            raise ResourceNotFound()
        if for_write and contract.status not in PERFORMANCE_WRITE_CONTRACT_STATUSES:
            allowed = ", ".join(
                sorted(status.value for status in PERFORMANCE_WRITE_CONTRACT_STATUSES)
            )
            raise InvalidStatusTransition(
                f"광고효과 쓰기는 {allowed} 상태의 계약에서만 수행할 수 있습니다."
            )
        return contract

    async def require_report(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        report_id: UUID,
        for_write: bool = False,
    ) -> PerformanceReportContext:
        contract = await self.require_contract(
            owner_id=owner_id,
            contract_id=contract_id,
            for_write=for_write,
        )
        report = await self._repository.get_owned_performance_report(
            owner_id=owner_id,
            contract_id=contract_id,
            report_id=report_id,
        )
        if report is None or report.id != report_id or report.contract_id != contract_id:
            raise ResourceNotFound()
        source_document = await self.require_source_document(
            owner_id=owner_id,
            contract_id=contract_id,
            document_id=report.source_document_id,
        )
        return PerformanceReportContext(
            contract=contract,
            report=report,
            source_document=source_document,
        )

    async def require_source_document(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_id: UUID,
    ) -> DocumentRecord:
        document = await self._repository.get_owned_performance_source_document(
            owner_id=owner_id,
            contract_id=contract_id,
            document_id=document_id,
        )
        if (
            document is None
            or document.id != document_id
            or document.contract_id != contract_id
            or document.type != DocumentType.PERFORMANCE_REPORT
        ):
            raise ResourceNotFound()
        return document

    async def require_available_identity(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        period: str,
    ) -> tuple[PerformanceContractAccess, PerformanceReportIdentity]:
        """Preflight a new month; the DB unique constraint still resolves races."""

        contract = await self.require_contract(
            owner_id=owner_id,
            contract_id=contract_id,
            for_write=True,
        )
        identity = PerformanceReportIdentity(contract_id=contract_id, period=period)
        if await self._repository.has_performance_report_for_period(
            owner_id=owner_id,
            contract_id=identity.contract_id,
            period=identity.period,
        ):
            raise PerformanceReportPeriodAlreadyExists()
        return contract, identity
