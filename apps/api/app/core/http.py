from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.utils import generate_unique_id
from starlette.responses import Response

from app.core.errors import ErrorCode
from app.core.exceptions import ApiException
from app.schemas.common import ApiError, ApiResponse

CANONICAL_OPERATION_IDS = {
    ("GET", "/health"): "healthCheck",
    ("GET", "/contracts"): "listContracts",
    ("POST", "/contracts"): "createContract",
    ("GET", "/contracts/{contract_id}"): "getContract",
    ("GET", "/contracts/{contract_id}/timeline"): "getContractTimeline",
    ("PUT", "/contracts/{contract_id}/renewal-decision"): "saveRenewalDecision",
    ("POST", "/contracts/{contract_id}/documents"): "uploadContractDocument",
    (
        "GET",
        "/contracts/{contract_id}/documents/{document_id}/access",
    ): "getDocumentAccess",
    ("PUT", "/contracts/{contract_id}/understood-terms"): "saveUnderstoodTerms",
    ("POST", "/contracts/{contract_id}/analysis"): "startAnalysis",
    ("GET", "/contracts/{contract_id}/analysis"): "getAnalysis",
    ("PATCH", "/contracts/{contract_id}/review-items/{item_id}"): "updateReviewItem",
    ("POST", "/contracts/{contract_id}/adjustment-requests"): "createAdjustmentRequest",
    (
        "GET",
        "/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}",
    ): "getOwnerAdjustmentRequest",
    (
        "POST",
        "/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}/send",
    ): "sendAdjustmentRequest",
    ("GET", "/public/adjustment-requests/{token}"): "getPublicAdjustmentRequest",
    ("POST", "/public/adjustment-requests/{token}/open"): "openPublicAdjustmentRequest",
    (
        "POST",
        "/public/adjustment-requests/{token}/responses",
    ): "submitAdjustmentResponses",
    ("POST", "/contracts/{contract_id}/adjustment-confirmation"): "confirmAdjustment",
    (
        "POST",
        "/contracts/{contract_id}/revised-contract-reviews",
    ): "createRevisedContractReview",
    (
        "GET",
        "/contracts/{contract_id}/revised-contract-reviews/latest",
    ): "getLatestRevisedContractReview",
    (
        "POST",
        "/contracts/{contract_id}/revised-contract-reviews/{review_id}/confirmation",
    ): "confirmRevisedContractReview",
    ("POST", "/contracts/{contract_id}/agreement"): "createAgreement",
    ("GET", "/contracts/{contract_id}/agreement"): "getAgreement",
    (
        "POST",
        "/contracts/{contract_id}/signature-embedded-drafts",
    ): "createSignatureEmbeddedDraft",
    ("GET", "/contracts/{contract_id}/signature"): "getSignature",
    ("GET", "/contracts/{contract_id}/obligations"): "listObligations",
    (
        "POST",
        "/contracts/{contract_id}/obligations/{obligation_id}/evidence-link",
    ): "createObligationEvidenceLink",
    ("POST", "/public/obligations/{token}/evidence"): "submitObligationEvidence",
    (
        "PATCH",
        "/contracts/{contract_id}/obligations/{obligation_id}",
    ): "reviewObligation",
    ("GET", "/dashboard"): "getDashboard",
    ("POST", "/webhooks/modusign"): "receiveModusignWebhook",
}

NO_AUTOMATIC_VALIDATION_RESPONSE_OPERATION_IDS = {
    "getPublicAdjustmentRequest",
    "openPublicAdjustmentRequest",
}
PUBLIC_OPERATION_IDS = {
    "healthCheck",
    "getPublicAdjustmentRequest",
    "openPublicAdjustmentRequest",
    "submitAdjustmentResponses",
    "submitObligationEvidence",
}


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", new_request_id())


def set_no_store(response: Response) -> Response:
    """Mark public-token responses as non-cacheable without logging their value."""

    response.headers["Cache-Control"] = "no-store"
    return response


def canonical_operation_id(route: APIRoute) -> str:
    """Use the shared OpenAPI operationId for every registered public route."""

    methods = route.methods - {"HEAD", "OPTIONS"}
    if len(methods) != 1:
        return generate_unique_id(route)

    method = next(iter(methods))
    path = route.path_format
    operation_id = CANONICAL_OPERATION_IDS.get((method, path))
    if operation_id is None:
        matches = [
            candidate
            for (candidate_method, candidate_path), candidate in (CANONICAL_OPERATION_IDS.items())
            if candidate_method == method and path.endswith(candidate_path)
        ]
        operation_id = matches[0] if len(matches) == 1 else None
    return operation_id if operation_id is not None else generate_unique_id(route)


def install_openapi_contract(app: FastAPI, *, server_url: str) -> None:
    """Remove impossible generated responses from the canonical public contract."""

    default_openapi = app.openapi

    def canonical_openapi() -> dict:
        schema = default_openapi()
        schema["servers"] = [{"url": server_url}]
        schema["security"] = [{"BearerAuth": []}]
        for path_item in schema.get("paths", {}).values():
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                operation_id = operation.get("operationId")
                if operation_id in NO_AUTOMATIC_VALIDATION_RESPONSE_OPERATION_IDS:
                    operation.get("responses", {}).pop("422", None)
                if operation_id in PUBLIC_OPERATION_IDS:
                    operation["security"] = []
                elif operation_id == "receiveModusignWebhook":
                    operation["security"] = [{"ModusignWebhookSecret": []}]
                else:
                    operation.pop("security", None)
        return schema

    app.openapi = canonical_openapi


def install_http_contract(app: FastAPI) -> None:
    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = new_request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if (
            "/public/" in request.url.path
            or request.url.path.endswith("/send")
            or request.url.path.endswith("/evidence-link")
        ):
            set_no_store(response)
        return response

    @app.exception_handler(ApiException)
    async def handle_api_exception(request: Request, error: ApiException) -> JSONResponse:
        envelope = ApiResponse[None](
            data=None,
            error=ApiError(code=error.code.value, message=error.message),
            request_id=request_id(request),
        )
        return JSONResponse(
            status_code=error.status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        envelope = ApiResponse[None](
            data=None,
            error=ApiError(
                code=ErrorCode.VALIDATION_ERROR.value,
                message="요청 형식이 올바르지 않습니다.",
            ),
            request_id=request_id(request),
        )
        return JSONResponse(
            status_code=422,
            content=envelope.model_dump(mode="json", by_alias=True),
        )
