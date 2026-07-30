from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.services.state_machine import InvalidStatusTransition

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(InvalidStatusTransition)
async def invalid_status_transition_handler(
    _request: Request,
    error: InvalidStatusTransition,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "data": None,
            "error": {"code": error.code.value, "message": str(error)},
            "requestId": f"req_{uuid4().hex}",
        },
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)
