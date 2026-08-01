"""Owner-only advertisement performance report routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.dependencies import (
    get_current_owner_id,
    get_performance_confirmation_service,
    get_performance_report_upload_service,
)
from app.core.exceptions import InvalidDocument
from app.core.http import request_id
from app.schemas.common import ApiError, ApiResponse
from app.schemas.performance import (
    PerformanceReportConfirmation,
    PerformanceReportConfirmed,
    PerformanceReportCreated,
)
from app.services.documents import read_upload_content
from app.services.performance_confirmation import PerformanceConfirmationService
from app.services.performance_upload import PerformanceReportUploadService

router = APIRouter()

NO_STORE_RESPONSE_HEADERS = {
    "Cache-Control": {
        "description": "민감한 계약·성과 자료의 캐시 저장 금지",
        "schema": {"type": "string", "example": "no-store"},
    }
}

PERFORMANCE_REPORT_UPLOAD_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["period", "file"],
                    "properties": {
                        "period": {
                            "type": "string",
                            "pattern": r"^[0-9]{4}-(0[1-9]|1[0-2])$",
                            "description": "리포트 대상 달력 월(YYYY-MM)",
                            "examples": ["2026-07"],
                        },
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": (
                                "MIME와 magic bytes가 일치하는 비어 있지 않은 PDF, PNG 또는 JPEG"
                            ),
                        },
                    },
                }
            }
        },
    }
}


@router.post(
    "/{contract_id}/performance-reports",
    response_model=ApiResponse[PerformanceReportCreated],
    status_code=201,
    openapi_extra=PERFORMANCE_REPORT_UPLOAD_OPENAPI,
    responses={
        201: {
            "description": "UPLOADED 광고효과 리포트 생성",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        401: {
            "model": ApiResponse[None],
            "description": "인증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        404: {
            "model": ApiResponse[None],
            "description": "계약을 찾을 수 없음",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        409: {
            "model": ApiResponse[None],
            "description": "멱등·월 중복 또는 계약 상태 충돌",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        422: {
            "model": ApiResponse[None],
            "description": "리포트 파일 또는 요청 검증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        503: {
            "model": ApiResponse[None],
            "description": "private Storage 또는 업로드 저장 기반 장애",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
)
async def create_performance_report(
    request: Request,
    contract_id: UUID,
    period: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[
        PerformanceReportUploadService,
        Depends(get_performance_report_upload_service),
    ],
) -> ApiResponse[PerformanceReportCreated] | JSONResponse:
    current_request_id = request_id(request)
    uploads_to_close: list[StarletteUploadFile] = [file]
    try:
        form = await request.form()
        form_items = list(form.multi_items())
        uploads_to_close.extend(
            value
            for _name, value in form_items
            if isinstance(value, StarletteUploadFile) and value is not file
        )
        field_names = sorted(name for name, _value in form_items)
        if field_names != ["file", "period"]:
            raise InvalidDocument("multipart에는 period와 file을 각각 하나씩만 보낼 수 있습니다.")
        content = await read_upload_content(
            file,
            max_size_bytes=service.max_size_bytes,
        )
        result = await service.upload(
            owner_id=owner_id,
            contract_id=contract_id,
            idempotency_key=idempotency_key,
            period=period,
            declared_content_type=file.content_type,
            content=content,
            request_id=current_request_id,
        )
    finally:
        for uploaded in uploads_to_close:
            await uploaded.close()
    if result.replayed:
        request.state.request_id = result.request_id
    if result.error_code is not None:
        envelope = ApiResponse[None](
            data=None,
            error=ApiError(
                code=result.error_code.value,
                message=result.error_message or "요청을 처리할 수 없습니다.",
            ),
            request_id=result.request_id,
        )
        return JSONResponse(
            status_code=result.status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )
    if result.report is None:
        raise RuntimeError("성과 리포트 업로드 응답이 없습니다.")
    return ApiResponse(
        data=result.report,
        error=None,
        request_id=result.request_id,
    )


@router.patch(
    "/{contract_id}/performance-reports/{report_id}",
    response_model=ApiResponse[PerformanceReportConfirmed],
    responses={
        200: {
            "description": "최초 확정 또는 정정된 광고효과 리포트",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        401: {
            "model": ApiResponse[None],
            "description": "인증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        404: {
            "model": ApiResponse[None],
            "description": "계약 또는 리포트를 찾을 수 없음",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        409: {
            "model": ApiResponse[None],
            "description": "revision 충돌, 정정 의존성 또는 상태 충돌",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        422: {
            "model": ApiResponse[None],
            "description": "요청 검증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
)
async def confirm_performance_report(
    request: Request,
    contract_id: UUID,
    report_id: UUID,
    payload: PerformanceReportConfirmation,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[
        PerformanceConfirmationService,
        Depends(get_performance_confirmation_service),
    ],
) -> ApiResponse[PerformanceReportConfirmed]:
    confirmed = await service.confirm(
        owner_id=owner_id,
        contract_id=contract_id,
        report_id=report_id,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    return ApiResponse(
        data=confirmed,
        error=None,
        request_id=request_id(request),
    )
