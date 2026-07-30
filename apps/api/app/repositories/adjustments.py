from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.core.enums import (
    AdjustmentRequestStatus,
    AdjustmentResolution,
    AdjustmentResponseDecision,
    AgreementClauseCategory,
    ReviewItemStatus,
    SuggestionChoice,
)
from app.repositories.public_tokens import PublicTokenRecord


@dataclass(frozen=True)
class ReviewItemForAdjustment:
    id: UUID
    contract_id: UUID
    status: ReviewItemStatus
    user_choice: SuggestionChoice | None
    suggestion_compromise: str
    suggestion_request: str
    category: AgreementClauseCategory = AgreementClauseCategory.OTHER
    original_text: str = "원계약에서 확인되지 않아 추가 확인 필요"


@dataclass(frozen=True)
class AdjustmentRequestItemRecord:
    review_item_id: UUID
    user_choice: SuggestionChoice
    request_text: str
    category: AgreementClauseCategory = AgreementClauseCategory.OTHER
    before_text: str = "원계약에서 확인되지 않아 추가 확인 필요"


@dataclass(frozen=True)
class AdjustmentRequestRecord:
    id: UUID
    contract_id: UUID
    status: AdjustmentRequestStatus
    items: tuple[AdjustmentRequestItemRecord, ...]
    expires_in_hours: int
    sent_at: datetime | None
    expires_at: datetime | None
    opened_at: datetime | None
    responded_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AdjustmentResponseRecord:
    review_item_id: UUID
    decision: AdjustmentResponseDecision
    counter_text: str | None
    reason: str | None


@dataclass(frozen=True)
class FinalClauseRecord:
    review_item_id: UUID
    category: AgreementClauseCategory
    resolution: AdjustmentResolution
    outcome: str
    disposition: str
    before_text: str
    after_text: str
    reason: str | None


@dataclass(frozen=True)
class AdjustmentDetailRecord:
    request: AdjustmentRequestRecord
    responses: tuple[AdjustmentResponseRecord, ...]


@dataclass(frozen=True)
class PublicAdjustmentRecord:
    contract_title: str
    request: AdjustmentRequestRecord


class AdjustmentRepository(Protocol):
    async def list_review_items_for_adjustment(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        review_item_ids: list[UUID],
    ) -> list[ReviewItemForAdjustment] | None: ...

    async def create_adjustment_draft_with_audit(
        self,
        *,
        owner_id: UUID,
        record: AdjustmentRequestRecord,
    ) -> AdjustmentRequestRecord | None: ...

    async def get_owned_adjustment_request(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
    ) -> AdjustmentRequestRecord | None: ...

    async def get_owned_adjustment_detail(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
    ) -> AdjustmentDetailRecord | None: ...

    async def get_public_adjustment_request(
        self,
        *,
        adjustment_request_id: UUID,
    ) -> PublicAdjustmentRecord | None: ...

    async def open_public_adjustment_request(
        self,
        *,
        adjustment_request_id: UUID,
        opened_at: datetime,
    ) -> AdjustmentRequestRecord | None: ...

    async def submit_public_adjustment_responses(
        self,
        *,
        adjustment_request_id: UUID,
        responses: tuple[AdjustmentResponseRecord, ...],
        responded_at: datetime,
    ) -> AdjustmentRequestRecord | None: ...

    async def confirm_adjustment_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
        resolutions: tuple[tuple[UUID, AdjustmentResolution], ...],
        confirmed_at: datetime,
    ) -> AdjustmentRequestRecord | None: ...

    async def send_adjustment_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
        sent_at: datetime,
        public_token: PublicTokenRecord,
    ) -> AdjustmentRequestRecord | None: ...
