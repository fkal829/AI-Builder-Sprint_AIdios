from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

DataT = TypeVar("DataT")


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


class ApiResponse(BaseModel, Generic[DataT]):
    model_config = ConfigDict(populate_by_name=True)

    data: DataT | None
    error: ApiError | None
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")
