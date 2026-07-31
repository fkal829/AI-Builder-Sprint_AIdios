from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    AdjustmentRequestStatus,
    AdjustmentResponseDecision,
    SuggestionChoice,
)
from app.core.text_safety import contains_unsafe_legal_conclusion


class AdjustmentRequestCreate(BaseModel):
    review_item_ids: list[UUID] = Field(min_length=1, max_length=4)
    expires_in_hours: int = Field(ge=1, le=168)

    @model_validator(mode="after")
    def review_items_are_unique(self) -> "AdjustmentRequestCreate":
        if len(set(self.review_item_ids)) != len(self.review_item_ids):
            raise ValueError("review_item_ids는 중복될 수 없습니다.")
        return self


class AdjustmentRequestItem(BaseModel):
    review_item_id: UUID
    user_choice: Literal[SuggestionChoice.COMPROMISE, SuggestionChoice.REQUEST]
    request_text: str = Field(min_length=1)


class AdjustmentRequest(BaseModel):
    id: UUID
    contract_id: UUID
    status: AdjustmentRequestStatus
    items: list[AdjustmentRequestItem] = Field(min_length=1, max_length=4)
    expires_in_hours: int = Field(ge=1, le=168)
    sent_at: datetime | None = None
    expires_at: datetime | None = None
    opened_at: datetime | None = None
    responded_at: datetime | None = None


class ExplicitConfirmation(BaseModel):
    confirmed: Literal[True]


class AdjustmentRequestSent(BaseModel):
    id: UUID
    status: Literal[AdjustmentRequestStatus.SENT]
    public_url: str
    expires_at: datetime


class AdjustmentResponseItem(BaseModel):
    review_item_id: UUID
    decision: AdjustmentResponseDecision
    counter_text: str | None = None
    reason: str | None = None


class PublicAdjustmentItem(BaseModel):
    item_id: str = Field(min_length=1)
    request_text: str = Field(min_length=1)


class PublicAdjustment(BaseModel):
    contract_title: str = Field(min_length=1)
    status: Literal[
        AdjustmentRequestStatus.SENT,
        AdjustmentRequestStatus.OPENED,
        AdjustmentRequestStatus.RESPONDED,
        AdjustmentRequestStatus.CONFIRMED,
    ]
    expires_at: datetime
    items: list[PublicAdjustmentItem] = Field(min_length=1, max_length=4)


class PublicAdjustmentOpen(BaseModel):
    status: Literal[AdjustmentRequestStatus.OPENED]
    opened_at: datetime


class AdjustmentResponseSubmitItem(BaseModel):
    item_id: str = Field(min_length=1)
    decision: AdjustmentResponseDecision
    counter_text: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def requires_decision_specific_fields(self) -> "AdjustmentResponseSubmitItem":
        if self.decision == AdjustmentResponseDecision.ACCEPT:
            if self.counter_text is not None or self.reason is not None:
                raise ValueError("ACCEPT 응답에는 추가 문구나 사유를 넣을 수 없습니다.")
        elif self.decision == AdjustmentResponseDecision.REJECT:
            if self.counter_text is not None or not _has_text(self.reason):
                raise ValueError("REJECT 응답에는 비어 있지 않은 사유가 필요합니다.")
        elif not _has_text(self.counter_text) or not _has_text(self.reason):
            raise ValueError("COUNTER 응답에는 역제안 문구와 사유가 필요합니다.")
        return self


class AdjustmentResponsesSubmit(BaseModel):
    responses: list[AdjustmentResponseSubmitItem] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def item_ids_are_unique(self) -> "AdjustmentResponsesSubmit":
        item_ids = [response.item_id for response in self.responses]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("응답 item_id는 중복될 수 없습니다.")
        return self


class PublicSubmission(BaseModel):
    submitted: Literal[True]


class StrictAdjustmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CounterproposalComparisonInput(StrictAdjustmentModel):
    review_item_id: UUID
    request_text: str = Field(min_length=1)
    counter_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_non_blank_text(self) -> "CounterproposalComparisonInput":
        if any(not value.strip() for value in (self.request_text, self.counter_text, self.reason)):
            raise ValueError("역제안 비교 입력 문자열은 비어 있을 수 없습니다.")
        return self


class CounterproposalComparisonBatchInput(StrictAdjustmentModel):
    items: list[CounterproposalComparisonInput] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "CounterproposalComparisonBatchInput":
        item_ids = [item.review_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("역제안 비교 입력 ID는 중복될 수 없습니다.")
        return self


class GeneratedCounterproposalComparison(StrictAdjustmentModel):
    review_item_id: UUID
    changed_summary: str = Field(min_length=1, max_length=1200)
    remaining_checks: list[str] = Field(min_length=1, max_length=6)
    final_confirmation: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def validate_safe_copy(self) -> "GeneratedCounterproposalComparison":
        text_values = (
            self.changed_summary,
            *self.remaining_checks,
            self.final_confirmation,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("역제안 비교 출력 문자열은 비어 있을 수 없습니다.")
        if contains_unsafe_legal_conclusion(text_values):
            raise ValueError("역제안 비교 출력에 허용되지 않은 단정 표현이 있습니다.")
        return self


class CounterproposalComparisonBatchOutput(StrictAdjustmentModel):
    items: list[GeneratedCounterproposalComparison] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "CounterproposalComparisonBatchOutput":
        item_ids = [item.review_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("역제안 비교 출력 ID는 중복될 수 없습니다.")
        return self


class CounterproposalComparison(BaseModel):
    review_item_id: UUID
    changed_summary: str = Field(min_length=1, max_length=1200)
    remaining_checks: list[str] = Field(max_length=6)
    final_confirmation: str = Field(min_length=1, max_length=600)


class OwnerAdjustmentDetail(BaseModel):
    request: AdjustmentRequest
    responses: list[AdjustmentResponseItem]
    comparisons: list[CounterproposalComparison]


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())
