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
from fastapi.responses import JSONResponse

from app.api.dependencies import (
    get_adjustment_service,
    get_agreement_service,
    get_analysis_service,
    get_contract_service,
    get_current_owner_id,
    get_document_access_service,
    get_document_upload_service,
    get_idempotency_service,
    get_obligation_service,
    get_review_item_service,
    get_revised_contract_service,
    get_signature_service,
    get_tone_polish_service,
    get_understood_term_service,
)
from app.core.enums import IdempotencyOperation
from app.core.exceptions import AnalysisStartUnavailable, InvalidDocument
from app.core.http import request_id
from app.schemas.adjustments import (
    AdjustmentCopyPolishRequest,
    AdjustmentCopyPolishResult,
    AdjustmentRequest,
    AdjustmentRequestCreate,
    AdjustmentRequestSent,
    ExplicitConfirmation,
    OwnerAdjustmentDetail,
)
from app.schemas.agreements import AdjustmentConfirmation, Agreement
from app.schemas.analysis import AnalysisStartRequest, AnalysisTask, ReviewItem, ReviewItemUpdate
from app.schemas.common import ApiError, ApiResponse
from app.schemas.contracts import (
    AuditEvent,
    Contract,
    ContractCreate,
    ContractListItem,
    RenewalDecision,
    RenewalDecisionRequest,
)
from app.schemas.documents import (
    ContractDocumentUploadType,
    Document,
    DocumentAccess,
    DocumentType,
)
from app.schemas.obligations import (
    EvidenceReviewRequest,
    Obligation,
    ObligationList,
    PublicLink,
    PublicLinkCreate,
)
from app.schemas.revised_contracts import (
    RevisedContractReview,
    RevisedContractReviewConfirmation,
    RevisedContractReviewCreate,
)
from app.schemas.signatures import (
    EmbeddedSignatureDraft,
    EmbeddedSignatureDraftCreate,
    Signature,
)
from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermInput
from app.services.adjustments import AdjustmentService
from app.services.agreements import AgreementService
from app.services.analysis import AnalysisService
from app.services.contracts import ContractService
from app.services.documents import (
    DocumentAccessService,
    DocumentUploadService,
    read_upload_content,
)
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.obligations import ObligationService
from app.services.review_items import ReviewItemService
from app.services.revised_contracts import RevisedContractService
from app.services.signatures import SignatureService
from app.services.tone_polish import TonePolishService
from app.services.understood_terms import UnderstoodTermService

router = APIRouter()

NO_STORE_RESPONSE_HEADERS = {
    "Cache-Control": {
        "description": "민감한 공개 URL의 캐시 저장 금지",
        "schema": {"type": "string", "example": "no-store"},
    }
}


@router.post(
    "/{contract_id}/adjustment-copy/polish",
    response_model=ApiResponse[AdjustmentCopyPolishResult],
    responses={
        200: {"description": "다듬은 문구 미리보기", "headers": NO_STORE_RESPONSE_HEADERS},
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
        422: {
            "model": ApiResponse[None],
            "description": "다듬기 입력 검증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        502: {
            "model": ApiResponse[None],
            "description": "Solar 다듬기 또는 출력 검증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
)
async def polish_adjustment_copy(
    request: Request,
    response: Response,
    contract_id: UUID,
    payload: AdjustmentCopyPolishRequest,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[TonePolishService, Depends(get_tone_polish_service)],
) -> ApiResponse[AdjustmentCopyPolishResult]:
    result = await service.polish(
        owner_id=owner_id,
        contract_id=contract_id,
        payload=payload,
    )
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(data=result, error=None, request_id=request_id(request))


@router.post(
    "/{contract_id}/revised-contract-reviews",
    response_model=ApiResponse[RevisedContractReview],
    status_code=201,
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약 또는 문서를 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "대조 생성 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "대조 요청 검증 실패"},
    },
)
async def create_revised_contract_review(
    request: Request,
    contract_id: UUID,
    payload: RevisedContractReviewCreate,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[RevisedContractService, Depends(get_revised_contract_service)],
) -> ApiResponse[RevisedContractReview]:
    review = await service.create_review(
        owner_id=owner_id,
        contract_id=contract_id,
        payload=payload,
    )
    return ApiResponse(data=review, error=None, request_id=request_id(request))


@router.get(
    "/{contract_id}/revised-contract-reviews/latest",
    response_model=ApiResponse[RevisedContractReview],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "대조 결과를 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "계약 ID 검증 실패"},
    },
)
async def get_latest_revised_contract_review(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[RevisedContractService, Depends(get_revised_contract_service)],
) -> ApiResponse[RevisedContractReview]:
    review = await service.get_latest(owner_id=owner_id, contract_id=contract_id)
    return ApiResponse(data=review, error=None, request_id=request_id(request))


@router.post(
    "/{contract_id}/revised-contract-reviews/{review_id}/confirmation",
    response_model=ApiResponse[RevisedContractReview],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "대조 결과를 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "최종 확인 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "확인 요청 검증 실패"},
    },
)
async def confirm_revised_contract_review(
    request: Request,
    contract_id: UUID,
    review_id: UUID,
    payload: RevisedContractReviewConfirmation,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[RevisedContractService, Depends(get_revised_contract_service)],
) -> ApiResponse[RevisedContractReview]:
    review = await service.confirm(
        owner_id=owner_id,
        contract_id=contract_id,
        review_id=review_id,
        payload=payload,
    )
    return ApiResponse(data=review, error=None, request_id=request_id(request))


@router.post(
    "/{contract_id}/adjustment-confirmation",
    response_model=ApiResponse[AdjustmentRequest],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약 또는 조정 요청을 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "조정 확정 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "확정 요청 검증 실패"},
    },
)
async def confirm_adjustment(
    request: Request,
    contract_id: UUID,
    payload: AdjustmentConfirmation,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[AdjustmentService, Depends(get_adjustment_service)],
) -> ApiResponse[AdjustmentRequest]:
    adjustment = await service.confirm(
        owner_id=owner_id,
        contract_id=contract_id,
        payload=payload,
    )
    return ApiResponse(data=adjustment, error=None, request_id=request_id(request))


@router.post(
    "/{contract_id}/agreement",
    deprecated=True,
    response_model=ApiResponse[Agreement],
    status_code=201,
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약을 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "레거시 합의서 생성 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "요청 검증 실패"},
    },
)
async def create_agreement(
    request: Request,
    contract_id: UUID,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[AgreementService, Depends(get_agreement_service)],
) -> ApiResponse[Agreement]:
    agreement = await service.create(
        owner_id=owner_id,
        contract_id=contract_id,
        idempotency_key=idempotency_key,
    )
    return ApiResponse(data=agreement, error=None, request_id=request_id(request))


@router.get(
    "/{contract_id}/agreement",
    deprecated=True,
    response_model=ApiResponse[Agreement],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "합의서를 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "계약 ID 검증 실패"},
    },
)
async def get_agreement(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[AgreementService, Depends(get_agreement_service)],
) -> ApiResponse[Agreement]:
    agreement = await service.get(owner_id=owner_id, contract_id=contract_id)
    return ApiResponse(data=agreement, error=None, request_id=request_id(request))


@router.post(
    "/{contract_id}/signature-embedded-drafts",
    response_model=ApiResponse[EmbeddedSignatureDraft],
    status_code=201,
    responses={
        201: {
            "description": "내장 서명 초안 생성",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약 또는 합의서를 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "서명 초안 생성 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "요청 검증 실패"},
        502: {"model": ApiResponse[None], "description": "모두싸인 요청 실패"},
    },
)
async def create_signature_embedded_draft(
    request: Request,
    response: Response,
    contract_id: UUID,
    payload: EmbeddedSignatureDraftCreate,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[SignatureService, Depends(get_signature_service)],
) -> ApiResponse[EmbeddedSignatureDraft]:
    draft = await service.create_embedded_draft(
        owner_id=owner_id,
        contract_id=contract_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(data=draft, error=None, request_id=request_id(request))


@router.get(
    "/{contract_id}/signature",
    response_model=ApiResponse[Signature],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "서명 상태를 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "계약 ID 검증 실패"},
    },
)
async def get_signature(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[SignatureService, Depends(get_signature_service)],
) -> ApiResponse[Signature]:
    signature = await service.get(owner_id=owner_id, contract_id=contract_id)
    return ApiResponse(data=signature, error=None, request_id=request_id(request))


@router.post(
    "/{contract_id}/adjustment-requests",
    response_model=ApiResponse[AdjustmentRequest],
    status_code=201,
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약 또는 검토 항목을 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "조정 요청 생성 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "조정 요청 검증 실패"},
    },
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
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "조정 요청을 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "경로 ID 검증 실패"},
        502: {"model": ApiResponse[None], "description": "역제안 비교 실패"},
    },
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
    responses={
        200: {
            "description": "조정 요청 링크 생성",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        401: {
            "model": ApiResponse[None],
            "description": "인증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        404: {
            "model": ApiResponse[None],
            "description": "조정 요청을 찾을 수 없음",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        409: {
            "model": ApiResponse[None],
            "description": "발송 상태 또는 멱등 충돌",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        422: {
            "model": ApiResponse[None],
            "description": "발송 확인 요청 검증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
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


@router.post(
    "",
    response_model=ApiResponse[Contract],
    status_code=201,
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        422: {"model": ApiResponse[None], "description": "계약 입력 검증 실패"},
    },
)
async def create_contract(
    request: Request,
    payload: ContractCreate,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[Contract]:
    contract = await service.create(owner_id=owner_id, payload=payload)
    return ApiResponse(data=contract, error=None, request_id=request_id(request))


@router.get(
    "",
    response_model=ApiResponse[list[ContractListItem]],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
    },
)
async def list_contracts(
    request: Request,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[list[ContractListItem]]:
    contracts = await service.list(owner_id=owner_id)
    return ApiResponse(data=contracts, error=None, request_id=request_id(request))


@router.get(
    "/{contract_id}",
    response_model=ApiResponse[Contract],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약을 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "계약 ID 검증 실패"},
    },
)
async def get_contract(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[Contract]:
    contract = await service.get(owner_id=owner_id, contract_id=contract_id)
    return ApiResponse(data=contract, error=None, request_id=request_id(request))


@router.get(
    "/{contract_id}/timeline",
    response_model=ApiResponse[list[AuditEvent]],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약을 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "계약 ID 검증 실패"},
    },
)
async def get_contract_timeline(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[list[AuditEvent]]:
    timeline = await service.timeline(owner_id=owner_id, contract_id=contract_id)
    return ApiResponse(data=timeline, error=None, request_id=request_id(request))


@router.get(
    "/{contract_id}/obligations",
    response_model=ApiResponse[ObligationList],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약을 찾을 수 없음"},
        422: {"model": ApiResponse[None], "description": "계약 ID 검증 실패"},
    },
)
async def list_contract_obligations(
    request: Request,
    contract_id: UUID,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ObligationService, Depends(get_obligation_service)],
) -> ApiResponse[ObligationList]:
    obligations = await service.list(owner_id=owner_id, contract_id=contract_id)
    return ApiResponse(
        data=list(obligations),
        error=None,
        request_id=request_id(request),
    )


@router.post(
    "/{contract_id}/obligations/{obligation_id}/evidence-link",
    response_model=ApiResponse[PublicLink],
    status_code=201,
    responses={
        201: {
            "description": "증빙 제출 링크 생성",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        401: {
            "model": ApiResponse[None],
            "description": "인증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        404: {
            "model": ApiResponse[None],
            "description": "이행 항목을 찾을 수 없음",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        409: {
            "model": ApiResponse[None],
            "description": "이행 항목 상태 충돌",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
        422: {
            "model": ApiResponse[None],
            "description": "요청 검증 실패",
            "headers": NO_STORE_RESPONSE_HEADERS,
        },
    },
)
async def create_obligation_evidence_link(
    request: Request,
    contract_id: UUID,
    obligation_id: UUID,
    payload: PublicLinkCreate,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ObligationService, Depends(get_obligation_service)],
) -> ApiResponse[PublicLink]:
    link = await service.create_evidence_link(
        owner_id=owner_id,
        contract_id=contract_id,
        obligation_id=obligation_id,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    return ApiResponse(
        data=link,
        error=None,
        request_id=request_id(request),
    )


@router.patch(
    "/{contract_id}/obligations/{obligation_id}",
    response_model=ApiResponse[Obligation],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "이행 항목을 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "이행 항목 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "요청 검증 실패"},
    },
)
async def review_obligation_evidence(
    request: Request,
    contract_id: UUID,
    obligation_id: UUID,
    payload: EvidenceReviewRequest,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ObligationService, Depends(get_obligation_service)],
) -> ApiResponse[Obligation]:
    obligation = await service.review_evidence(
        owner_id=owner_id,
        contract_id=contract_id,
        obligation_id=obligation_id,
        payload=payload,
    )
    return ApiResponse(
        data=obligation,
        error=None,
        request_id=request_id(request),
    )


@router.put(
    "/{contract_id}/renewal-decision",
    response_model=ApiResponse[RenewalDecision],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "계약을 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "재계약 검토 기간이 아님"},
        422: {"model": ApiResponse[None], "description": "요청 검증 실패"},
    },
)
async def save_contract_renewal_decision(
    request: Request,
    contract_id: UUID,
    payload: RenewalDecisionRequest,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ContractService, Depends(get_contract_service)],
) -> ApiResponse[RenewalDecision]:
    decision = await service.save_renewal_decision(
        owner_id=owner_id,
        contract_id=contract_id,
        payload=payload,
    )
    return ApiResponse(data=decision, error=None, request_id=request_id(request))


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
    document_type: Annotated[ContractDocumentUploadType, Form(alias="type")],
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[
        DocumentUploadService,
        Depends(get_document_upload_service),
    ],
) -> ApiResponse[Document]:
    try:
        form = await request.form()
        unexpected_fields = set(form.keys()) - {"file", "type"}
        if unexpected_fields:
            raise InvalidDocument("허용되지 않은 multipart 필드가 포함되어 있습니다.")
        content = await read_upload_content(
            file,
            max_size_bytes=service.max_size_bytes,
        )
        document = await service.upload(
            owner_id=owner_id,
            contract_id=contract_id,
            document_type=DocumentType(document_type),
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
) -> ApiResponse[AnalysisTask] | JSONResponse:
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

    def admission_failure(
        error: Exception,
    ) -> IdempotentOutcome[ApiResponse[AnalysisTask]] | None:
        if not isinstance(error, AnalysisStartUnavailable):
            return None
        envelope = ApiResponse[AnalysisTask](
            data=None,
            error=ApiError(code=error.code.value, message=error.message),
            request_id=current_request_id,
        )
        return IdempotentOutcome(
            status_code=error.status_code,
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
        exception_outcome=admission_failure,
    )
    if outcome.replayed:
        request.state.request_id = outcome.response.request_id
    if not outcome.replayed and outcome.response.data is not None:
        background_tasks.add_task(
            service.process,
            owner_id=owner_id,
            task_id=outcome.response.data.id,
        )
    if outcome.status_code != 202:
        return JSONResponse(
            status_code=outcome.status_code,
            content=outcome.response.model_dump(mode="json", by_alias=True),
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


@router.patch(
    "/{contract_id}/review-items/{item_id}",
    response_model=ApiResponse[ReviewItem],
    responses={
        401: {"model": ApiResponse[None], "description": "인증 실패"},
        404: {"model": ApiResponse[None], "description": "검토 항목을 찾을 수 없음"},
        409: {"model": ApiResponse[None], "description": "검토 항목 상태 충돌"},
        422: {"model": ApiResponse[None], "description": "선택값 또는 ID 검증 실패"},
    },
)
async def update_contract_review_item(
    request: Request,
    contract_id: UUID,
    item_id: UUID,
    payload: ReviewItemUpdate,
    owner_id: Annotated[UUID, Depends(get_current_owner_id)],
    service: Annotated[ReviewItemService, Depends(get_review_item_service)],
) -> ApiResponse[ReviewItem]:
    item = await service.update_selection(
        owner_id=owner_id,
        contract_id=contract_id,
        item_id=item_id,
        payload=payload,
    )
    return ApiResponse(
        data=item,
        error=None,
        request_id=request_id(request),
    )
