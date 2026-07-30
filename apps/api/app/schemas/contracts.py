from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import AuditActorType, AuditEventType, ContractStatus


class ContractCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    counterparty_name: str = Field(min_length=1, max_length=120)


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
    understood_term: dict[str, Any] | None = None
    renewal_decision: dict[str, Any] | None = None
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


class AuditEvent(BaseModel):
    id: UUID
    event_type: AuditEventType
    actor_type: AuditActorType
    summary: str | None = None
    created_at: datetime
