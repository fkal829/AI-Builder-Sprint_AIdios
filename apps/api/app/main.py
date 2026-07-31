from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.http import (
    canonical_operation_id,
    install_http_contract,
    install_openapi_contract,
    request_id,
)
from app.core.logging import install_uvicorn_access_log_filter
from app.schemas.common import ApiError, ApiResponse
from app.services.state_machine import InvalidStatusTransition

settings = get_settings()
install_uvicorn_access_log_filter()

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="P0 프런트엔드와 FastAPI가 공유하는 HTTP 계약",
    docs_url="/docs" if settings.app_env != "production" else None,
    generate_unique_id_function=canonical_operation_id,
)
install_http_contract(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(InvalidStatusTransition)
async def invalid_status_transition_handler(
    request: Request,
    error: InvalidStatusTransition,
) -> JSONResponse:
    envelope = ApiResponse[None](
        data=None,
        error=ApiError(code=error.code.value, message=str(error)),
        request_id=request_id(request),
    )
    return JSONResponse(
        status_code=409,
        content=envelope.model_dump(mode="json", by_alias=True),
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)
install_openapi_contract(app, server_url=settings.api_v1_prefix)
