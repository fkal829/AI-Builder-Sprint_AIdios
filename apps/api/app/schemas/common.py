from pydantic import BaseModel, ConfigDict, Field


class ApiError(BaseModel):
    code: str
    message: str


class ApiResponse[DataT](BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: DataT | None
    error: ApiError | None
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")
