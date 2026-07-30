from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NonNegativeKrw = Annotated[int, Field(strict=True, ge=0)]


class UnderstoodTermSourceType(StrEnum):
    USER_MEMORY = "USER_MEMORY"


class UnderstoodTermFields(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    duration_text: str = Field(min_length=1)
    monthly_amount: NonNegativeKrw | None
    total_amount: NonNegativeKrw | None
    refund_text: str = Field(min_length=1)
    termination_text: str = Field(min_length=1)
    source_type: UnderstoodTermSourceType


class UnderstoodTermInput(UnderstoodTermFields):
    pass


class UnderstoodTerm(UnderstoodTermFields):
    contract_id: UUID
