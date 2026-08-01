from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    AuditActorType,
    AuditEventType,
    ContractStatus,
    RenewalDecisionType,
)
from app.schemas.understood_terms import UnderstoodTerm


class ContractCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    counterparty_name: str = Field(min_length=1, max_length=120)


class RenewalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: RenewalDecisionType
    confirmed: Literal[True]


class RenewalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_id: UUID
    decision: RenewalDecisionType
    decided_at: datetime
    revisit_review_item_ids: list[UUID] = Field(
        json_schema_extra={"uniqueItems": True},
    )

    @model_validator(mode="after")
    def validate_revisit_review_items(self) -> "RenewalDecision":
        if len(set(self.revisit_review_item_ids)) != len(self.revisit_review_item_ids):
            raise ValueError("재검토 항목 ID는 중복될 수 없습니다.")
        if (
            self.decision != RenewalDecisionType.RENEW_WITH_CHANGES
            and self.revisit_review_item_ids
        ):
            raise ValueError("조건 변경 재계약이 아니면 재검토 항목은 비어 있어야 합니다.")
        return self


class ContractSummary(BaseModel):
    id: UUID
    title: str
    counterparty_name: str
    status: ContractStatus
    start_date: date | None = None
    end_date: date | None = None
    total_amount: int | None = None
    created_at: datetime
    updated_at: datetime


class Contract(BaseModel):
    """Owner-safe contract detail.

    Canonical fields are deliberately nullable: they are filled only after the
    document-analysis flow has verified source evidence.
    """

    id: UUID
    title: str
    counterparty_name: str
    status: ContractStatus
    signed_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    termination_notice_date: date | None = None
    renewal_type: str | None = None
    total_amount: int | None = None
    understood_term: UnderstoodTerm | None = None
    renewal_decision: RenewalDecision | None = None
    modusign_document_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ContractListItem(BaseModel):
    id: UUID
    title: str
    counterparty_name: str
    status: ContractStatus
    total_amount: int | None = None
    end_date: date | None = None
    expiry_d_day: int | None = None
    termination_notice_d_day: int | None = None
    auto_renewal_d_day: int | None = None


class ContractDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_id: UUID
    deleted: Literal[True] = True


class AuditEvent(BaseModel):
    id: UUID
    event_type: AuditEventType
    actor_type: AuditActorType
    summary: str | None = None
    created_at: datetime
