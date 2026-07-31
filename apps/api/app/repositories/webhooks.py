from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.core.enums import ModusignStatus


@dataclass(frozen=True)
class ModusignWebhookReceipt:
    deduplication_key: str
    event_id: str | None
    event_type: str
    document_id: str
    received_at: datetime


class ModusignWebhookRepository(Protocol):
    async def record_modusign_webhook_event(
        self,
        *,
        receipt: ModusignWebhookReceipt,
    ) -> bool: ...

    async def mark_modusign_webhook_processed(
        self,
        *,
        deduplication_key: str,
        processed_at: datetime,
    ) -> None: ...

    async def apply_modusign_document_status(
        self,
        *,
        signature_id: UUID,
        document_id: str,
        event_key: str,
        status: ModusignStatus,
        processed_at: datetime,
    ) -> bool: ...
