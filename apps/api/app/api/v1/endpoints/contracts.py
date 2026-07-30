"""Owner contract, document, analysis, review, agreement and signature routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.api.dependencies import (
    get_current_owner_id,
    get_document_access_service,
    get_document_upload_service,
    get_understood_term_service,
)
from app.core.http import request_id
from app.schemas.common import ApiResponse
from app.schemas.documents import Document, DocumentAccess, DocumentType
from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermInput
from app.services.documents import (
    DocumentAccessService,
    DocumentUploadService,
    read_upload_content,
)
from app.services.understood_terms import UnderstoodTermService

router = APIRouter()


@router.post(
    "/{contract_id}/documents",
    response_model=ApiResponse[Document],
    status_code=201,
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약을 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "업로드 검증 실패"},
    },
)
async def upload_contract_document(
    request: Request,
    contract_id: UUID,
    file: Annotated[UploadFile, File()],
    document_type: Annotated[DocumentType, Form(alias="type")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[
        DocumentUploadService,
        Depends(get_document_upload_service),
    ],
) -> ApiResponse[Document]:
    try:
        content = await read_upload_content(
            file,
            max_size_bytes=service.max_size_bytes,
        )
        document = await service.upload(
            owner_id=owner_id,
            contract_id=contract_id,
            document_type=document_type,
            declared_content_type=file.content_type,
            content=content,
        )
    finally:
        await file.close()
    return ApiResponse(
        data=document,
        error=None,
        request_id=request_id(request),
    )


@router.get(
    "/{contract_id}/documents/{document_id}/access",
    response_model=ApiResponse[DocumentAccess],
    responses={
        200: {
            "description": "소유자용 짧은 원문 접근 URL",
            "headers": {
                "Cache-Control": {
                    "description": "민감한 원문 접근 URL의 캐시 저장 금지",
                    "schema": {"type": "string", "example": "no-store"},
                }
            },
        },
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "문서를 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "페이지 또는 요청 검증 실패"},
    },
)
async def get_contract_document_access(
    request: Request,
    response: Response,
    contract_id: UUID,
    document_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[
        DocumentAccessService,
        Depends(get_document_access_service),
    ],
    source_page: Annotated[int | None, Query(ge=1)] = None,
) -> ApiResponse[DocumentAccess]:
    document_access = await service.get_access(
        owner_id=owner_id,
        contract_id=contract_id,
        document_id=document_id,
        source_page=source_page,
    )
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(
        data=document_access,
        error=None,
        request_id=request_id(request),
    )


@router.put(
    "/{contract_id}/understood-terms",
    response_model=ApiResponse[UnderstoodTerm],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약을 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "이해조건 검증 실패"},
    },
)
async def save_contract_understood_terms(
    request: Request,
    contract_id: UUID,
    payload: UnderstoodTermInput,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[
        UnderstoodTermService,
        Depends(get_understood_term_service),
    ],
) -> ApiResponse[UnderstoodTerm]:
    understood_term = await service.save(
        owner_id=owner_id,
        contract_id=contract_id,
        payload=payload,
    )
    return ApiResponse(
        data=understood_term,
        error=None,
        request_id=request_id(request),
    )
