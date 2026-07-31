"""Authenticated, idempotent external webhook routes."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, Security
from fastapi.security import APIKeyHeader

from app.api.dependencies import get_modusign_webhook_service
from app.core.exceptions import WebhookAuthenticationFailed
from app.schemas.common import ApiResponse
from app.schemas.webhooks import ModusignWebhookEvent
from app.services.webhooks import ModusignWebhookService

router = APIRouter()

modusign_webhook_secret = APIKeyHeader(
    name="X-Modusign-Webhook-Secret",
    scheme_name="ModusignWebhookSecret",
    description="모두싸인 웹훅 등록 시 서버가 설정한 고정 비밀 헤더",
    auto_error=False,
)


@router.post(
    "/modusign",
    status_code=204,
    response_class=Response,
    responses={
        401: {"model": ApiResponse[None], "description": "웹훅 인증 실패"},
        422: {"model": ApiResponse[None], "description": "웹훅 payload 검증 실패"},
    },
)
async def receive_modusign_webhook(
    payload: ModusignWebhookEvent,
    background_tasks: BackgroundTasks,
    webhook_secret: Annotated[
        str | None,
        Security(modusign_webhook_secret),
    ] = None,
    service: Annotated[
        ModusignWebhookService,
        Depends(get_modusign_webhook_service),
    ] = None,
) -> Response:
    if service is None or not service.verify_secret(webhook_secret):
        raise WebhookAuthenticationFailed()
    receipt = await service.receive(payload=payload)
    if receipt is not None:
        background_tasks.add_task(service.process, receipt=receipt)
    return Response(status_code=204)
