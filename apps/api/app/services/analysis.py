import re
from calendar import monthrange
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.adapters.base import DocumentAnalysisAdapter, ParsedDocument
from app.adapters.upstage import UpstageDocumentParseError, UpstageExtractionError
from app.core.enums import (
    AnalysisStatus,
    ContractStatus,
    DetectionMethod,
    ExtractedField,
    ExtractedSourceType,
    ReviewBasisType,
    ReviewItemStatus,
    ReviewSeverity,
    ReviewSignalType,
    VerificationStatus,
)
from app.core.errors import ErrorCode
from app.core.exceptions import (
    AnalysisStartUnavailable,
    ExternalStorageFailure,
    InvalidDocument,
    ResourceNotFound,
)
from app.repositories.analysis import AnalysisRepository, AnalysisTaskRecord
from app.repositories.contracts import ContractRecord, ContractRepository
from app.repositories.documents import DocumentRecord, DocumentRepository, PrivateStorage
from app.repositories.understood_terms import UnderstoodTermRepository
from app.schemas.analysis import (
    Analysis,
    AnalysisStartRequest,
    AnalysisTask,
    ExtractedTerm,
    ExtractedTermCandidate,
    ReviewItem,
)
from app.schemas.documents import DocumentType
from app.schemas.understood_terms import UnderstoodTerm
from app.services.state_machine import InvalidStatusTransition

ANALYSIS_FIELDS = (
    ExtractedField.CONTRACT_PARTY_OWNER,
    ExtractedField.CONTRACT_PARTY_AGENCY,
    ExtractedField.CONTRACT_SIGNED_DATE,
    ExtractedField.CONTRACT_START_DATE,
    ExtractedField.CONTRACT_END_DATE,
    ExtractedField.MONTHLY_AMOUNT,
    ExtractedField.CONTRACT_TOTAL_AMOUNT,
    ExtractedField.PAYMENT_METHOD,
    ExtractedField.AUTO_RENEWAL,
    ExtractedField.CONTRACT_RENEWAL_TYPE,
    ExtractedField.TERMINATION_NOTICE_DATE,
    ExtractedField.EARLY_TERMINATION_ALLOWED,
    ExtractedField.TERMINATION_PENALTY_RATE,
    ExtractedField.REFUND_CONDITION,
    ExtractedField.ADVERTISING_CHANNEL,
    ExtractedField.CONTENT_TYPE,
    ExtractedField.CONTENT_QUANTITY,
    ExtractedField.DELIVERABLE_DUE_DATE,
    ExtractedField.POSTING_FREQUENCY,
    ExtractedField.REPORTING_FREQUENCY,
    ExtractedField.PERFORMANCE_GUARANTEE,
    ExtractedField.ADVERTISING_ACCOUNT_OWNERSHIP,
    ExtractedField.CONTENT_OWNERSHIP,
    ExtractedField.SHOOTING_SAFETY,
    ExtractedField.PORTRAIT_RIGHTS,
    ExtractedField.PERSONAL_INFORMATION_HANDLING,
    ExtractedField.FACILITY_DAMAGE_LIABILITY,
    ExtractedField.FALSE_ADVERTISING_LIABILITY,
)


class AnalysisPipelineFailure(RuntimeError):
    def __init__(self, *, error_code: ErrorCode, attempt_count: int) -> None:
        super().__init__(error_code.value)
        self.error_code = error_code
        self.attempt_count = max(1, min(attempt_count, 2))


class AnalysisService:
    def __init__(
        self,
        *,
        adapter: DocumentAnalysisAdapter,
        contracts: ContractRepository,
        documents: DocumentRepository,
        understood_terms: UnderstoodTermRepository,
        analyses: AnalysisRepository,
        storage: PrivateStorage,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.adapter = adapter
        self.contracts = contracts
        self.documents = documents
        self.understood_terms = understood_terms
        self.analyses = analyses
        self.storage = storage
        self._now = now or (lambda: datetime.now(UTC))

    async def start(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: AnalysisStartRequest,
    ) -> AnalysisTask:
        try:
            contract = await self.contracts.get(owner_id=owner_id, contract_id=contract_id)
            if contract is None:
                raise ResourceNotFound()

            document = await self.documents.get_owned_document(
                owner_id=owner_id,
                contract_id=contract_id,
                document_id=payload.document_id,
            )
            if document is None:
                raise ResourceNotFound()
            if document.type != DocumentType.CONTRACT:
                raise InvalidDocument("분석 대상은 CONTRACT 문서여야 합니다.")

            latest_contract_document = await self.documents.get_latest_owned_document(
                owner_id=owner_id,
                contract_id=contract_id,
                document_type=DocumentType.CONTRACT,
            )
            if latest_contract_document is None or latest_contract_document.id != document.id:
                raise InvalidDocument("가장 최근에 업로드한 CONTRACT 문서만 분석할 수 있습니다.")

            for supporting_document_id in payload.supporting_document_ids:
                supporting = await self.documents.get_owned_document(
                    owner_id=owner_id,
                    contract_id=contract_id,
                    document_id=supporting_document_id,
                )
                if supporting is None:
                    raise ResourceNotFound()
                if supporting.type not in {
                    DocumentType.PROPOSAL,
                    DocumentType.ESTIMATE,
                    DocumentType.MESSAGE,
                }:
                    raise InvalidDocument(
                        "선택 자료는 PROPOSAL, ESTIMATE, MESSAGE 문서만 허용됩니다."
                    )

            latest_task = await self.analyses.get_latest_analysis_task(
                owner_id=owner_id,
                contract_id=contract_id,
            )
            if latest_task is not None and latest_task.status in {
                AnalysisStatus.QUEUED,
                AnalysisStatus.PROCESSING,
            }:
                raise InvalidStatusTransition("이미 실행 중인 분석 작업이 있습니다.")

            restart = latest_task is not None and latest_task.status == AnalysisStatus.FAILED
            if restart:
                if contract.status != ContractStatus.ANALYZING:
                    raise InvalidStatusTransition(
                        "실패한 분석은 ANALYZING 계약에서만 재시작합니다."
                    )
            elif contract.status != ContractStatus.DRAFT:
                raise InvalidStatusTransition("DRAFT 계약에서만 최초 분석을 시작할 수 있습니다.")

            now = self._now()
            task = AnalysisTaskRecord(
                id=uuid4(),
                contract_id=contract_id,
                document_id=document.id,
                supporting_document_ids=tuple(payload.supporting_document_ids),
                status=AnalysisStatus.QUEUED,
                attempt_count=0,
                error_code=None,
                result=None,
                created_at=now,
                updated_at=now,
            )
            saved = await self.analyses.start_analysis_with_audit(
                owner_id=owner_id,
                task=task,
                restart=restart,
            )
            if saved is None:
                raise InvalidStatusTransition("분석 시작 조건이 변경되었습니다.")
            return _task_from_record(saved)
        except (ResourceNotFound, InvalidDocument, InvalidStatusTransition):
            raise
        except ExternalStorageFailure as error:
            raise AnalysisStartUnavailable() from error

    async def process(
        self,
        *,
        owner_id: UUID,
        task_id: UUID,
    ) -> None:
        task = await self.analyses.mark_analysis_processing(task_id=task_id)
        if task is None:
            return

        attempt_count = 1
        try:
            contract = await self.contracts.get(
                owner_id=owner_id,
                contract_id=task.contract_id,
            )
            if contract is None:
                raise ResourceNotFound()
            documents = await self._load_task_documents(owner_id=owner_id, task=task)
            all_terms: list[ExtractedTerm] = []
            max_attempt_count = 1
            for document in documents:
                content = await self.storage.download_private_object(path=document.storage_path)
                candidates, used_attempts = await self._extract_with_evaluator(
                    content=content,
                    content_type=document.content_type,
                )
                max_attempt_count = max(max_attempt_count, used_attempts)
                source_type = (
                    ExtractedSourceType.CONTRACT_DOCUMENT
                    if document.id == task.document_id
                    else ExtractedSourceType.DOCUMENTED_EXPLANATION
                )
                all_terms.extend(
                    ExtractedTerm(
                        id=uuid4(),
                        contract_id=task.contract_id,
                        document_id=document.id,
                        source_type=source_type,
                        **candidate.model_dump(),
                    )
                    for candidate in candidates
                )
            attempt_count = max_attempt_count
            understood = await self.understood_terms.get_understood_term(
                owner_id=owner_id,
                contract_id=task.contract_id,
            )
            result = Analysis(
                contract_id=task.contract_id,
                extracted_terms=all_terms,
                review_items=_build_review_items(
                    contract_id=task.contract_id,
                    terms=all_terms,
                    understood=understood,
                    contract=contract,
                ),
            )
            completed = await self.analyses.complete_analysis_with_audit(
                task_id=task.id,
                attempt_count=attempt_count,
                result=result,
            )
            if completed is None:
                raise ExternalStorageFailure("분석 완료 상태 저장에 실패했습니다.")
        except AnalysisPipelineFailure as error:
            await self.analyses.fail_analysis_with_audit(
                task_id=task.id,
                attempt_count=error.attempt_count,
                error_code=error.error_code,
            )
        except (ExternalStorageFailure, ResourceNotFound):
            await self.analyses.fail_analysis_with_audit(
                task_id=task.id,
                attempt_count=attempt_count,
                error_code=ErrorCode.DOCUMENT_PARSE_FAILED,
            )
        except (ValidationError, ValueError):
            await self.analyses.fail_analysis_with_audit(
                task_id=task.id,
                attempt_count=attempt_count,
                error_code=ErrorCode.ANALYSIS_SCHEMA_INVALID,
            )

    async def _load_task_documents(
        self,
        *,
        owner_id: UUID,
        task: AnalysisTaskRecord,
    ) -> list[DocumentRecord]:
        records: list[DocumentRecord] = []
        for document_id in (task.document_id, *task.supporting_document_ids):
            document = await self.documents.get_owned_document(
                owner_id=owner_id,
                contract_id=task.contract_id,
                document_id=document_id,
            )
            if document is None:
                raise ResourceNotFound()
            records.append(document)
        return records

    async def _extract_with_evaluator(
        self,
        *,
        content: bytes,
        content_type: str,
    ) -> tuple[list[ExtractedTermCandidate], int]:
        try:
            parsed = await self.adapter.parse_document(
                content=content,
                content_type=content_type,
            )
        except UpstageDocumentParseError as error:
            raise AnalysisPipelineFailure(
                error_code=ErrorCode.DOCUMENT_PARSE_FAILED,
                attempt_count=1,
            ) from error

        candidates_by_field: dict[ExtractedField, ExtractedTermCandidate] = {}
        target_fields = ANALYSIS_FIELDS
        for attempt_count in (1, 2):
            try:
                extracted = await self.adapter.extract_terms(
                    content=content,
                    content_type=content_type,
                    parsed_document=parsed,
                    target_fields=target_fields,
                )
                _validate_unique_fields(extracted)
            except (UpstageExtractionError, ValidationError, ValueError) as error:
                if attempt_count == 2:
                    raise AnalysisPipelineFailure(
                        error_code=ErrorCode.ANALYSIS_SCHEMA_INVALID,
                        attempt_count=attempt_count,
                    ) from error
                continue

            for candidate in extracted:
                candidates_by_field[candidate.field] = _verify_candidate_evidence(
                    candidate,
                    parsed,
                )
            unresolved = tuple(
                field
                for field in ANALYSIS_FIELDS
                if field not in candidates_by_field
                or candidates_by_field[field].verification_status
                in {
                    VerificationStatus.NOT_FOUND,
                    VerificationStatus.MISSING_EVIDENCE,
                    VerificationStatus.NEEDS_CHECK,
                }
            )
            if not unresolved:
                return list(candidates_by_field.values()), attempt_count
            if attempt_count == 1:
                target_fields = unresolved
                continue

            for field in unresolved:
                candidates_by_field.setdefault(field, _not_found_candidate(field))
            return list(candidates_by_field.values()), attempt_count

        raise AnalysisPipelineFailure(
            error_code=ErrorCode.ANALYSIS_SCHEMA_INVALID,
            attempt_count=2,
        )


def _task_from_record(record: AnalysisTaskRecord) -> AnalysisTask:
    return AnalysisTask(
        id=record.id,
        contract_id=record.contract_id,
        document_id=record.document_id,
        supporting_document_ids=list(record.supporting_document_ids),
        status=record.status,
        attempt_count=record.attempt_count,
        error_code=record.error_code,
        result=record.result,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _validate_unique_fields(candidates: list[ExtractedTermCandidate]) -> None:
    fields = [candidate.field for candidate in candidates]
    if len(fields) != len(set(fields)):
        raise ValueError("한 번의 추출 결과에 같은 필드가 중복되었습니다.")


def _verify_candidate_evidence(
    candidate: ExtractedTermCandidate,
    parsed: ParsedDocument,
) -> ExtractedTermCandidate:
    if candidate.verification_status not in {
        VerificationStatus.VERIFIED,
        VerificationStatus.NEEDS_CHECK,
    }:
        return candidate
    pages = {page.number: page.text for page in parsed.pages}
    page_text = pages.get(candidate.source_page)
    if (
        page_text is None
        or candidate.source_text is None
        or _normalized_text(candidate.source_text) not in _normalized_text(page_text)
    ):
        return ExtractedTermCandidate(
            field=candidate.field,
            value_type=candidate.value_type,
            value=candidate.value,
            source_page=None,
            source_text=None,
            confidence=candidate.confidence,
            verification_status=VerificationStatus.MISSING_EVIDENCE,
        )
    return candidate


def _not_found_candidate(field: ExtractedField) -> ExtractedTermCandidate:
    from app.core.enums import ExtractedValueType
    from app.schemas.analysis import EXPECTED_VALUE_TYPES

    return ExtractedTermCandidate(
        field=field,
        value_type=EXPECTED_VALUE_TYPES.get(field, ExtractedValueType.TEXT),
        value=None,
        source_page=None,
        source_text=None,
        confidence=0,
        verification_status=VerificationStatus.NOT_FOUND,
    )


def _build_review_items(
    *,
    contract_id: UUID,
    terms: list[ExtractedTerm],
    understood: UnderstoodTerm | None,
    contract: ContractRecord | None = None,
) -> list[ReviewItem]:
    contract_terms = {
        term.field: term
        for term in terms
        if term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT
    }
    reviews: list[ReviewItem] = []
    for field in ANALYSIS_FIELDS:
        term = contract_terms.get(field)
        if term is None:
            continue
        if term.verification_status != VerificationStatus.VERIFIED:
            reviews.append(
                _review_for_term(
                    contract_id=contract_id,
                    term=term,
                    signal=(
                        ReviewSignalType.MISSING
                        if term.verification_status == VerificationStatus.NOT_FOUND
                        else ReviewSignalType.NEEDS_CHECK
                    ),
                    severity=ReviewSeverity.CHECK,
                    explanation=f"{field.value} 조건을 계약 원문에서 명확히 확인하지 못했습니다.",
                )
            )

    if contract is not None:
        canonical_fields = (
            (ExtractedField.CONTRACT_SIGNED_DATE, "signed_date", "계약 체결일"),
            (ExtractedField.CONTRACT_START_DATE, "start_date", "계약 시작일"),
            (ExtractedField.CONTRACT_END_DATE, "end_date", "계약 종료일"),
            (
                ExtractedField.TERMINATION_NOTICE_DATE,
                "termination_notice_date",
                "해지 통보기한",
            ),
            (ExtractedField.CONTRACT_RENEWAL_TYPE, "renewal_type", "갱신 유형"),
            (ExtractedField.CONTRACT_TOTAL_AMOUNT, "total_amount", "총 계약금액"),
        )
        for field, attribute, label in canonical_fields:
            term = contract_terms.get(field)
            current = getattr(contract, attribute)
            if (
                current is not None
                and term is not None
                and term.verification_status == VerificationStatus.VERIFIED
                and _canonical_term_value(term) != current
            ):
                reviews.append(
                    _review_for_term(
                        contract_id=contract_id,
                        term=term,
                        signal=ReviewSignalType.MISMATCH,
                        severity=ReviewSeverity.IMPORTANT,
                        explanation=(
                            f"저장된 {label}과 최신 계약 원문의 {label}이 다릅니다."
                        ),
                    )
                )

    if understood is not None:
        duration_months = _duration_months(understood.duration_text)
        start_term = contract_terms.get(ExtractedField.CONTRACT_START_DATE)
        end_term = contract_terms.get(ExtractedField.CONTRACT_END_DATE)
        if (
            duration_months is not None
            and start_term is not None
            and end_term is not None
            and start_term.verification_status == VerificationStatus.VERIFIED
            and end_term.verification_status == VerificationStatus.VERIFIED
            and not _duration_matches(
                start=date.fromisoformat(str(start_term.value)),
                end=date.fromisoformat(str(end_term.value)),
                months=duration_months,
            )
        ):
            reviews.append(
                _review_for_term(
                    contract_id=contract_id,
                    term=end_term,
                    related_terms=(start_term, end_term),
                    signal=ReviewSignalType.MISMATCH,
                    severity=ReviewSeverity.IMPORTANT,
                    explanation="사용자가 이해한 계약기간과 계약 원문의 계약기간이 다릅니다.",
                )
            )

        comparisons = (
            (
                ExtractedField.MONTHLY_AMOUNT,
                understood.monthly_amount,
                "월 납부액",
            ),
            (
                ExtractedField.CONTRACT_TOTAL_AMOUNT,
                understood.total_amount,
                "총 계약금액",
            ),
        )
        for field, expected, label in comparisons:
            term = contract_terms.get(field)
            if (
                expected is not None
                and term is not None
                and term.verification_status == VerificationStatus.VERIFIED
                and term.value != expected
            ):
                reviews.append(
                    _review_for_term(
                        contract_id=contract_id,
                        term=term,
                        signal=ReviewSignalType.MISMATCH,
                        severity=ReviewSeverity.IMPORTANT,
                        explanation=(
                            f"사용자가 이해한 {label}과 계약 원문의 {label}이 다릅니다."
                        ),
                    )
                )
        refund = contract_terms.get(ExtractedField.REFUND_CONDITION)
        if (
            refund is not None
            and refund.verification_status == VerificationStatus.VERIFIED
            and _normalized_text(understood.refund_text)
            not in _normalized_text(str(refund.value))
        ):
            reviews.append(
                _review_for_term(
                    contract_id=contract_id,
                    term=refund,
                    signal=ReviewSignalType.MISMATCH,
                    severity=ReviewSeverity.IMPORTANT,
                    explanation="사용자가 이해한 환불 조건과 계약 원문의 환불 조건이 다릅니다.",
                )
            )
        understood_termination = _understood_termination_value(
            understood.termination_text
        )
        termination = contract_terms.get(ExtractedField.EARLY_TERMINATION_ALLOWED)
        if (
            understood_termination is not None
            and termination is not None
            and termination.verification_status == VerificationStatus.VERIFIED
            and termination.value != understood_termination
        ):
            reviews.append(
                _review_for_term(
                    contract_id=contract_id,
                    term=termination,
                    signal=ReviewSignalType.MISMATCH,
                    severity=ReviewSeverity.IMPORTANT,
                    explanation=(
                        "사용자가 이해한 중도해지 가능 여부와 계약 원문의 조건이 다릅니다."
                    ),
                )
            )
    return reviews


def _canonical_term_value(term: ExtractedTerm) -> object:
    if term.field in {
        ExtractedField.CONTRACT_SIGNED_DATE,
        ExtractedField.CONTRACT_START_DATE,
        ExtractedField.CONTRACT_END_DATE,
        ExtractedField.TERMINATION_NOTICE_DATE,
    }:
        return date.fromisoformat(str(term.value))
    return term.value


def _review_for_term(
    *,
    contract_id: UUID,
    term: ExtractedTerm,
    related_terms: tuple[ExtractedTerm, ...] | None = None,
    signal: ReviewSignalType,
    severity: ReviewSeverity,
    explanation: str,
) -> ReviewItem:
    has_evidence = term.source_page is not None and term.source_text is not None
    verification_status = (
        term.verification_status
        if term.verification_status
        in {
            VerificationStatus.VERIFIED,
            VerificationStatus.NOT_FOUND,
            VerificationStatus.MISSING_EVIDENCE,
            VerificationStatus.NEEDS_CHECK,
        }
        else VerificationStatus.NEEDS_CHECK
    )
    return ReviewItem(
        id=uuid4(),
        contract_id=contract_id,
        type=signal,
        severity=severity,
        detection_method=DetectionMethod.DETERMINISTIC,
        model_confidence=None,
        model_limitations=None,
        plain_explanation=explanation,
        basis_type=ReviewBasisType.INTERNAL_RULE,
        basis_text="계약 원문과 사용자가 저장한 이해조건을 분리해 비교하는 내부 확인 규칙",
        basis_citation=None,
        related_extracted_term_ids=[
            related.id for related in (related_terms or (term,))
        ],
        source_document_id=term.document_id if has_evidence else None,
        source_page=term.source_page if has_evidence else None,
        source_text=term.source_text if has_evidence else None,
        source_confidence=term.confidence if has_evidence else None,
        verification_status=verification_status,
        suggestion_accept="계약 원문 조건을 그대로 확인합니다.",
        suggestion_compromise="서로 이해한 조건을 확인해 조정 가능한 문구를 협의합니다.",
        suggestion_request="확인된 조건을 계약 문구에 명확히 적어 달라고 요청합니다.",
        user_choice=None,
        status=ReviewItemStatus.UNREVIEWED,
    )


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _duration_months(value: str) -> int | None:
    normalized = _normalized_text(value)
    years = re.search(r"(\d+)년", normalized)
    months = re.search(r"(\d+)개월", normalized)
    if years is None and months is None:
        return None
    total = int(years.group(1)) * 12 if years is not None else 0
    total += int(months.group(1)) if months is not None else 0
    return total if total > 0 else None


def _duration_matches(*, start: date, end: date, months: int) -> bool:
    month_index = start.year * 12 + start.month - 1 + months
    target_year, zero_based_month = divmod(month_index, 12)
    target_month = zero_based_month + 1
    target_day = min(start.day, monthrange(target_year, target_month)[1])
    exclusive_end = date(target_year, target_month, target_day)
    return end in {exclusive_end, exclusive_end - timedelta(days=1)}


def _understood_termination_value(value: str) -> str | None:
    normalized = _normalized_text(value)
    if any(token in normalized for token in ("불가능", "불가", "할수없", "안됨")):
        return "NO"
    if any(token in normalized for token in ("가능", "할수있")):
        return "YES"
    return None
