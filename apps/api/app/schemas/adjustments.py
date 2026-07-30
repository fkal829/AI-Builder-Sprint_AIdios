from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.enums import AdjustmentRequestStatus, SuggestionChoice


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
    decision: str
    counter_text: str | None = None
    reason: str | None = None


class CounterproposalComparison(BaseModel):
    review_item_id: UUID
    changed_summary: str
    remaining_checks: list[str]
    final_confirmation: str


class OwnerAdjustmentDetail(BaseModel):
    request: AdjustmentRequest
    responses: list[AdjustmentResponseItem]
    comparisons: list[CounterproposalComparison]
