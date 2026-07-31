from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.core.errors import ErrorCode
from app.core.exceptions import ApiException
from app.schemas.common import ApiError, ApiResponse


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", new_request_id())


def set_no_store(response: Response) -> Response:
    """Mark public-token responses as non-cacheable without logging their value."""

    response.headers["Cache-Control"] = "no-store"
    return response


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
