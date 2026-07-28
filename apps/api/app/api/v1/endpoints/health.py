from uuid import uuid4

from fastapi import APIRouter

from app.schemas.common import ApiResponse
from app.schemas.health import HealthData

router = APIRouter()


@router.get("", response_model=ApiResponse[HealthData])
async def health_check() -> ApiResponse[HealthData]:
    return ApiResponse(
        data=HealthData(status="ok"),
        error=None,
        requestId=f"req_{uuid4().hex}",
    )
