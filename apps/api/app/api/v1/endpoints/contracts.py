"""Owner contract, document, analysis, review, agreement and signature routes."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
)

from app.api.dependencies import (
    get_adjustment_service,
    get_analysis_service,
    get_contract_service,
    get_current_owner_id,
    get_document_access_service,
    get_document_upload_service,
    get_idempotency_service,
    get_understood_term_service,
)
from app.core.enums import IdempotencyOperation
from app.core.http import request_id
from app.schemas.adjustments import (
    AdjustmentRequest,
    AdjustmentRequestCreate,
    AdjustmentRequestSent,
    ExplicitConfirmation,
    OwnerAdjustmentDetail,
)
from app.schemas.analysis import AnalysisStartRequest, AnalysisTask
from app.schemas.common import ApiResponse
from app.schemas.contracts import AuditEvent, Contract, ContractCreate, ContractListItem
from app.schemas.documents import Document, DocumentAccess, DocumentType
from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermInput
from app.services.adjustments import AdjustmentService
from app.services.analysis import AnalysisService
from app.services.contracts import ContractService
from app.services.documents import (
    DocumentAccessService,
    DocumentUploadService,
    read_upload_content,
)
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.understood_terms import UnderstoodTermService

router = APIRouter()


@router.post(
    "/{contract_id}/adjustment-requests",
    response_model=ApiResponse[AdjustmentRequest],
    status_code=201,
)
async def create_adjustment_request_draft(
    request: Request,
    contract_id: UUID,
    payload: AdjustmentRequestCreate,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[AdjustmentService, Depends(get_adjustment_service)],
) -> ApiResponse[AdjustmentRequest]:
    adjustment = await service.create_draft(
        owner_id=owner_id,
        contract_id=contract_id,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    return ApiResponse(data=adjustment, error=None, request_id=request_id(request))


@router.get(
    "/{contract_id}/adjustment-requests/{adjustment_request_id}",
    response_model=ApiResponse[OwnerAdjustmentDetail],
)
async def get_owner_adjustment_request(
    request: Request,
    contract_id: UUID,
    adjustment_request_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[AdjustmentService, Depends(get_adjustment_service)],
) -> ApiResponse[OwnerAdjustmentDetail]:
    detail = await service.get_detail(
        owner_id=owner_id,
        contract_id=contract_id,
        adjustment_request_id=adjustment_request_id,
    )
    return ApiResponse(data=detail, error=None, request_id=request_id(request))


@router.post(
    "/{contract_id}/adjustment-requests/{adjustment_request_id}/send",
    response_model=ApiResponse[AdjustmentRequestSent],
)
async def send_adjustment_request(
    request: Request,
    response: Response,
    contract_id: UUID,
    adjustment_request_id: UUID,
    payload: ExplicitConfirmation,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[AdjustmentService, Depends(get_adjustment_service)],
) -> ApiResponse[AdjustmentRequestSent]:
    sent = await service.send(
        owner_id=owner_id,
        contract_id=contract_id,
        adjustment_request_id=adjustment_request_id,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(data=sent, error=None, request_id=request_id(request))


@router.post("", response_model=ApiResponse[Contract], status_code=201)
async def create_contract(
    request: Request,
    payload: ContractCreate,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[Contract]:
    contract = await service.create(owner_id=owner_id, payload=payload)
    return ApiResponse(data=contract, error=None, request_id=request_id(request))


@router.get("", response_model=ApiResponse[list[ContractListItem]])
async def list_contracts(
    request: Request,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[list[ContractListItem]]:
    contracts = await service.list(owner_id=owner_id)
    return ApiResponse(data=contracts, error=None, request_id=request_id(request))


@router.get("/{contract_id}", response_model=ApiResponse[Contract])
async def get_contract(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[Contract]:
    contract = await service.get(owner_id=owner_id, contract_id=contract_id)
    return ApiResponse(data=contract, error=None, request_id=request_id(request))


@router.get("/{contract_id}/timeline", response_model=ApiResponse[list[AuditEvent]])
async def get_contract_timeline(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[list[AuditEvent]]:
    timeline = await service.timeline(owner_id=owner_id, contract_id=contract_id)
    return ApiResponse(data=timeline, error=None, request_id=request_id(request))


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


@router.post(
    "/{contract_id}/analysis",
    response_model=ApiResponse[AnalysisTask],
    status_code=202,
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약 또는 문서를 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "분석 시작 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "분석 문서 검증 실패"},
        503: {"model": ApiResponse[None], "description": "분석 작업 접수 실패"},
    },
)
async def start_contract_analysis(
    request: Request,
    background_tasks: BackgroundTasks,
    contract_id: UUID,
    payload: AnalysisStartRequest,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    idempotency: Annotated[IdempotencyService, Depends(get_idempotency_service)],
) -> ApiResponse[AnalysisTask]:
    current_request_id = request_id(request)

    async def perform() -> IdempotentOutcome[ApiResponse[AnalysisTask]]:
        task = await service.start(
            owner_id=owner_id,
            contract_id=contract_id,
            payload=payload,
        )
        envelope = ApiResponse[AnalysisTask](
            data=task,
            error=None,
            request_id=current_request_id,
        )
        return IdempotentOutcome(
            status_code=202,
            response=envelope,
            replay_payload=envelope.model_dump(mode="json", by_alias=True),
        )

    outcome = await idempotency.execute(
        owner_id=owner_id,
        operation=IdempotencyOperation.ANALYSIS_START,
        resource_id=contract_id,
        key=idempotency_key,
        request_payload=payload,
        perform=perform,
        replay=lambda stored: ApiResponse[AnalysisTask].model_validate(stored),
    )
    if not outcome.replayed and outcome.response.data is not None:
        background_tasks.add_task(
            service.process,
            owner_id=owner_id,
            task_id=outcome.response.data.id,
        )
    return outcome.response


@router.get(
    "/{contract_id}/analysis",
    response_model=ApiResponse[AnalysisTask],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "최근 분석 작업을 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "계약 ID 검증 실패"},
    },
)
async def get_contract_analysis(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> ApiResponse[AnalysisTask]:
    task = await service.get_latest(
        owner_id=owner_id,
        contract_id=contract_id,
    )
    return ApiResponse(
        data=task,
        error=None,
        request_id=request_id(request),
    )
