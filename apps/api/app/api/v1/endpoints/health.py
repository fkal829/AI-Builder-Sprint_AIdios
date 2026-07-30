from fastapi import APIRouter, Request

from app.core.http import request_id
from app.schemas.common import ApiResponse
from app.schemas.health import HealthData

router = APIRouter()


@router.get("", response_model=ApiResponse[HealthData])
async def health_check(request: Request) -> ApiResponse[HealthData]:
    return ApiResponse(
        data=HealthData(status="ok"),
        error=None,
        request_id=request_id(request),
    )
