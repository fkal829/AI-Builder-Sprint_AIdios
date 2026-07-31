"""Token-protected agency adjustment and obligation routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_adjustment_service, get_obligation_service
from app.core.http import request_id
from app.schemas.adjustments import (
    AdjustmentResponsesSubmit,
    PublicAdjustment,
    PublicAdjustmentOpen,
    PublicSubmission,
)
from app.schemas.common import ApiResponse
from app.schemas.obligations import EvidenceSubmission
from app.services.adjustments import AdjustmentService
from app.services.obligations import ObligationService

router = APIRouter()

NO_STORE_RESPONSE_HEADERS = {
    "Cache-Control": {
        "description": "공개 토큰 응답의 캐시 저장 금지",
        "schema": {"type": "string", "example": "no-store"},
    }
}


@router.get(
    "/adjustment-requests/{token}",
    response_model=ApiResponse[PublicAdjustment],
    responses={
        200: {
            "description": "공개 조정 요청 조회",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        404: {
            "model": ApiResponse[None],
            "description": "유효하지 않은 공개 토큰",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        410: {
            "model": ApiResponse[None],
            "description": "만료된 공개 토큰",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
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
    responses={
        200: {
            "description": "공개 조정 요청 열람 기록",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        404: {
            "model": ApiResponse[None],
            "description": "유효하지 않은 공개 토큰",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        410: {
            "model": ApiResponse[None],
            "description": "만료된 공개 토큰",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
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
    responses={
        201: {
            "description": "공개 조정 응답 제출",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        404: {
            "model": ApiResponse[None],
            "description": "유효하지 않은 공개 토큰",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        409: {
            "model": ApiResponse[None],
            "description": "이미 제출했거나 제출 상태 충돌",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        410: {
            "model": ApiResponse[None],
            "description": "만료된 공개 토큰",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        422: {
            "model": ApiResponse[None],
            "description": "공개 응답 검증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
)
async def submit_public_adjustment_responses(
    request: Request,
    token: str,
    payload: AdjustmentResponsesSubmit,
    service: Annotated[AdjustmentService, Depends(get_adjustment_service)],
) -> ApiResponse[PublicSubmission]:
    submission = await service.submit_public_responses(token=token, payload=payload)
    return ApiResponse(data=submission, error=None, request_id=request_id(request))


@router.post(
    "/obligations/{token}/evidence",
    response_model=ApiResponse[PublicSubmission],
    responses={
        200: {
            "description": "증빙 제출 완료",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        404: {
            "model": ApiResponse[None],
            "description": "유효하지 않은 공개 토큰",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        409: {
            "model": ApiResponse[None],
            "description": "이미 제출된 이행 항목",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        410: {
            "model": ApiResponse[None],
            "description": "만료된 공개 토큰",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        422: {
            "model": ApiResponse[None],
            "description": "증빙 URL 검증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
)
async def submit_public_obligation_evidence(
    request: Request,
    token: str,
    payload: EvidenceSubmission,
    service: Annotated[ObligationService, Depends(get_obligation_service)],
) -> ApiResponse[PublicSubmission]:
    submission = await service.submit_evidence(token=token, payload=payload)
    return ApiResponse(data=submission, error=None, request_id=request_id(request))
