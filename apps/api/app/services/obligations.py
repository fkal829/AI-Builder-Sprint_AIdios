from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.core.enums import IdempotencyOperation, PublicTokenScope
from app.core.exceptions import ResourceNotFound
from app.repositories.obligations import (
    EvidenceLinkCreateOutcome,
    ObligationRecord,
    ObligationRepository,
)
from app.schemas.obligations import (
    Obligation,
    PublicLink,
    PublicLinkCreate,
)
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.public_tokens import PublicTokenService
from app.services.state_machine import InvalidStatusTransition


class ObligationService:
    def __init__(
        self,
        repository: ObligationRepository,
        *,
        idempotency: IdempotencyService | None = None,
        public_tokens: PublicTokenService | None = None,
        public_app_base_url: str = "",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._idempotency = idempotency
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
        idempotency, public_tokens = self._link_dependencies()

        async def perform() -> IdempotentOutcome[PublicLink]:
            created_at = self._utc_now()
            expires_at = created_at + timedelta(hours=payload.expires_in_hours)
            issued, token_record = public_tokens.prepare(
                scope=PublicTokenScope.OBLIGATION_EVIDENCE,
                resource_id=obligation_id,
                expires_at=expires_at,
                created_at=created_at,
            )
            outcome = await self._repository.create_obligation_evidence_link_with_audit(
                owner_id=owner_id,
                contract_id=contract_id,
                obligation_id=obligation_id,
                public_token=token_record,
            )
            if outcome == EvidenceLinkCreateOutcome.NOT_FOUND:
                raise ResourceNotFound()
            if outcome == EvidenceLinkCreateOutcome.INVALID_STATUS_TRANSITION:
                raise InvalidStatusTransition(
                    "PENDING 상태의 이행 항목에만 증빙 제출 링크를 생성할 수 있습니다."
                )
            link = PublicLink(
                public_url=self._public_url(issued.token),
                scope=PublicTokenScope.OBLIGATION_EVIDENCE,
                expires_at=issued.expires_at,
            )
            return IdempotentOutcome(
                status_code=201,
                response=link,
                replay_payload={
                    "token_id": str(token_record.id),
                    "expires_at": issued.expires_at.isoformat(),
                },
            )

        result = await idempotency.execute(
            owner_id=owner_id,
            operation=IdempotencyOperation.EVIDENCE_LINK_CREATE,
            resource_id=obligation_id,
            key=idempotency_key,
            request_payload=payload,
            perform=perform,
            replay=self._replay_evidence_link,
        )
        return result.response

    def _replay_evidence_link(self, stored: dict[str, Any]) -> PublicLink:
        _, public_tokens = self._link_dependencies()
        token = public_tokens.token_for_id(UUID(stored["token_id"]))
        return PublicLink(
            public_url=self._public_url(token),
            scope=PublicTokenScope.OBLIGATION_EVIDENCE,
            expires_at=datetime.fromisoformat(
                stored["expires_at"].replace("Z", "+00:00")
            ),
        )

    def _public_url(self, token: str) -> str:
        return f"{self._public_app_base_url}/obligations/{token}"

    def _link_dependencies(self) -> tuple[IdempotencyService, PublicTokenService]:
        if (
            self._idempotency is None
            or self._public_tokens is None
            or not self._public_app_base_url
        ):
            raise RuntimeError("증빙 제출 링크 생성 의존성이 구성되지 않았습니다.")
        return self._idempotency, self._public_tokens

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
