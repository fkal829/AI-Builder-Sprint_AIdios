"""Token-protected agency adjustment and obligation routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_adjustment_service
from app.core.http import request_id
from app.schemas.adjustments import (
    AdjustmentResponsesSubmit,
    PublicAdjustment,
    PublicAdjustmentOpen,
    PublicSubmission,
)
from app.schemas.common import ApiResponse
from app.services.adjustments import AdjustmentService

router = APIRouter()


@router.get(
    "/adjustment-requests/{token}",
    response_model=ApiResponse[PublicAdjustment],
)
async def get_public_adjustment_request(
    request: Request,
    token: str,
    service: Annotated[AdjustmentService, Depends(get_adjustment_service)],
) -> ApiResponse[PublicAdjustment]:
    adjustment = await service.get_public_request(token=token)
    return ApiResponse(data=adjustment, error=None, request_id=request_id(request))


@router.post(
    "/adjustment-requests/{token}/open",
    response_model=ApiResponse[PublicAdjustmentOpen],
)
async def open_public_adjustment_request(
    request: Request,
    token: str,
    service: Annotated[AdjustmentService, Depends(get_adjustment_service)],
) -> ApiResponse[PublicAdjustmentOpen]:
    opened = await service.open_public_request(token=token)
    return ApiResponse(data=opened, error=None, request_id=request_id(request))


@router.post(
    "/adjustment-requests/{token}/responses",
    response_model=ApiResponse[PublicSubmission],
    status_code=201,
)
async def submit_public_adjustment_responses(
    request: Request,
    token: str,
    payload: AdjustmentResponsesSubmit,
    service: Annotated[AdjustmentService, Depends(get_adjustment_service)],
) -> ApiResponse[PublicSubmission]:
    submission = await service.submit_public_responses(token=token, payload=payload)
    return ApiResponse(data=submission, error=None, request_id=request_id(request))
