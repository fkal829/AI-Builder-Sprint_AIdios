"""Validated, minimal Modusign webhook payloads.

The requester object is deliberately not modeled because it is vendor metadata,
not an authentication input, and may contain personal contact information.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ModusignWebhookEventType = Literal[
    "document_started",
    "document_signed",
    "document_all_signed",
    "document_rejected",
    "document_request_canceled",
    "document_signing_canceled",
]


class ModusignWebhookEventInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=1, max_length=200)
    type: ModusignWebhookEventType


class ModusignWebhookDocument(BaseModel):
    # Keep unmodeled vendor fields only long enough to calculate the canonical
    # deduplication hash. They are never persisted or logged.
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=200)


class ModusignWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: ModusignWebhookEventInfo
    document: ModusignWebhookDocument
