from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.core.enums import (
    AdjustmentRequestStatus,
    IdempotencyOperation,
    ReviewItemStatus,
    SuggestionChoice,
)
from app.core.exceptions import InvalidAdjustmentRequest, ResourceNotFound
from app.repositories.adjustments import (
    AdjustmentRepository,
    AdjustmentRequestItemRecord,
    AdjustmentRequestRecord,
    ReviewItemForAdjustment,
)
from app.schemas.adjustments import (
    AdjustmentRequest,
    AdjustmentRequestCreate,
    AdjustmentRequestItem,
    AdjustmentRequestSent,
    OwnerAdjustmentDetail,
)
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.public_tokens import PublicTokenService


class AdjustmentService:
    """Owner-side adjustment draft, detail, and explicit send use cases."""

    def __init__(
        self,
        *,
        repository: AdjustmentRepository,
        idempotency: IdempotencyService,
        public_tokens: PublicTokenService,
        public_app_base_url: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._idempotency = idempotency
        self._public_tokens = public_tokens
        self._public_app_base_url = public_app_base_url.rstrip("/")
        self._now = now or (lambda: datetime.now(UTC))

    async def create_draft(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        idempotency_key: UUID,
        payload: AdjustmentRequestCreate,
    ) -> AdjustmentRequest:
        async def perform() -> IdempotentOutcome[AdjustmentRequest]:
            items = await self._validated_draft_items(
                owner_id=owner_id,
                contract_id=contract_id,
                review_item_ids=payload.review_item_ids,
            )
            now = self._utc_now()
            record = AdjustmentRequestRecord(
                id=uuid4(),
                contract_id=contract_id,
                status=AdjustmentRequestStatus.DRAFT,
                items=tuple(items),
                expires_in_hours=payload.expires_in_hours,
                sent_at=None,
                expires_at=None,
                opened_at=None,
                responded_at=None,
                created_at=now,
                updated_at=now,
            )
            saved = await self._repository.create_adjustment_draft_with_audit(
                owner_id=owner_id,
                record=record,
            )
            if saved is None:
                raise ResourceNotFound()
            adjustment = _adjustment_from_record(saved)
            return IdempotentOutcome(
                status_code=201,
                response=adjustment,
                replay_payload=adjustment.model_dump(mode="json"),
            )

        result = await self._idempotency.execute(
            owner_id=owner_id,
            operation=IdempotencyOperation.ADJUSTMENT_DRAFT_CREATE,
            resource_id=contract_id,
            key=idempotency_key,
            request_payload=payload,
            perform=perform,
            replay=lambda stored: AdjustmentRequest.model_validate(stored),
        )
        return result.response

    async def get_detail(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
    ) -> OwnerAdjustmentDetail:
        record = await self._repository.get_owned_adjustment_request(
            owner_id=owner_id,
            contract_id=contract_id,
            adjustment_request_id=adjustment_request_id,
        )
        if record is None:
            raise ResourceNotFound()
        # Agency response and comparison entries are added by C-5/B; keeping
        # these arrays explicit makes the owner response stable before then.
        return OwnerAdjustmentDetail(
            request=_adjustment_from_record(record),
            responses=[],
            comparisons=[],
        )

    async def send(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        adjustment_request_id: UUID,
        idempotency_key: UUID,
    ) -> AdjustmentRequestSent:
        async def perform() -> IdempotentOutcome[AdjustmentRequestSent]:
            draft = await self._repository.get_owned_adjustment_request(
                owner_id=owner_id,
                contract_id=contract_id,
                adjustment_request_id=adjustment_request_id,
            )
            if draft is None:
                raise ResourceNotFound()
            sent_at = self._utc_now()
            expires_at = sent_at + timedelta(hours=draft.expires_in_hours)
            issued, token_record = self._public_tokens.prepare_adjustment_response(
                adjustment_request_id=adjustment_request_id,
                expires_at=expires_at,
            )
            sent = await self._repository.send_adjustment_with_audit(
                owner_id=owner_id,
                contract_id=contract_id,
                adjustment_request_id=adjustment_request_id,
                sent_at=sent_at,
                public_token=token_record,
            )
            if sent is None or sent.expires_at is None:
                from app.services.state_machine import InvalidStatusTransition

                raise InvalidStatusTransition("조정 요청을 발송할 수 없는 상태입니다.")
            response = AdjustmentRequestSent(
                id=sent.id,
                status=AdjustmentRequestStatus.SENT,
                public_url=self._public_url(issued.token),
                expires_at=sent.expires_at,
            )
            return IdempotentOutcome(
                status_code=200,
                response=response,
                replay_payload={
                    "id": str(sent.id),
                    "expires_at": sent.expires_at.isoformat(),
                    "token_id": str(token_record.id),
                },
            )

        result = await self._idempotency.execute(
            owner_id=owner_id,
            operation=IdempotencyOperation.ADJUSTMENT_SEND,
            resource_id=adjustment_request_id,
            key=idempotency_key,
            request_payload={"confirmed": True},
            perform=perform,
            replay=self._replay_sent,
        )
        return result.response

    async def _validated_draft_items(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        review_item_ids: list[UUID],
    ) -> list[AdjustmentRequestItemRecord]:
        review_items = await self._repository.list_review_items_for_adjustment(
            owner_id=owner_id,
            contract_id=contract_id,
            review_item_ids=review_item_ids,
        )
        if review_items is None:
            raise ResourceNotFound()
        by_id = {item.id: item for item in review_items}
        if set(by_id) != set(review_item_ids):
            raise InvalidAdjustmentRequest("선택한 검토 항목을 찾을 수 없습니다.")
        return [_request_item_from_review(by_id[item_id]) for item_id in review_item_ids]

    def _replay_sent(self, stored: dict[str, Any]) -> AdjustmentRequestSent:
        token = self._public_tokens.token_for_id(UUID(stored["token_id"]))
        return AdjustmentRequestSent(
            id=UUID(stored["id"]),
            status=AdjustmentRequestStatus.SENT,
            public_url=self._public_url(token),
            expires_at=datetime.fromisoformat(stored["expires_at"].replace("Z", "+00:00")),
        )

    def _public_url(self, token: str) -> str:
        return f"{self._public_app_base_url}/adjustments/{token}"

    def _utc_now(self) -> datetime:
        now = self._now()
        if now.tzinfo is None:
            raise ValueError("Adjustment timestamps must be timezone-aware.")
        return now.astimezone(UTC)


def _request_item_from_review(review_item: ReviewItemForAdjustment) -> AdjustmentRequestItemRecord:
    if review_item.status != ReviewItemStatus.SELECTED or review_item.user_choice not in {
        SuggestionChoice.COMPROMISE,
        SuggestionChoice.REQUEST,
    }:
        raise InvalidAdjustmentRequest(
            "SELECTED 상태의 절충안 또는 요청안만 조정 요청에 포함할 수 있습니다."
        )
    request_text = (
        review_item.suggestion_compromise
        if review_item.user_choice == SuggestionChoice.COMPROMISE
        else review_item.suggestion_request
    )
    if not request_text.strip():
        raise InvalidAdjustmentRequest("조정 요청 문구가 비어 있습니다.")
    return AdjustmentRequestItemRecord(
        review_item_id=review_item.id,
        user_choice=review_item.user_choice,
        request_text=request_text,
    )


def _adjustment_from_record(record: AdjustmentRequestRecord) -> AdjustmentRequest:
    return AdjustmentRequest(
        id=record.id,
        contract_id=record.contract_id,
        status=record.status,
        items=[
            AdjustmentRequestItem(
                review_item_id=item.review_item_id,
                user_choice=item.user_choice,
                request_text=item.request_text,
            )
            for item in record.items
        ],
        expires_in_hours=record.expires_in_hours,
        sent_at=record.sent_at,
        expires_at=record.expires_at,
        opened_at=record.opened_at,
        responded_at=record.responded_at,
    )
