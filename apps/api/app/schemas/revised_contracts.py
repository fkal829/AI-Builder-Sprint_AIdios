from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RevisedContractReviewStatus(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFIRMED = "CONFIRMED"


class RevisedContractMatchStatus(StrEnum):
    MATCHED = "MATCHED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"


class RevisedContractReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjustment_request_id: UUID
    document_id: UUID


class RevisedContractReviewConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_review_item_ids: list[UUID] = Field(min_length=1, max_length=4)
    confirmed: Literal[True]


class RevisedContractReviewItem(BaseModel):
    review_item_id: UUID
    expected_text: str = Field(min_length=1)
    match_status: RevisedContractMatchStatus
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    owner_confirmed: bool = False


class RevisedContractReview(BaseModel):
    id: UUID
    contract_id: UUID
    adjustment_request_id: UUID
    document_id: UUID
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: RevisedContractReviewStatus
    items: list[RevisedContractReviewItem] = Field(min_length=1, max_length=4)
    created_at: datetime
    confirmed_at: datetime | None = None
