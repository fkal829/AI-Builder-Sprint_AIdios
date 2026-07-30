from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class DocumentType(StrEnum):
    CONTRACT = "CONTRACT"
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
