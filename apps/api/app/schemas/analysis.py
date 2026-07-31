from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    AnalysisStatus,
    DetectionMethod,
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
    ReviewBasisType,
    ReviewItemStatus,
    ReviewSeverity,
    ReviewSignalType,
    SuggestionChoice,
    VerificationStatus,
)
from app.core.errors import ErrorCode
from app.core.text_safety import contains_unsafe_legal_conclusion

EXPECTED_VALUE_TYPES: dict[ExtractedField, ExtractedValueType] = {
    ExtractedField.CONTRACT_SIGNED_DATE: ExtractedValueType.DATE,
    ExtractedField.CONTRACT_START_DATE: ExtractedValueType.DATE,
    ExtractedField.CONTRACT_END_DATE: ExtractedValueType.DATE,
    ExtractedField.TERMINATION_NOTICE_DATE: ExtractedValueType.DATE,
    ExtractedField.DELIVERABLE_DUE_DATE: ExtractedValueType.DATE,
    ExtractedField.MONTHLY_AMOUNT: ExtractedValueType.MONEY_KRW,
    ExtractedField.CONTRACT_TOTAL_AMOUNT: ExtractedValueType.MONEY_KRW,
    ExtractedField.CONTENT_QUANTITY: ExtractedValueType.INTEGER,
    ExtractedField.TERMINATION_PENALTY_RATE: ExtractedValueType.PERCENT,
    ExtractedField.AUTO_RENEWAL: ExtractedValueType.BOOLEAN,
    ExtractedField.EARLY_TERMINATION_ALLOWED: ExtractedValueType.BOOLEAN,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedTermCandidate(StrictModel):
    field: ExtractedField
    value_type: ExtractedValueType
    value: Any
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = Field(default=None, min_length=1)
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus

    @model_validator(mode="after")
    def validate_candidate(self) -> "ExtractedTermCandidate":
        has_page = self.source_page is not None
        has_text = self.source_text is not None
        if has_page != has_text:
            raise ValueError("source_page와 source_text는 함께 제공해야 합니다.")

        if self.verification_status == VerificationStatus.VERIFIED:
            if self.value is None or not has_page:
                raise ValueError("VERIFIED 결과에는 값과 원문 근거가 필요합니다.")
        elif self.verification_status == VerificationStatus.NOT_FOUND:
            if self.value is not None or has_page:
                raise ValueError("NOT_FOUND 결과에는 값과 원문 근거를 넣을 수 없습니다.")
        elif self.verification_status == VerificationStatus.MISSING_EVIDENCE:
            if self.value is None or has_page:
                raise ValueError("MISSING_EVIDENCE 결과에는 근거 없는 값만 허용됩니다.")
        elif self.verification_status == VerificationStatus.NEEDS_CHECK and not has_page:
            raise ValueError("NEEDS_CHECK 결과에는 확인할 원문 근거가 필요합니다.")

        self._validate_value_type()
        return self

    def _validate_value_type(self) -> None:
        expected_type = EXPECTED_VALUE_TYPES.get(self.field, ExtractedValueType.TEXT)
        if self.value_type != expected_type:
            raise ValueError(f"{self.field}의 value_type은 {expected_type}이어야 합니다.")
        if self.value is None:
            return
        if self.value_type == ExtractedValueType.DATE:
            if not isinstance(self.value, str):
                raise ValueError("DATE 값은 ISO date 문자열이어야 합니다.")
            try:
                date.fromisoformat(self.value)
            except ValueError as error:
                raise ValueError("DATE 값은 ISO date 형식이어야 합니다.") from error
        if self.value_type in {
            ExtractedValueType.MONEY_KRW,
            ExtractedValueType.INTEGER,
            ExtractedValueType.PERCENT,
        } and (not isinstance(self.value, int) or isinstance(self.value, bool)):
            raise ValueError(f"{self.value_type} 값은 정수여야 합니다.")
        if (
            self.value_type
            in {
                ExtractedValueType.MONEY_KRW,
                ExtractedValueType.INTEGER,
            }
            and self.value < 0
        ):
            raise ValueError("금액과 정수 값은 0 이상이어야 합니다.")
        if self.value_type == ExtractedValueType.PERCENT and not 0 <= self.value <= 100:
            raise ValueError("비율은 0부터 100 사이여야 합니다.")
        if self.value_type == ExtractedValueType.BOOLEAN and self.value not in {
            "YES",
            "NO",
            "UNKNOWN",
        }:
            raise ValueError("BOOLEAN 값은 YES, NO, UNKNOWN 중 하나여야 합니다.")
        if self.value_type == ExtractedValueType.TEXT:
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError("TEXT 값은 비어 있지 않은 문자열이어야 합니다.")
            if self.field == ExtractedField.CONTRACT_RENEWAL_TYPE and self.value not in {
                "AUTO",
                "MANUAL",
                "NONE",
                "UNKNOWN",
            }:
                raise ValueError(
                    "contract_renewal_type은 AUTO, MANUAL, NONE, UNKNOWN 중 하나여야 합니다."
                )
        if (
            self.field
            in {
                ExtractedField.AUTO_RENEWAL,
                ExtractedField.EARLY_TERMINATION_ALLOWED,
                ExtractedField.CONTRACT_RENEWAL_TYPE,
            }
            and self.value == "UNKNOWN"
            and self.verification_status != VerificationStatus.NEEDS_CHECK
        ):
            raise ValueError("UNKNOWN 값은 NEEDS_CHECK로 표시해야 합니다.")


class ExtractedTerm(ExtractedTermCandidate):
    id: UUID
    contract_id: UUID
    document_id: UUID
    source_type: ExtractedSourceType


class ReviewBasisCitation(StrictModel):
    organization: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    url: str | None = Field(default=None, pattern=r"^https?://")
    version: str | None = Field(default=None, min_length=1)
    effective_date: date | None = None


class ReviewItem(StrictModel):
    id: UUID
    contract_id: UUID
    type: ReviewSignalType
    severity: ReviewSeverity
    detection_method: DetectionMethod
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    model_limitations: str | None = Field(default=None, min_length=1)
    plain_explanation: str = Field(min_length=1)
    basis_type: ReviewBasisType
    basis_text: str = Field(min_length=1)
    basis_citation: ReviewBasisCitation | None
    related_extracted_term_ids: list[UUID] = Field(min_length=1, max_length=11)
    source_document_id: UUID | None
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = Field(default=None, min_length=1)
    source_confidence: float | None = Field(default=None, ge=0, le=1)
    verification_status: VerificationStatus
    suggestion_accept: str = Field(min_length=1)
    suggestion_compromise: str = Field(min_length=1)
    suggestion_request: str = Field(min_length=1)
    user_choice: SuggestionChoice | None = None
    status: ReviewItemStatus = ReviewItemStatus.UNREVIEWED

    @model_validator(mode="after")
    def validate_review_item(self) -> "ReviewItem":
        if len(set(self.related_extracted_term_ids)) != len(self.related_extracted_term_ids):
            raise ValueError("related_extracted_term_ids는 중복될 수 없습니다.")

        evidence_values = (
            self.source_document_id,
            self.source_page,
            self.source_text,
            self.source_confidence,
        )
        has_evidence = all(value is not None for value in evidence_values)
        if any(value is not None for value in evidence_values) != has_evidence:
            raise ValueError("검토 항목의 원문 근거 필드는 함께 제공해야 합니다.")
        if (
            self.verification_status
            in {VerificationStatus.VERIFIED, VerificationStatus.NEEDS_CHECK}
            and not has_evidence
        ):
            raise ValueError("VERIFIED 또는 NEEDS_CHECK 검토 항목에는 원문 근거가 필요합니다.")
        if (
            self.verification_status
            in {VerificationStatus.NOT_FOUND, VerificationStatus.MISSING_EVIDENCE}
            and has_evidence
        ):
            raise ValueError("근거가 없는 검토 상태에는 원문 근거를 넣을 수 없습니다.")

        if self.detection_method in {DetectionMethod.MODEL, DetectionMethod.HYBRID}:
            if self.model_confidence is None or self.model_limitations is None:
                raise ValueError("모델 기반 검토 항목에는 모델 확신도와 한계가 필요합니다.")
        elif self.model_confidence is not None or self.model_limitations is not None:
            raise ValueError("결정 규칙 기반 검토 항목에는 모델 확신도와 한계를 넣지 않습니다.")

        if self.basis_type == ReviewBasisType.OFFICIAL_SOURCE:
            if self.basis_citation is None:
                raise ValueError("공식 기준에는 출처가 필요합니다.")
        elif self.basis_citation is not None:
            raise ValueError("내부 확인 규칙에는 공식 출처를 넣지 않습니다.")

        if self.status == ReviewItemStatus.UNREVIEWED:
            if self.user_choice is not None:
                raise ValueError("미검토 항목에는 사용자 선택을 넣을 수 없습니다.")
        elif self.user_choice is None:
            raise ValueError("검토 상태가 변경된 항목에는 사용자 선택이 필요합니다.")
        if (
            self.status
            in {
                ReviewItemStatus.SELECTED,
                ReviewItemStatus.SENT,
                ReviewItemStatus.KEPT_ORIGINAL,
            }
            and self.user_choice == SuggestionChoice.ACCEPT
        ):
            raise ValueError("조정 대상으로 선택한 항목에는 ACCEPT를 사용할 수 없습니다.")
        return self


class SolarReviewInput(StrictModel):
    review_item_id: UUID
    signal: ReviewSignalType
    severity: ReviewSeverity
    verification_status: VerificationStatus
    field_labels: list[str] = Field(min_length=1, max_length=11)
    deterministic_explanation: str = Field(min_length=1, max_length=600)
    contract_values: list[str] = Field(max_length=11)
    user_understanding: str | None = Field(default=None, min_length=1, max_length=400)
    source_excerpt: str | None = Field(default=None, min_length=1, max_length=1200)

    @model_validator(mode="after")
    def validate_text(self) -> "SolarReviewInput":
        values = [
            *self.field_labels,
            self.deterministic_explanation,
            *self.contract_values,
        ]
        if self.user_understanding is not None:
            values.append(self.user_understanding)
        if self.source_excerpt is not None:
            values.append(self.source_excerpt)
        if any(not value.strip() for value in values):
            raise ValueError("Solar 검토 입력 문자열은 비어 있을 수 없습니다.")
        return self


class SolarReviewBatchInput(StrictModel):
    items: list[SolarReviewInput] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "SolarReviewBatchInput":
        item_ids = [item.review_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Solar 검토 입력 ID는 중복될 수 없습니다.")
        return self


class SolarReviewOutput(StrictModel):
    review_item_id: UUID
    plain_explanation: str = Field(min_length=1, max_length=600)
    suggestion_accept: str = Field(min_length=1, max_length=600)
    suggestion_compromise: str = Field(min_length=1, max_length=600)
    suggestion_request: str = Field(min_length=1, max_length=600)
    self_reported_confidence: float = Field(strict=True, ge=0, le=1)
    model_limitations: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def validate_safe_distinct_copy(self) -> "SolarReviewOutput":
        text_values = (
            self.plain_explanation,
            self.suggestion_accept,
            self.suggestion_compromise,
            self.suggestion_request,
            self.model_limitations,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("Solar 검토 출력 문자열은 비어 있을 수 없습니다.")
        suggestions = {
            self.suggestion_accept.strip(),
            self.suggestion_compromise.strip(),
            self.suggestion_request.strip(),
        }
        if len(suggestions) != 3:
            raise ValueError("Solar의 원안·절충·요청 문구는 서로 달라야 합니다.")
        if contains_unsafe_legal_conclusion(text_values):
            raise ValueError("Solar 검토 출력에 허용되지 않은 단정 표현이 있습니다.")
        return self


class SolarReviewBatchOutput(StrictModel):
    items: list[SolarReviewOutput] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "SolarReviewBatchOutput":
        item_ids = [item.review_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Solar 검토 출력 ID는 중복될 수 없습니다.")
        return self


class Analysis(StrictModel):
    contract_id: UUID
    extracted_terms: list[ExtractedTerm]
    review_items: list[ReviewItem]

    @model_validator(mode="after")
    def validate_evidence_links(self) -> "Analysis":
        term_ids = [term.id for term in self.extracted_terms]
        if len(term_ids) != len(set(term_ids)):
            raise ValueError("분석 결과의 추출값 ID는 중복될 수 없습니다.")

        review_ids = [item.id for item in self.review_items]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("분석 결과의 검토 항목 ID는 중복될 수 없습니다.")

        terms_by_id = {term.id: term for term in self.extracted_terms}
        if any(term.contract_id != self.contract_id for term in self.extracted_terms):
            raise ValueError("모든 추출값은 분석 결과와 같은 계약에 속해야 합니다.")

        for item in self.review_items:
            if item.contract_id != self.contract_id:
                raise ValueError("모든 검토 항목은 분석 결과와 같은 계약에 속해야 합니다.")
            try:
                related_terms = [
                    terms_by_id[term_id] for term_id in item.related_extracted_term_ids
                ]
            except KeyError as error:
                raise ValueError(
                    "검토 항목의 관련 근거는 같은 분석 결과의 추출값이어야 합니다."
                ) from error

            if item.source_document_id is None:
                continue
            if not any(
                term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT
                and term.document_id == item.source_document_id
                and term.source_page == item.source_page
                and term.source_text == item.source_text
                and term.confidence == item.source_confidence
                for term in related_terms
            ):
                raise ValueError("검토 항목의 원문 근거는 연결된 계약 추출값과 일치해야 합니다.")
        return self


class ReviewItemUpdate(StrictModel):
    user_choice: SuggestionChoice


class AnalysisStartRequest(StrictModel):
    document_id: UUID
    supporting_document_ids: list[UUID] = Field(max_length=10)

    @model_validator(mode="after")
    def validate_supporting_documents(self) -> "AnalysisStartRequest":
        if len(set(self.supporting_document_ids)) != len(self.supporting_document_ids):
            raise ValueError("supporting_document_ids는 중복될 수 없습니다.")
        if self.document_id in self.supporting_document_ids:
            raise ValueError("주 계약 문서는 선택 자료에 포함할 수 없습니다.")
        return self


class AnalysisTask(StrictModel):
    id: UUID
    contract_id: UUID
    document_id: UUID
    supporting_document_ids: list[UUID] = Field(max_length=10)
    status: AnalysisStatus
    attempt_count: int = Field(ge=0, le=2)
    error_code: ErrorCode | None
    result: Analysis | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_status_payload(self) -> "AnalysisTask":
        if len(set(self.supporting_document_ids)) != len(self.supporting_document_ids):
            raise ValueError("supporting_document_ids는 중복될 수 없습니다.")
        if self.document_id in self.supporting_document_ids:
            raise ValueError("주 계약 문서는 선택 자료에 포함할 수 없습니다.")
        if self.status == AnalysisStatus.QUEUED:
            if self.attempt_count != 0 or self.error_code is not None or self.result is not None:
                raise ValueError("QUEUED 작업은 시도 전 상태여야 합니다.")
        elif self.status == AnalysisStatus.PROCESSING:
            if not 1 <= self.attempt_count <= 2:
                raise ValueError("PROCESSING 작업의 시도 횟수는 1~2여야 합니다.")
            if self.error_code is not None or self.result is not None:
                raise ValueError("PROCESSING 작업에는 결과와 오류를 넣을 수 없습니다.")
        elif self.status == AnalysisStatus.COMPLETED:
            if not 1 <= self.attempt_count <= 2:
                raise ValueError("COMPLETED 작업의 시도 횟수는 1~2여야 합니다.")
            if self.error_code is not None or self.result is None:
                raise ValueError("완료된 분석 작업에는 결과만 필요합니다.")
            if self.result.contract_id != self.contract_id:
                raise ValueError("분석 결과는 작업과 같은 계약에 속해야 합니다.")
            for term in self.result.extracted_terms:
                if (
                    term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT
                    and term.document_id != self.document_id
                ):
                    raise ValueError("계약 원문 추출값은 분석 작업의 주 문서에 속해야 합니다.")
                if (
                    term.source_type == ExtractedSourceType.DOCUMENTED_EXPLANATION
                    and term.document_id not in self.supporting_document_ids
                ):
                    raise ValueError("선택 자료 추출값은 분석 작업의 선택 문서에 속해야 합니다.")
        elif self.status == AnalysisStatus.FAILED:
            allowed_errors = {
                ErrorCode.DOCUMENT_PARSE_FAILED,
                ErrorCode.ANALYSIS_SCHEMA_INVALID,
            }
            if not 1 <= self.attempt_count <= 2:
                raise ValueError("FAILED 작업의 시도 횟수는 1~2여야 합니다.")
            if self.result is not None or self.error_code not in allowed_errors:
                raise ValueError("실패한 분석 작업에는 허용된 분석 오류만 필요합니다.")
        return self
