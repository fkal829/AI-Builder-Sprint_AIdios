"""Owner dashboard aggregation route."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_current_owner_id, get_dashboard_service
from app.core.http import request_id
from app.schemas.common import ApiResponse
from app.schemas.dashboard import Dashboard
from app.services.dashboard import DashboardService

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[Dashboard],
    responses={401: {"model": ApiResponse[None], "description": "인증 실패"}},
)
async def get_dashboard(
    request: Request,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[DashboardService, Depends(get_dashboard_service)],
) -> ApiResponse[Dashboard]:
    dashboard = await service.get(owner_id=owner_id)
    return ApiResponse(data=dashboard, error=None, request_id=request_id(request))
