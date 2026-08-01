import logging
import re
from calendar import monthrange
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError

from app.adapters.base import ContractReviewAdapter, DocumentAnalysisAdapter, ParsedDocument
from app.adapters.solar import SOLAR_CONFIDENCE_LIMITATION, SolarReviewError
from app.adapters.upstage import UpstageDocumentParseError, UpstageExtractionError
from app.core.enums import (
    AnalysisStatus,
    ContractStatus,
    DetectionMethod,
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
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
from app.domain.obligations import (
    REPRESENTATIVE_OBLIGATION_FIELDS,
    REPRESENTATIVE_TITLE_FIELDS,
    build_representative_obligation,
)
from app.repositories.analysis import AnalysisRepository, AnalysisTaskRecord
from app.repositories.contracts import ContractRecord, ContractRepository
from app.repositories.documents import DocumentRecord, DocumentRepository, PrivateStorage
from app.repositories.understood_terms import UnderstoodTermRepository
from app.schemas.analysis import (
    Analysis,
    AnalysisStartRequest,
    AnalysisTask,
    DocumentClause,
    ExtractedTerm,
    ExtractedTermCandidate,
    ReviewItem,
    SolarReviewInput,
    SolarReviewOutput,
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

REVIEW_FIELD_LABELS: dict[ExtractedField, str] = {
    ExtractedField.CONTRACT_PARTY_OWNER: "광고주 계약 당사자",
    ExtractedField.CONTRACT_PARTY_AGENCY: "광고대행사 계약 당사자",
    ExtractedField.CONTRACT_SIGNED_DATE: "계약 체결일",
    ExtractedField.CONTRACT_START_DATE: "계약 시작일",
    ExtractedField.CONTRACT_END_DATE: "계약 종료일",
    ExtractedField.MONTHLY_AMOUNT: "월 납부액",
    ExtractedField.CONTRACT_TOTAL_AMOUNT: "총 계약금액",
    ExtractedField.PAYMENT_METHOD: "결제 방식",
    ExtractedField.AUTO_RENEWAL: "자동갱신 여부",
    ExtractedField.CONTRACT_RENEWAL_TYPE: "갱신 유형",
    ExtractedField.TERMINATION_NOTICE_DATE: "해지 통보기한",
    ExtractedField.EARLY_TERMINATION_ALLOWED: "중도해지 가능 여부",
    ExtractedField.TERMINATION_PENALTY_RATE: "중도해지 위약금",
    ExtractedField.REFUND_CONDITION: "환불 조건",
    ExtractedField.ADVERTISING_CHANNEL: "광고 채널",
    ExtractedField.CONTENT_TYPE: "산출물 유형",
    ExtractedField.CONTENT_QUANTITY: "산출물 수량",
    ExtractedField.DELIVERABLE_DUE_DATE: "산출물 기한",
    ExtractedField.POSTING_FREQUENCY: "게시 빈도",
    ExtractedField.REPORTING_FREQUENCY: "보고 의무",
    ExtractedField.PERFORMANCE_GUARANTEE: "성과 보장 조건",
    ExtractedField.ADVERTISING_ACCOUNT_OWNERSHIP: "광고 계정 소유권",
    ExtractedField.CONTENT_OWNERSHIP: "콘텐츠 소유권",
    ExtractedField.SHOOTING_SAFETY: "촬영 안전",
    ExtractedField.PORTRAIT_RIGHTS: "초상권",
    ExtractedField.PERSONAL_INFORMATION_HANDLING: "개인정보 처리",
    ExtractedField.FACILITY_DAMAGE_LIABILITY: "시설 파손·손해 책임",
    ExtractedField.FALSE_ADVERTISING_LIABILITY: "허위·과장 광고 책임",
}

AMBIGUOUS_CONTRACT_PHRASES = (
    "공란",
    "미기재",
    "수기 입력 예정",
    "별도 협의",
    "추후 결정",
    "상황에 따라 변경",
)
ONE_SIDED_RESPONSIBILITY_PHRASES = (
    "모든 책임",
    "일체의 책임",
    "일체 책임",
    "전적인 책임",
    "전적으로 부담",
    "책임지지 않는다",
    "책임을 지지 않는다",
)
P0_IMPORTANT_MISSING_FIELDS = {
    ExtractedField.CONTENT_QUANTITY,
    ExtractedField.DELIVERABLE_DUE_DATE,
    ExtractedField.REPORTING_FREQUENCY,
    ExtractedField.SHOOTING_SAFETY,
    ExtractedField.FACILITY_DAMAGE_LIABILITY,
    ExtractedField.FALSE_ADVERTISING_LIABILITY,
}
DELIVERABLE_FIELDS = {
    ExtractedField.ADVERTISING_CHANNEL,
    ExtractedField.CONTENT_TYPE,
    ExtractedField.CONTENT_QUANTITY,
    ExtractedField.DELIVERABLE_DUE_DATE,
    ExtractedField.POSTING_FREQUENCY,
    ExtractedField.REPORTING_FREQUENCY,
}
SAFETY_RESPONSIBILITY_FIELDS = {
    ExtractedField.SHOOTING_SAFETY,
    ExtractedField.FACILITY_DAMAGE_LIABILITY,
    ExtractedField.FALSE_ADVERTISING_LIABILITY,
}

logger = logging.getLogger(__name__)

CLAUSE_HEADING_PATTERN = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]*)?"
    r"(?P<heading>제[ \t]*\d+[ \t]*조(?:의[ \t]*\d+)?)"
    r"(?:[ \t]*[（(](?P<title>[^)）\n]{1,80})[)）])?"
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
        reviewer: ContractReviewAdapter,
        contracts: ContractRepository,
        documents: DocumentRepository,
        understood_terms: UnderstoodTermRepository,
        analyses: AnalysisRepository,
        storage: PrivateStorage,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.adapter = adapter
        self.reviewer = reviewer
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

    async def get_latest(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> AnalysisTask:
        task = await self.analyses.get_latest_analysis_task(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if task is None:
            raise ResourceNotFound()
        return _task_from_record(task)

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
            (
                candidates_by_document,
                parsed_documents,
                attempt_count,
            ) = await self._extract_documents_with_evaluator(documents=documents)
            all_terms: list[ExtractedTerm] = []
            for document in documents:
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
                    for candidate in candidates_by_document[document.id]
                )
            understood = await self.understood_terms.get_understood_term(
                owner_id=owner_id,
                contract_id=task.contract_id,
            )
            review_items = _build_review_items(
                contract_id=task.contract_id,
                terms=all_terms,
                understood=understood,
                contract=contract,
            )
            solar_inputs = _build_solar_review_inputs(
                reviews=review_items,
                terms=all_terms,
                understood=understood,
                contract=contract,
            )
            try:
                solar_outputs = await self.reviewer.generate_review_content(
                    items=solar_inputs,
                )
                final_review_items = _apply_solar_review_content(
                    reviews=review_items,
                    outputs=solar_outputs,
                )
            except SolarReviewError as error:
                logger.warning(
                    "analysis_solar_fallback task_id=%s item_count=%d error_type=%s",
                    task.id,
                    len(solar_inputs),
                    type(error).__name__,
                )
                final_review_items = review_items
            result = Analysis(
                contract_id=task.contract_id,
                document_clauses=_build_document_clauses(
                    document_id=task.document_id,
                    parsed_document=parsed_documents[task.document_id],
                ),
                extracted_terms=all_terms,
                review_items=final_review_items,
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

    async def _extract_documents_with_evaluator(
        self,
        *,
        documents: list[DocumentRecord],
    ) -> tuple[
        dict[UUID, list[ExtractedTermCandidate]],
        dict[UUID, ParsedDocument],
        int,
    ]:
        contents: dict[UUID, bytes] = {}
        parsed_documents: dict[UUID, ParsedDocument] = {}
        candidates_by_document: dict[UUID, dict[ExtractedField, ExtractedTermCandidate]] = {
            document.id: {} for document in documents
        }
        target_fields_by_document = {document.id: ANALYSIS_FIELDS for document in documents}

        for document in documents:
            content = await self.storage.download_private_object(path=document.storage_path)
            try:
                parsed = await self.adapter.parse_document(
                    content=content,
                    content_type=document.content_type,
                )
            except UpstageDocumentParseError as error:
                raise AnalysisPipelineFailure(
                    error_code=ErrorCode.DOCUMENT_PARSE_FAILED,
                    attempt_count=1,
                ) from error
            contents[document.id] = content
            parsed_documents[document.id] = parsed

        used_rounds = 1
        for round_number in (1, 2):
            used_rounds = round_number
            for document in documents:
                target_fields = target_fields_by_document[document.id]
                if not target_fields:
                    continue
                try:
                    extracted = await self.adapter.extract_terms(
                        content=contents[document.id],
                        content_type=document.content_type,
                        parsed_document=parsed_documents[document.id],
                        target_fields=target_fields,
                    )
                    _validate_unique_fields(extracted)
                    _validate_target_fields(
                        candidates=extracted,
                        target_fields=target_fields,
                    )
                except (
                    UpstageExtractionError,
                    ValidationError,
                    ValueError,
                ) as error:
                    if round_number == 2:
                        raise AnalysisPipelineFailure(
                            error_code=ErrorCode.ANALYSIS_SCHEMA_INVALID,
                            attempt_count=round_number,
                        ) from error
                    continue

                candidates_by_field = candidates_by_document[document.id]
                for candidate in extracted:
                    candidates_by_field[candidate.field] = _verify_candidate_evidence(
                        candidate,
                        parsed_documents[document.id],
                    )
                _normalize_renewal_candidates(candidates_by_field)
                target_fields_by_document[document.id] = _unresolved_fields(candidates_by_field)

            if not any(target_fields_by_document.values()):
                break

        for document in documents:
            candidates_by_field = candidates_by_document[document.id]
            for field in _unresolved_fields(candidates_by_field):
                candidates_by_field.setdefault(field, _not_found_candidate(field))

        return (
            {
                document.id: list(candidates_by_document[document.id].values())
                for document in documents
            },
            parsed_documents,
            used_rounds,
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


def _build_document_clauses(
    *,
    document_id: UUID,
    parsed_document: ParsedDocument,
) -> list[DocumentClause]:
    """Split the primary document deterministically without dropping non-empty source text."""
    clauses: list[DocumentClause] = []

    def append_clause(
        *,
        page_number: int,
        page_index: int,
        heading: str,
        title: str,
        source_text: str,
    ) -> None:
        cleaned_text = source_text.strip()
        if not cleaned_text:
            return
        ordinal = len(clauses) + 1
        clauses.append(
            DocumentClause(
                id=uuid5(
                    NAMESPACE_URL,
                    (
                        "https://dandi-contract.local/documents/"
                        f"{document_id}/clauses/{page_number}/{page_index}"
                    ),
                ),
                document_id=document_id,
                ordinal=ordinal,
                heading=heading,
                title=title,
                source_page=page_number,
                source_text=cleaned_text,
                confidence=None,
            )
        )

    for page in parsed_document.pages:
        page_text = page.text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not page_text:
            continue
        matches = list(CLAUSE_HEADING_PATTERN.finditer(page_text))
        page_index = 0
        if not matches:
            append_clause(
                page_number=page.number,
                page_index=page_index,
                heading=f"{page.number}쪽 원문",
                title="원문",
                source_text=page_text,
            )
            continue

        leading_text = page_text[: matches[0].start()]
        if leading_text.strip():
            append_clause(
                page_number=page.number,
                page_index=page_index,
                heading=f"{page.number}쪽 원문",
                title="머리말" if not clauses else "이어지는 원문",
                source_text=leading_text,
            )
            page_index += 1

        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
            heading = re.sub(r"[ \t]+", "", match.group("heading"))
            title = (match.group("title") or "계약 조항").strip()
            append_clause(
                page_number=page.number,
                page_index=page_index,
                heading=heading,
                title=title,
                source_text=page_text[match.start() : end],
            )
            page_index += 1

    return clauses


def _validate_unique_fields(candidates: list[ExtractedTermCandidate]) -> None:
    fields = [candidate.field for candidate in candidates]
    if len(fields) != len(set(fields)):
        raise ValueError("한 번의 추출 결과에 같은 필드가 중복되었습니다.")


def _validate_target_fields(
    *,
    candidates: list[ExtractedTermCandidate],
    target_fields: tuple[ExtractedField, ...],
) -> None:
    unexpected = {candidate.field for candidate in candidates} - set(target_fields)
    if unexpected:
        raise ValueError("재추출 대상으로 요청하지 않은 필드가 반환되었습니다.")


def _unresolved_fields(
    candidates_by_field: dict[ExtractedField, ExtractedTermCandidate],
) -> tuple[ExtractedField, ...]:
    return tuple(
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


def _normalize_renewal_candidates(
    candidates_by_field: dict[ExtractedField, ExtractedTermCandidate],
) -> None:
    """Apply renewal implications without promoting ambiguous or conflicting values."""

    auto_renewal = candidates_by_field.get(ExtractedField.AUTO_RENEWAL)
    if auto_renewal is None:
        return

    renewal_type = candidates_by_field.get(ExtractedField.CONTRACT_RENEWAL_TYPE)
    if (
        auto_renewal.verification_status == VerificationStatus.VERIFIED
        and auto_renewal.value == "NO"
        and renewal_type is not None
        and renewal_type.verification_status == VerificationStatus.VERIFIED
        and renewal_type.value == "AUTO"
    ):
        candidates_by_field[ExtractedField.AUTO_RENEWAL] = _candidate_with_status(
            auto_renewal, VerificationStatus.NEEDS_CHECK
        )
        candidates_by_field[ExtractedField.CONTRACT_RENEWAL_TYPE] = _candidate_with_status(
            renewal_type, VerificationStatus.NEEDS_CHECK
        )
        return

    if auto_renewal.value != "YES" or auto_renewal.verification_status not in {
        VerificationStatus.VERIFIED,
        VerificationStatus.NEEDS_CHECK,
    }:
        return

    if (
        renewal_type is not None
        and renewal_type.verification_status == VerificationStatus.VERIFIED
        and renewal_type.value == "AUTO"
    ):
        return

    if (
        auto_renewal.verification_status == VerificationStatus.VERIFIED
        and renewal_type is not None
        and renewal_type.verification_status
        in {VerificationStatus.VERIFIED, VerificationStatus.NEEDS_CHECK}
        and renewal_type.value not in {"AUTO", None}
    ):
        candidates_by_field[ExtractedField.AUTO_RENEWAL] = _candidate_with_status(
            auto_renewal, VerificationStatus.NEEDS_CHECK
        )
        if renewal_type.source_page is not None and renewal_type.source_text is not None:
            candidates_by_field[ExtractedField.CONTRACT_RENEWAL_TYPE] = _candidate_with_status(
                renewal_type,
                VerificationStatus.NEEDS_CHECK,
            )
        return

    if (
        renewal_type is not None
        and renewal_type.verification_status == VerificationStatus.NEEDS_CHECK
    ):
        return

    candidates_by_field[ExtractedField.CONTRACT_RENEWAL_TYPE] = ExtractedTermCandidate(
        field=ExtractedField.CONTRACT_RENEWAL_TYPE,
        value_type=ExtractedValueType.TEXT,
        value="AUTO",
        source_page=auto_renewal.source_page,
        source_text=auto_renewal.source_text,
        confidence=auto_renewal.confidence,
        verification_status=auto_renewal.verification_status,
    )


def _candidate_with_status(
    candidate: ExtractedTermCandidate,
    status: VerificationStatus,
) -> ExtractedTermCandidate:
    return ExtractedTermCandidate.model_validate(
        {
            **candidate.model_dump(),
            "verification_status": status,
        }
    )


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
    documented_terms = _documented_terms_by_field(terms)
    reviews: list[ReviewItem] = []
    for field in ANALYSIS_FIELDS:
        term = contract_terms.get(field)
        if term is None:
            continue
        if term.verification_status != VerificationStatus.VERIFIED:
            found_specific_signal = False
            if term.verification_status == VerificationStatus.NEEDS_CHECK:
                ambiguous_phrase = _find_phrase(term, AMBIGUOUS_CONTRACT_PHRASES)
                if ambiguous_phrase is not None:
                    reviews.append(
                        _review_for_term(
                            contract_id=contract_id,
                            term=term,
                            signal=ReviewSignalType.UNCLEAR,
                            severity=ReviewSeverity.CHECK,
                            explanation=(
                                f"{REVIEW_FIELD_LABELS[field]} 조건에 "
                                f"'{ambiguous_phrase}' 표현이 있어 적용 기준이 "
                                "명확하지 않습니다."
                            ),
                        )
                    )
                    found_specific_signal = True
                if field in SAFETY_RESPONSIBILITY_FIELDS:
                    one_sided_phrase = _find_phrase(
                        term,
                        ONE_SIDED_RESPONSIBILITY_PHRASES,
                    )
                    if one_sided_phrase is not None:
                        reviews.append(
                            _review_for_term(
                                contract_id=contract_id,
                                term=term,
                                signal=ReviewSignalType.NEEDS_CHECK,
                                severity=ReviewSeverity.IMPORTANT,
                                explanation=(
                                    f"{REVIEW_FIELD_LABELS[field]} 조건에 "
                                    f"'{one_sided_phrase}' 표현이 있어 책임 범위와 "
                                    "주체를 추가로 확인해야 합니다."
                                ),
                            )
                        )
                        found_specific_signal = True
            if not found_specific_signal and not _documented_comparison_terms(
                documented_terms.get(field, ())
            ):
                reviews.append(
                    _review_for_term(
                        contract_id=contract_id,
                        term=term,
                        signal=(
                            ReviewSignalType.MISSING
                            if term.verification_status == VerificationStatus.NOT_FOUND
                            else ReviewSignalType.NEEDS_CHECK
                        ),
                        severity=(
                            ReviewSeverity.IMPORTANT
                            if field in P0_IMPORTANT_MISSING_FIELDS
                            else ReviewSeverity.CHECK
                        ),
                        explanation=_unresolved_explanation(
                            field=field,
                            verification_status=term.verification_status,
                        ),
                    )
                )

    reviews.extend(
        _build_documented_explanation_reviews(
            contract_id=contract_id,
            contract_terms=contract_terms,
            documented_terms=documented_terms,
        )
    )

    representative_terms = tuple(
        contract_terms[field]
        for field in REPRESENTATIVE_OBLIGATION_FIELDS
        if field in contract_terms
    )
    if (
        len(representative_terms) == len(REPRESENTATIVE_OBLIGATION_FIELDS)
        and all(
            term.verification_status == VerificationStatus.VERIFIED for term in representative_terms
        )
        and build_representative_obligation(
            contract_id=contract_id,
            terms=terms,
        )
        is None
    ):
        due = contract_terms[ExtractedField.DELIVERABLE_DUE_DATE]
        ordered_terms = tuple(
            contract_terms[field]
            for field in (
                *REPRESENTATIVE_TITLE_FIELDS,
                ExtractedField.DELIVERABLE_DUE_DATE,
            )
        )
        reviews.append(
            _review_for_term(
                contract_id=contract_id,
                term=due,
                related_terms=ordered_terms,
                signal=ReviewSignalType.NEEDS_CHECK,
                severity=ReviewSeverity.IMPORTANT,
                explanation=(
                    "산출물 제목과 기한이 서로 다른 계약 원문 근거에서 확인되어 "
                    "하나의 대표 이행 항목으로 확정할 수 없습니다. 같은 산출물의 "
                    "조건인지 추가 확인이 필요합니다."
                ),
            )
        )

    for term in contract_terms.values():
        if term.verification_status != VerificationStatus.VERIFIED:
            continue
        ambiguous_phrase = _find_phrase(term, AMBIGUOUS_CONTRACT_PHRASES)
        if ambiguous_phrase is not None:
            reviews.append(
                _review_for_term(
                    contract_id=contract_id,
                    term=term,
                    signal=ReviewSignalType.UNCLEAR,
                    severity=ReviewSeverity.CHECK,
                    explanation=(
                        f"{REVIEW_FIELD_LABELS[term.field]} 조건에 "
                        f"'{ambiguous_phrase}' 표현이 있어 적용 기준이 명확하지 않습니다."
                    ),
                )
            )
        if term.field in SAFETY_RESPONSIBILITY_FIELDS:
            one_sided_phrase = _find_phrase(
                term,
                ONE_SIDED_RESPONSIBILITY_PHRASES,
            )
            if one_sided_phrase is not None:
                reviews.append(
                    _review_for_term(
                        contract_id=contract_id,
                        term=term,
                        signal=ReviewSignalType.NEEDS_CHECK,
                        severity=ReviewSeverity.IMPORTANT,
                        explanation=(
                            f"{REVIEW_FIELD_LABELS[term.field]} 조건에 "
                            f"'{one_sided_phrase}' 표현이 있어 책임 범위와 주체를 "
                            "추가로 확인해야 합니다."
                        ),
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
                        explanation=(f"저장된 {label}과 최신 계약 원문의 {label}이 다릅니다."),
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
                        explanation=(f"사용자가 이해한 {label}과 계약 원문의 {label}이 다릅니다."),
                    )
                )
        refund = contract_terms.get(ExtractedField.REFUND_CONDITION)
        if (
            refund is not None
            and refund.verification_status == VerificationStatus.VERIFIED
            and _normalized_text(understood.refund_text) not in _normalized_text(str(refund.value))
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
        understood_termination = _understood_termination_value(understood.termination_text)
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


def _documented_terms_by_field(
    terms: list[ExtractedTerm],
) -> dict[ExtractedField, tuple[ExtractedTerm, ...]]:
    grouped: dict[ExtractedField, list[ExtractedTerm]] = {}
    for term in terms:
        if term.source_type != ExtractedSourceType.DOCUMENTED_EXPLANATION:
            continue
        grouped.setdefault(term.field, []).append(term)
    return {field: tuple(field_terms) for field, field_terms in grouped.items()}


def _documented_comparison_terms(
    terms: tuple[ExtractedTerm, ...],
) -> tuple[ExtractedTerm, ...]:
    # A supporting document may legitimately omit most contract fields. Only an
    # extracted claim participates in comparison; NOT_FOUND alone is not a claim.
    return tuple(term for term in terms if term.verification_status != VerificationStatus.NOT_FOUND)


def _build_documented_explanation_reviews(
    *,
    contract_id: UUID,
    contract_terms: dict[ExtractedField, ExtractedTerm],
    documented_terms: dict[ExtractedField, tuple[ExtractedTerm, ...]],
) -> list[ReviewItem]:
    reviews: list[ReviewItem] = []
    for field in ANALYSIS_FIELDS:
        contract_term = contract_terms.get(field)
        supporting_terms = _documented_comparison_terms(documented_terms.get(field, ()))
        if contract_term is None or not supporting_terms:
            continue

        related_terms = (contract_term, *supporting_terms)
        label = REVIEW_FIELD_LABELS[field]
        supporting_evidence_is_verified = all(
            term.verification_status == VerificationStatus.VERIFIED for term in supporting_terms
        )
        supporting_values = (
            {_document_comparison_value(term) for term in supporting_terms}
            if supporting_evidence_is_verified
            else set()
        )
        if len(supporting_values) > 1:
            reviews.append(
                _review_for_term(
                    contract_id=contract_id,
                    term=contract_term,
                    related_terms=related_terms,
                    signal=ReviewSignalType.NEEDS_CHECK,
                    severity=ReviewSeverity.IMPORTANT,
                    verification_status=_comparison_review_verification_status(contract_term),
                    explanation=(
                        f"선택 자료마다 문서로 확인된 {label} 설명이 서로 달라 "
                        "계약 문서와의 차이를 확정할 수 없습니다. "
                        "어느 설명이 최종 조건인지 추가 확인이 필요합니다."
                    ),
                    basis_text=(
                        "여러 선택 자료의 설명이 일치할 때만 계약 문서상 조건과 "
                        "확정 비교하는 내부 확인 규칙"
                    ),
                )
            )
            continue

        if (
            contract_term.verification_status == VerificationStatus.NOT_FOUND
            and supporting_evidence_is_verified
        ):
            reviews.append(
                _review_for_term(
                    contract_id=contract_id,
                    term=contract_term,
                    related_terms=related_terms,
                    signal=ReviewSignalType.NO_BASIS,
                    severity=ReviewSeverity.IMPORTANT,
                    verification_status=VerificationStatus.NOT_FOUND,
                    explanation=(
                        f"선택 자료에는 문서로 확인된 {label} 설명이 있지만 "
                        "계약 문서에서 같은 조건의 근거를 찾지 못했습니다. "
                        "해당 설명이 계약 조건에 반영되는지 확인해야 합니다."
                    ),
                    basis_text=(
                        "선택 자료에 검증된 설명이 있고 계약 문서에서는 같은 조건을 "
                        "찾지 못한 경우 계약 반영 여부를 확인하는 내부 규칙"
                    ),
                )
            )
            continue

        comparison_is_verified = (
            contract_term.verification_status == VerificationStatus.VERIFIED
            and supporting_evidence_is_verified
        )
        if not comparison_is_verified:
            reviews.append(
                _review_for_term(
                    contract_id=contract_id,
                    term=contract_term,
                    related_terms=related_terms,
                    signal=ReviewSignalType.NEEDS_CHECK,
                    severity=ReviewSeverity.IMPORTANT,
                    verification_status=_comparison_review_verification_status(contract_term),
                    explanation=(
                        f"계약 문서상 {label} 또는 선택 자료의 문서로 확인된 설명 중 "
                        "원문 근거가 충분히 검증되지 않아 차이를 확정할 수 없습니다. "
                        "양쪽 원문을 추가로 확인해야 합니다."
                    ),
                    basis_text=(
                        "계약 문서상 조건과 선택 자료의 문서로 확인된 설명을 "
                        "검증된 원문 근거끼리 비교하는 내부 확인 규칙"
                    ),
                )
            )
            continue

        supporting_value = next(iter(supporting_values))
        if supporting_value == _document_comparison_value(contract_term):
            continue
        reviews.append(
            _review_for_term(
                contract_id=contract_id,
                term=contract_term,
                related_terms=related_terms,
                signal=ReviewSignalType.MISMATCH,
                severity=ReviewSeverity.IMPORTANT,
                verification_status=VerificationStatus.VERIFIED,
                explanation=(
                    f"선택 자료에서 문서로 확인된 {label} 설명과 계약 문서상 조건이 다릅니다."
                ),
                basis_text=(
                    "검증된 계약 문서상 조건과 선택 자료의 문서로 확인된 설명을 "
                    "날짜·금액·수량·분류·문구별로 결정적으로 비교하는 내부 확인 규칙"
                ),
            )
        )
    return reviews


def _comparison_review_verification_status(
    contract_term: ExtractedTerm,
) -> VerificationStatus:
    if contract_term.source_page is not None and contract_term.source_text is not None:
        return VerificationStatus.NEEDS_CHECK
    return contract_term.verification_status


def _document_comparison_value(term: ExtractedTerm) -> object:
    value = term.value
    if value is None:
        return None
    if term.value_type == ExtractedValueType.DATE:
        return date.fromisoformat(str(value))
    if term.value_type in {
        ExtractedValueType.MONEY_KRW,
        ExtractedValueType.INTEGER,
        ExtractedValueType.PERCENT,
    }:
        return int(value)
    if (
        term.value_type == ExtractedValueType.BOOLEAN
        or term.field == ExtractedField.CONTRACT_RENEWAL_TYPE
    ):
        return str(value).strip().upper()
    return _normalized_text(str(value))


def _term_source_label(term: ExtractedTerm) -> str:
    if term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT:
        return "계약 문서상 조건"
    return "문서로 확인된 설명"


def _canonical_term_value(term: ExtractedTerm) -> object:
    if term.field in {
        ExtractedField.CONTRACT_SIGNED_DATE,
        ExtractedField.CONTRACT_START_DATE,
        ExtractedField.CONTRACT_END_DATE,
        ExtractedField.TERMINATION_NOTICE_DATE,
    }:
        return date.fromisoformat(str(term.value))
    return term.value


def _unresolved_explanation(
    *,
    field: ExtractedField,
    verification_status: VerificationStatus,
) -> str:
    label = REVIEW_FIELD_LABELS[field]
    if verification_status == VerificationStatus.NOT_FOUND:
        if field in DELIVERABLE_FIELDS:
            return (
                f"계약 원문에서 산출물의 {label} 조건을 찾지 못했습니다. "
                "실제 제공 범위를 확인해야 합니다."
            )
        if field in SAFETY_RESPONSIBILITY_FIELDS:
            return (
                f"계약 원문에서 {label} 조건을 찾지 못했습니다. "
                "안전 조치와 책임 주체를 확인해야 합니다."
            )
        return f"계약 원문에서 {label} 조건을 찾지 못했습니다."
    if verification_status == VerificationStatus.MISSING_EVIDENCE:
        return f"{label} 값은 추출됐지만 이를 뒷받침하는 계약 원문 위치를 확인하지 못했습니다."
    return f"계약 원문의 {label} 조건은 사용자 확인이 더 필요합니다."


def _find_phrase(
    term: ExtractedTerm,
    phrases: tuple[str, ...],
) -> str | None:
    values = [term.source_text, str(term.value) if term.value is not None else None]
    normalized = _normalized_text(" ".join(value for value in values if value))
    for phrase in phrases:
        if _normalized_text(phrase) in normalized:
            return phrase
    return None


def _build_solar_review_inputs(
    *,
    reviews: list[ReviewItem],
    terms: list[ExtractedTerm],
    understood: UnderstoodTerm | None,
    contract: ContractRecord | None,
) -> list[SolarReviewInput]:
    terms_by_id = {term.id: term for term in terms}
    inputs: list[SolarReviewInput] = []
    for review in reviews:
        related_terms: list[ExtractedTerm] = []
        for term_id in review.related_extracted_term_ids:
            term = terms_by_id.get(term_id)
            if term is None:
                raise ValueError("검토 항목의 관련 추출 필드를 찾을 수 없습니다.")
            related_terms.append(term)
        labels = list(dict.fromkeys(REVIEW_FIELD_LABELS[term.field] for term in related_terms))
        contract_values = [
            _bounded_context(
                f"{_term_source_label(term)} "
                f"{REVIEW_FIELD_LABELS[term.field]}: "
                f"{term.value if term.value is not None else '계약 원문에서 확인되지 않음'}",
                limit=400,
            )
            for term in related_terms
        ]
        inputs.append(
            SolarReviewInput(
                review_item_id=review.id,
                signal=review.type,
                severity=review.severity,
                verification_status=review.verification_status,
                field_labels=labels,
                deterministic_explanation=_bounded_context(
                    review.plain_explanation,
                    limit=600,
                ),
                contract_values=contract_values,
                user_understanding=_review_comparison_context(
                    review=review,
                    related_terms=related_terms,
                    understood=understood,
                    contract=contract,
                ),
                source_excerpt=(
                    _bounded_context(review.source_text, limit=1200)
                    if review.source_text is not None
                    else None
                ),
            )
        )
    return inputs


def _review_comparison_context(
    *,
    review: ReviewItem,
    related_terms: list[ExtractedTerm],
    understood: UnderstoodTerm | None,
    contract: ContractRecord | None,
) -> str | None:
    fields = {term.field for term in related_terms}
    if understood is not None and "사용자가 이해한" in review.plain_explanation:
        if {
            ExtractedField.CONTRACT_START_DATE,
            ExtractedField.CONTRACT_END_DATE,
        }.issubset(fields):
            return _bounded_context(
                f"사용자가 이해한 계약기간: {understood.duration_text}",
                limit=400,
            )
        understood_values: tuple[tuple[ExtractedField, str, object | None], ...] = (
            (ExtractedField.MONTHLY_AMOUNT, "월 납부액", understood.monthly_amount),
            (
                ExtractedField.CONTRACT_TOTAL_AMOUNT,
                "총 계약금액",
                understood.total_amount,
            ),
            (ExtractedField.REFUND_CONDITION, "환불 조건", understood.refund_text),
            (
                ExtractedField.EARLY_TERMINATION_ALLOWED,
                "중도해지 가능 여부",
                understood.termination_text,
            ),
        )
        for field, label, value in understood_values:
            if field in fields and value is not None:
                return _bounded_context(
                    f"사용자가 이해한 {label}: {value}",
                    limit=400,
                )

    if contract is not None and "저장된" in review.plain_explanation:
        canonical_values: tuple[tuple[ExtractedField, str, object | None], ...] = (
            (ExtractedField.CONTRACT_SIGNED_DATE, "계약 체결일", contract.signed_date),
            (ExtractedField.CONTRACT_START_DATE, "계약 시작일", contract.start_date),
            (ExtractedField.CONTRACT_END_DATE, "계약 종료일", contract.end_date),
            (
                ExtractedField.TERMINATION_NOTICE_DATE,
                "해지 통보기한",
                contract.termination_notice_date,
            ),
            (
                ExtractedField.CONTRACT_RENEWAL_TYPE,
                "갱신 유형",
                contract.renewal_type,
            ),
            (
                ExtractedField.CONTRACT_TOTAL_AMOUNT,
                "총 계약금액",
                contract.total_amount,
            ),
        )
        for field, label, value in canonical_values:
            if field in fields and value is not None:
                return _bounded_context(f"저장된 {label}: {value}", limit=400)
    return None


def _apply_solar_review_content(
    *,
    reviews: list[ReviewItem],
    outputs: list[SolarReviewOutput],
) -> list[ReviewItem]:
    outputs_by_id = {output.review_item_id: output for output in outputs}
    if len(outputs_by_id) != len(outputs):
        raise ValueError("Solar 검토 출력 ID는 중복될 수 없습니다.")
    if set(outputs_by_id) != {review.id for review in reviews}:
        raise ValueError("Solar 검토 출력 ID가 검토 후보와 일치하지 않습니다.")

    merged: list[ReviewItem] = []
    for review in reviews:
        output = outputs_by_id[review.id]
        limitations = output.model_limitations.strip()
        if SOLAR_CONFIDENCE_LIMITATION not in limitations:
            limitations = f"{limitations} {SOLAR_CONFIDENCE_LIMITATION}"
        payload = review.model_dump(mode="python")
        payload.update(
            {
                "detection_method": DetectionMethod.HYBRID,
                "model_confidence": output.self_reported_confidence,
                "model_limitations": limitations,
                "plain_explanation": output.plain_explanation.strip(),
                "suggestion_accept": output.suggestion_accept.strip(),
                "suggestion_compromise": output.suggestion_compromise.strip(),
                "suggestion_request": output.suggestion_request.strip(),
            }
        )
        merged.append(ReviewItem.model_validate(payload))
    return merged


def _bounded_context(value: str, *, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def _review_for_term(
    *,
    contract_id: UUID,
    term: ExtractedTerm,
    related_terms: tuple[ExtractedTerm, ...] | None = None,
    signal: ReviewSignalType,
    severity: ReviewSeverity,
    explanation: str,
    verification_status: VerificationStatus | None = None,
    basis_text: str = ("계약 원문과 사용자가 저장한 이해조건을 분리해 비교하는 내부 확인 규칙"),
) -> ReviewItem:
    has_evidence = term.source_page is not None and term.source_text is not None
    review_verification_status = verification_status or term.verification_status
    related = related_terms or (term,)
    labels = list(dict.fromkeys(REVIEW_FIELD_LABELS[item.field] for item in related))
    label = "·".join(labels)
    if signal == ReviewSignalType.MISSING:
        suggestion_accept = f"현재 계약서에 {label} 조건이 없는 상태를 그대로 수용합니다."
    else:
        suggestion_accept = f"현재 계약 원문에 적힌 {label} 조건을 그대로 수용합니다."
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
        basis_text=basis_text,
        basis_citation=None,
        related_extracted_term_ids=[related_term.id for related_term in related],
        source_document_id=term.document_id if has_evidence else None,
        source_page=term.source_page if has_evidence else None,
        source_text=term.source_text if has_evidence else None,
        source_confidence=term.confidence if has_evidence else None,
        verification_status=review_verification_status,
        suggestion_accept=suggestion_accept,
        suggestion_compromise=(f"{label} 조건의 차이와 확인할 범위를 상대방과 협의해 조정합니다."),
        suggestion_request=(
            f"{label} 조건의 주체·기준·시점을 계약 문구에 명확히 적어 달라고 요청합니다."
        ),
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
