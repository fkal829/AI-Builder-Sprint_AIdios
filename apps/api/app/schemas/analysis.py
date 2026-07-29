from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.enums import (
    DetectionMethod,
    ExtractedField,
    ExtractedValueType,
    ReviewSeverity,
    ReviewSignalType,
    SuggestionChoice,
    VerificationStatus,
)

EXPECTED_VALUE_TYPES: dict[ExtractedField, ExtractedValueType] = {
    ExtractedField.CONTRACT_START_DATE: ExtractedValueType.DATE,
    ExtractedField.CONTRACT_END_DATE: ExtractedValueType.DATE,
    ExtractedField.TERMINATION_NOTICE_DATE: ExtractedValueType.DATE,
    ExtractedField.MONTHLY_AMOUNT: ExtractedValueType.MONEY_KRW,
    ExtractedField.CONTRACT_TOTAL_AMOUNT: ExtractedValueType.MONEY_KRW,
    ExtractedField.CONTENT_QUANTITY: ExtractedValueType.INTEGER,
    ExtractedField.TERMINATION_PENALTY_RATE: ExtractedValueType.PERCENT,
    ExtractedField.AUTO_RENEWAL: ExtractedValueType.BOOLEAN,
    ExtractedField.EARLY_TERMINATION_ALLOWED: ExtractedValueType.BOOLEAN,
    ExtractedField.PERFORMANCE_GUARANTEE: ExtractedValueType.BOOLEAN,
}


class ExtractedTerm(BaseModel):
    field: ExtractedField
    value_type: ExtractedValueType
    value: Any
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = Field(default=None, min_length=1)
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus

    @model_validator(mode="after")
    def validate_evidence(self) -> "ExtractedTerm":
        has_page = self.source_page is not None
        has_text = self.source_text is not None
        if has_page != has_text:
            raise ValueError("source_page와 source_text는 함께 제공해야 합니다.")
        if self.verification_status == VerificationStatus.VERIFIED and not has_page:
            raise ValueError("VERIFIED 결과에는 원문 근거가 필요합니다.")
        if self.verification_status == VerificationStatus.NOT_FOUND and has_page:
            raise ValueError("NOT_FOUND 결과에는 원문 근거를 넣을 수 없습니다.")
        if self.verification_status == VerificationStatus.NOT_FOUND and self.value is not None:
            raise ValueError("NOT_FOUND 결과의 value는 null이어야 합니다.")
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
        if self.value_type == ExtractedValueType.MONEY_KRW and self.value < 0:
            raise ValueError("원화 금액은 0 이상이어야 합니다.")
        if self.value_type == ExtractedValueType.INTEGER and self.value < 0:
            raise ValueError("정수 값은 0 이상이어야 합니다.")
        if self.value_type == ExtractedValueType.PERCENT and not 0 <= self.value <= 100:
            raise ValueError("비율은 0부터 100 사이여야 합니다.")
        if self.value_type == ExtractedValueType.BOOLEAN and self.value not in {
            "YES",
            "NO",
            "UNKNOWN",
        }:
            raise ValueError("BOOLEAN 값은 YES, NO, UNKNOWN 중 하나여야 합니다.")
        if self.value_type == ExtractedValueType.TEXT and not isinstance(self.value, str):
            raise ValueError("TEXT 값은 문자열이어야 합니다.")


class ReviewItem(BaseModel):
    type: ReviewSignalType
    severity: ReviewSeverity
    plain_explanation: str = Field(min_length=1)
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = Field(default=None, min_length=1)
    detection_method: DetectionMethod
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    verification_status: VerificationStatus
    suggestion_accept: str = Field(min_length=1)
    suggestion_compromise: str = Field(min_length=1)
    suggestion_request: str = Field(min_length=1)
    user_choice: SuggestionChoice | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "ReviewItem":
        has_page = self.source_page is not None
        has_text = self.source_text is not None
        if has_page != has_text:
            raise ValueError("source_page와 source_text는 함께 제공해야 합니다.")
        if self.verification_status == VerificationStatus.VERIFIED and not has_page:
            raise ValueError("VERIFIED 검토 항목에는 원문 근거가 필요합니다.")
        if self.verification_status == VerificationStatus.NOT_FOUND and has_page:
            raise ValueError(
                "NOT_FOUND 검토 항목에는 원문 근거를 넣을 수 없습니다."
            )
        if (
            self.detection_method in {DetectionMethod.MODEL, DetectionMethod.HYBRID}
            and self.model_confidence is None
        ):
            raise ValueError(
                "모델 기반 검토 항목에는 model_confidence가 필요합니다."
            )
        if (
            self.detection_method == DetectionMethod.DETERMINISTIC
            and self.model_confidence is not None
        ):
            raise ValueError(
                "규칙 기반 검토 항목에는 model_confidence를 넣지 않습니다."
            )
        return self
