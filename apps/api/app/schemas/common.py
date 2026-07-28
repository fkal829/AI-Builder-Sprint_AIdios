from typing import Generic, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


class ApiResponse(BaseModel, Generic[DataT]):
    data: DataT | None
    error: ApiError | None
    requestId: str = Field(pattern=r"^req_[a-f0-9]+$")
