from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field


class DocumentType(StrEnum):
    CONTRACT = "CONTRACT"
    REVISED_CONTRACT = "REVISED_CONTRACT"
    PROPOSAL = "PROPOSAL"
    ESTIMATE = "ESTIMATE"
    MESSAGE = "MESSAGE"
    PERFORMANCE_REPORT = "PERFORMANCE_REPORT"


class ContractDocumentUploadType(StrEnum):
    """Document types accepted by the existing general contract upload API."""

    CONTRACT = "CONTRACT"
    REVISED_CONTRACT = "REVISED_CONTRACT"
    PROPOSAL = "PROPOSAL"
    ESTIMATE = "ESTIMATE"
    MESSAGE = "MESSAGE"


class DocumentParseStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Document(BaseModel):
    id: UUID
    contract_id: UUID
    type: DocumentType
    parse_status: DocumentParseStatus
    created_at: datetime


class DocumentAccess(BaseModel):
    document_id: UUID
    access_url: AnyHttpUrl
    expires_at: datetime
    source_page: int | None = Field(default=None, ge=1)
