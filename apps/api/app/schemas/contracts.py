from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import ContractStatus


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
    total_amount: Decimal | None = None
    created_at: datetime
    updated_at: datetime
