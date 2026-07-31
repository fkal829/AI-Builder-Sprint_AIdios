"""Authenticated, idempotent external webhook routes."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Response

from app.api.dependencies import get_modusign_webhook_service
from app.core.exceptions import WebhookAuthenticationFailed
from app.schemas.webhooks import ModusignWebhookEvent
from app.services.webhooks import ModusignWebhookService

router = APIRouter()


@router.post("/modusign", status_code=204, response_class=Response)
async def receive_modusign_webhook(
    payload: ModusignWebhookEvent,
    background_tasks: BackgroundTasks,
    webhook_secret: Annotated[str | None, Header(alias="X-Modusign-Webhook-Secret")] = None,
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
