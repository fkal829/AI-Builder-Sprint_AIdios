import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

from pypdf import PdfReader

from app.core.enums import (
    AgreementClauseCategory,
    AgreementClauseDisposition,
    AgreementClauseOutcome,
    ContractStatus,
    IdempotencyOperation,
)
from app.core.exceptions import ExternalStorageFailure, ResourceNotFound
from app.repositories.agreements import (
    AgreementCreationContext,
    AgreementRecord,
    AgreementRepository,
)
from app.repositories.documents import PrivateStorage
from app.schemas.agreements import (
    AGREEMENT_TITLE,
    Agreement,
    AgreementClause,
    AgreementConditionSummary,
    OriginalContractReference,
)
from app.services.agreement_pdf import AgreementPdfRenderer
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.state_machine import InvalidStatusTransition

_MISSING = "원계약에서 확인되지 않아 추가 확인 필요"


class AgreementService:
    """Build and persist a deterministic agreement from confirmed adjustment data."""

    def __init__(
        self,
        *,
        repository: AgreementRepository,
        storage: PrivateStorage,
        pdf_renderer: AgreementPdfRenderer,
        idempotency: IdempotencyService,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._pdf_renderer = pdf_renderer
        self._idempotency = idempotency
        self._now = now or (lambda: datetime.now(UTC))

    async def create(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        idempotency_key: UUID,
    ) -> Agreement:
        async def perform() -> IdempotentOutcome[Agreement]:
            context = await self._repository.get_agreement_creation_context(
                owner_id=owner_id,
                contract_id=contract_id,
            )
            if context is None:
                raise ResourceNotFound()
            existing = await self._repository.get_owned_agreement(
                owner_id=owner_id,
                contract_id=contract_id,
            )
            if existing is not None:
                raise InvalidStatusTransition("이미 생성된 합의서가 있습니다.")
            agreement = _agreement_from_context(context)
            pdf_content = self._pdf_renderer.render(agreement)
            pdf_id = uuid4()
            pdf_storage_path = (
                f"{owner_id}/{contract_id}/agreements/{agreement.id}/v{agreement.version}/{pdf_id}.pdf"
            )
            record = AgreementRecord(
                agreement=agreement,
                adjustment_request_id=_confirmed_request_id(context),
                pdf_storage_path=pdf_storage_path,
                pdf_sha256=hashlib.sha256(pdf_content).hexdigest(),
                pdf_size_bytes=len(pdf_content),
                pdf_page_count=len(PdfReader(BytesIO(pdf_content), strict=True).pages),
                created_at=self._utc_now(),
            )
            await self._storage.upload_private_object(
                path=record.pdf_storage_path,
                content=pdf_content,
                content_type="application/pdf",
            )
            try:
                saved = await self._repository.create_agreement_with_audit(
                    owner_id=owner_id,
                    record=record,
                )
            except ExternalStorageFailure as error:
                try:
                    await self._storage.delete_private_object(path=record.pdf_storage_path)
                except ExternalStorageFailure as rollback_error:
                    raise ExternalStorageFailure(
                        "합의서 메타데이터 저장과 Storage 롤백에 실패했습니다."
                    ) from rollback_error
                raise error
            if saved is None:
                await self._storage.delete_private_object(path=record.pdf_storage_path)
                raise InvalidStatusTransition("합의서를 생성할 수 없는 상태입니다.")
            return IdempotentOutcome(
                status_code=201,
                response=saved.agreement,
                replay_payload=saved.agreement.model_dump(mode="json"),
            )

        result = await self._idempotency.execute(
            owner_id=owner_id,
            operation=IdempotencyOperation.AGREEMENT_CREATE,
            resource_id=contract_id,
            key=idempotency_key,
            request_payload={},
            perform=perform,
            replay=lambda stored: Agreement.model_validate(stored),
        )
        return result.response

    async def get(self, *, owner_id: UUID, contract_id: UUID) -> Agreement:
        record = await self._repository.get_owned_agreement(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if record is None:
            raise ResourceNotFound()
        return record.agreement

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Agreement timestamps must be timezone-aware.")
        return value.astimezone(UTC)


def _agreement_from_context(context: AgreementCreationContext) -> Agreement:
    contract = context.contract
    if contract.status != ContractStatus.READY_TO_SIGN:
        raise InvalidStatusTransition("확정된 조정 결과에서만 합의서를 만들 수 있습니다.")
    if contract.signed_date is None or context.original_document_id is None:
        raise InvalidStatusTransition("원계약 문서와 검증된 체결일이 필요합니다.")
    if not context.final_clauses:
        raise InvalidStatusTransition("확정된 조정 조항이 없습니다.")
    return Agreement(
        id=uuid4(),
        version=1,
        contract_id=contract.id,
        title=AGREEMENT_TITLE,
        original_contract=OriginalContractReference(
            title=contract.title,
            signed_date=contract.signed_date,
            document_id=context.original_document_id,
        ),
        condition_summary=_condition_summary(context),
        clauses=[
            AgreementClause(
                review_item_id=clause.review_item_id,
                category=AgreementClauseCategory(clause.category),
                outcome=AgreementClauseOutcome(clause.outcome),
                disposition=AgreementClauseDisposition(clause.disposition),
                before=clause.before_text,
                after=clause.after_text,
                reason=clause.reason,
            )
            for clause in context.final_clauses
        ],
        unchanged_terms_policy=(
            "이 합의서에서 명시적으로 변경하지 않은 원계약 조건은 그대로 유지합니다."
        ),
        signature_roles=["OWNER", "AGENCY"],
    )


def _confirmed_request_id(context: AgreementCreationContext) -> UUID:
    if context.adjustment_request_id is None:
        raise InvalidStatusTransition("확정된 조정 요청을 찾을 수 없습니다.")
    return context.adjustment_request_id


def _condition_summary(context: AgreementCreationContext) -> AgreementConditionSummary:
    contract = context.contract
    clauses_by_category: dict[AgreementClauseCategory, list[str]] = {
        category: [] for category in AgreementClauseCategory
    }
    for clause in context.final_clauses:
        clauses_by_category[AgreementClauseCategory(clause.category)].append(
            clause.after_text
        )
    return AgreementConditionSummary(
        term_and_payment=_summary_text(
            "계약기간·총액·결제",
            [
                _date_text("계약 시작일", contract.start_date),
                _date_text("계약 종료일", contract.end_date),
                _amount_text(contract.total_amount),
                _MISSING + "(결제 일정)",
                *clauses_by_category[AgreementClauseCategory.TERM_AND_PAYMENT],
            ],
        ),
        deliverables_and_reporting=_summary_text(
            "산출물·채널·보고",
            [
                _MISSING + "(산출물·광고 채널·보고 방식)",
                *clauses_by_category[AgreementClauseCategory.DELIVERABLES],
            ],
        ),
        termination_and_renewal=_summary_text(
            "해지·환불·자동갱신",
            [
                _text_or_missing("갱신 방식", contract.renewal_type),
                _date_text("해지 통지일", contract.termination_notice_date),
                _MISSING + "(해지·환불 조건)",
                *clauses_by_category[AgreementClauseCategory.TERMINATION_AND_RENEWAL],
            ],
        ),
        rights_safety_and_liability=_summary_text(
            "권리·안전·책임",
            [
                _MISSING + "(콘텐츠·계정 권리, 촬영 안전, 시설 파손·손해 책임, 초상권·개인정보)",
                *clauses_by_category[AgreementClauseCategory.RIGHTS_AND_SAFETY],
            ],
        ),
    )


def _summary_text(label: str, parts: list[str]) -> str:
    return f"{label}: " + "; ".join(parts)


def _date_text(label: str, value: Any) -> str:
    return f"{label} {value.isoformat()}" if value is not None else f"{_MISSING}({label})"


def _amount_text(value: int | None) -> str:
    return f"계약 총액 {value:,}원" if value is not None else f"{_MISSING}(계약 총액)"


def _text_or_missing(label: str, value: str | None) -> str:
    return f"{label} {value}" if value else f"{_MISSING}({label})"
