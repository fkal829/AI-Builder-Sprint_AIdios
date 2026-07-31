from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.core.enums import ObligationStatus
from app.repositories.public_tokens import PublicTokenRecord


@dataclass(frozen=True)
class ObligationRecord:
    id: UUID
    contract_id: UUID
    title: str
    due_date: date
    assignee: str
    evidence_type: str
    source_document_id: UUID
    source_page: int
    source_text: str
    confidence: float
    evidence_url: str | None
    status: ObligationStatus
    submitted_at: datetime | None
    reviewed_at: datetime | None
    payment_condition_met: bool


class EvidenceLinkCreateOutcome(StrEnum):
    CREATED = "CREATED"
    REPLAY = "REPLAY"
    NOT_FOUND = "NOT_FOUND"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    IDEMPOTENCY_PENDING = "IDEMPOTENCY_PENDING"


@dataclass(frozen=True)
class EvidenceLinkCreateResult:
    outcome: EvidenceLinkCreateOutcome
    token_id: UUID | None = None
    expires_at: datetime | None = None


class EvidenceSubmissionOutcome(StrEnum):
    SUBMITTED = "SUBMITTED"
    NOT_FOUND = "NOT_FOUND"
    EXPIRED = "EXPIRED"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"


class EvidenceReviewOutcome(StrEnum):
    REVIEWED = "REVIEWED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"


@dataclass(frozen=True)
class EvidenceReviewResult:
    outcome: EvidenceReviewOutcome
    obligation: ObligationRecord | None


class ObligationRepository(Protocol):
    async def list_owned_obligations(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> Sequence[ObligationRecord] | None: ...

    async def create_obligation_evidence_link_idempotent(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        obligation_id: UUID,
        idempotency_key: UUID,
        request_hash: str,
        public_token: PublicTokenRecord,
    ) -> EvidenceLinkCreateResult: ...

    async def submit_obligation_evidence_with_audit(
        self,
        *,
        public_token: PublicTokenRecord,
        evidence_url: str,
        submitted_at: datetime,
    ) -> EvidenceSubmissionOutcome: ...

    async def review_obligation_evidence_with_audit(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        obligation_id: UUID,
        decision: ObligationStatus,
        reviewed_at: datetime,
    ) -> EvidenceReviewResult: ...
