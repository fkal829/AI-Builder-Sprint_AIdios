from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import PUBLIC_ERROR_CODE_VALUES

PublicErrorCode = Literal[*PUBLIC_ERROR_CODE_VALUES]


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: PublicErrorCode
    message: str


class ErrorResponse(BaseModel):
    """Public failure envelope with a non-null error payload."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: None
    error: ApiError
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")


class ApiResponse[DataT](BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: DataT | None
    error: ApiError | None
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")

    @model_validator(mode="after")
    def require_exactly_one_payload(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("응답에는 data 또는 error 중 정확히 하나만 있어야 합니다.")
        return self
