from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.enums import (
    ReviewSeverity,
    ReviewSignalType,
    SuggestionChoice,
    VerificationStatus,
)


class ExtractedTerm(BaseModel):
    field: str = Field(min_length=1)
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
        return self


class ReviewItem(BaseModel):
    type: ReviewSignalType
    severity: ReviewSeverity
    plain_explanation: str = Field(min_length=1)
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = Field(default=None, min_length=1)
    confidence: float = Field(ge=0, le=1)
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
            raise ValueError("NOT_FOUND 검토 항목에는 원문 근거를 넣을 수 없습니다.")
        return self
