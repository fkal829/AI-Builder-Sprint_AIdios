"""Owner contract, document, analysis, review, agreement and signature routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.dependencies import get_current_owner_id, get_document_upload_service
from app.core.http import request_id
from app.schemas.common import ApiResponse
from app.schemas.documents import Document, DocumentType
from app.services.documents import DocumentUploadService, read_upload_content

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
