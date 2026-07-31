from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.enums import ObligationStatus, PublicTokenScope
from app.core.errors import ErrorCode
from app.core.exceptions import IdempotencyConflict, PublicTokenExpired, ResourceNotFound
from app.repositories.obligations import (
    EvidenceLinkCreateOutcome,
    EvidenceReviewOutcome,
    EvidenceSubmissionOutcome,
    ObligationRecord,
    ObligationRepository,
)
from app.schemas.adjustments import PublicSubmission
from app.schemas.obligations import (
    EvidenceReviewRequest,
    EvidenceSubmission,
    Obligation,
    PublicLink,
    PublicLinkCreate,
)
from app.services.idempotency import request_fingerprint
from app.services.public_tokens import PublicTokenService
from app.services.state_machine import InvalidStatusTransition


class ObligationService:
    def __init__(
        self,
        repository: ObligationRepository,
        *,
        public_tokens: PublicTokenService | None = None,
        public_app_base_url: str = "",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._public_tokens = public_tokens
        self._public_app_base_url = public_app_base_url.rstrip("/")
        self._now = now or (lambda: datetime.now(UTC))

    async def list(self, *, owner_id: UUID, contract_id: UUID) -> Sequence[Obligation]:
        records = await self._repository.list_owned_obligations(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if records is None:
            raise ResourceNotFound()
        return [
            _obligation_from_record(record)
            for record in sorted(records, key=lambda item: (item.due_date, str(item.id)))
        ]

    async def create_evidence_link(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        obligation_id: UUID,
        idempotency_key: UUID,
        payload: PublicLinkCreate,
    ) -> PublicLink:
        public_tokens = self._link_dependency()
        created_at = self._utc_now()
        expires_at = created_at + timedelta(hours=payload.expires_in_hours)
        _issued, token_record = public_tokens.prepare(
            scope=PublicTokenScope.OBLIGATION_EVIDENCE,
            resource_id=obligation_id,
            expires_at=expires_at,
            created_at=created_at,
        )
        result = await self._repository.create_obligation_evidence_link_idempotent(
            owner_id=owner_id,
            contract_id=contract_id,
            obligation_id=obligation_id,
            idempotency_key=idempotency_key,
            request_hash=request_fingerprint(payload),
            public_token=token_record,
        )
        if result.outcome == EvidenceLinkCreateOutcome.NOT_FOUND:
            raise ResourceNotFound()
        if result.outcome == EvidenceLinkCreateOutcome.INVALID_STATUS_TRANSITION:
            raise InvalidStatusTransition(
                "서명 완료 또는 이행 중 계약의 PENDING 이행 항목에만 "
                "증빙 제출 링크를 생성할 수 있습니다."
            )
        if result.outcome in {
            EvidenceLinkCreateOutcome.IDEMPOTENCY_CONFLICT,
            EvidenceLinkCreateOutcome.IDEMPOTENCY_PENDING,
        }:
            raise IdempotencyConflict()
        if result.token_id is None or result.expires_at is None:
            raise RuntimeError("증빙 제출 링크 저장 결과가 없습니다.")
        return PublicLink(
            public_url=self._public_url(public_tokens.token_for_id(result.token_id)),
            scope=PublicTokenScope.OBLIGATION_EVIDENCE,
            expires_at=result.expires_at,
        )

    async def submit_evidence(
        self,
        *,
        token: str,
        payload: EvidenceSubmission,
    ) -> PublicSubmission:
        public_tokens = self._public_token_service()
        token_record = await public_tokens.resolve(
            token=token,
            expected_scope=PublicTokenScope.OBLIGATION_EVIDENCE,
        )
        outcome = await self._repository.submit_obligation_evidence_with_audit(
            public_token=token_record,
            evidence_url=str(payload.evidence_url),
            submitted_at=self._utc_now(),
        )
        if outcome == EvidenceSubmissionOutcome.NOT_FOUND:
            raise ResourceNotFound()
        if outcome == EvidenceSubmissionOutcome.EXPIRED:
            raise PublicTokenExpired(code=ErrorCode.OBLIGATION_LINK_EXPIRED)
        if outcome == EvidenceSubmissionOutcome.INVALID_STATUS_TRANSITION:
            raise InvalidStatusTransition("증빙은 PENDING 상태에서 한 번만 제출할 수 있습니다.")
        return PublicSubmission(submitted=True)

    async def review_evidence(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        obligation_id: UUID,
        payload: EvidenceReviewRequest,
    ) -> Obligation:
        result = await self._repository.review_obligation_evidence_with_audit(
            owner_id=owner_id,
            contract_id=contract_id,
            obligation_id=obligation_id,
            decision=ObligationStatus(payload.decision),
            reviewed_at=self._utc_now(),
        )
        if result.outcome == EvidenceReviewOutcome.NOT_FOUND:
            raise ResourceNotFound()
        if result.outcome == EvidenceReviewOutcome.INVALID_STATUS_TRANSITION:
            raise InvalidStatusTransition(
                "SUBMITTED 상태의 이행 항목만 승인하거나 이의를 제기할 수 있습니다."
            )
        if result.obligation is None:
            raise RuntimeError("증빙 검토 저장 결과가 없습니다.")
        return _obligation_from_record(result.obligation)

    def _public_url(self, token: str) -> str:
        return f"{self._public_app_base_url}/r/{token}/evidence"

    def _link_dependency(self) -> PublicTokenService:
        if self._public_tokens is None or not self._public_app_base_url:
            raise RuntimeError("증빙 제출 링크 생성 의존성이 구성되지 않았습니다.")
        return self._public_tokens

    def _public_token_service(self) -> PublicTokenService:
        if self._public_tokens is None:
            raise RuntimeError("증빙 제출 공개 토큰 의존성이 구성되지 않았습니다.")
        return self._public_tokens

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Obligation timestamps must be timezone-aware.")
        return value.astimezone(UTC)


def _obligation_from_record(record: ObligationRecord) -> Obligation:
    return Obligation(
        id=record.id,
        contract_id=record.contract_id,
        title=record.title,
        due_date=record.due_date,
        assignee=record.assignee,
        evidence_type=record.evidence_type,
        source_document_id=record.source_document_id,
        source_page=record.source_page,
        source_text=record.source_text,
        confidence=record.confidence,
        evidence_url=record.evidence_url,
        status=record.status,
        submitted_at=record.submitted_at,
        reviewed_at=record.reviewed_at,
        payment_condition_met=record.payment_condition_met,
    )
