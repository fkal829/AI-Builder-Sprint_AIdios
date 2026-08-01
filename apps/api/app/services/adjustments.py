from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.core.enums import (
    AdjustmentRequestStatus,
    IdempotencyOperation,
    PublicTokenScope,
    ReviewItemStatus,
    SuggestionChoice,
)
from app.core.exceptions import InvalidAdjustmentRequest, ResourceNotFound
from app.repositories.adjustments import (
    AdjustmentRepository,
    AdjustmentRequestItemRecord,
    AdjustmentRequestRecord,
    AdjustmentResponseRecord,
    DocumentClauseForAdjustment,
    ManualReviewItemRecord,
    ReviewItemForAdjustment,
)
from app.schemas.adjustments import (
    AdjustmentRequest,
    AdjustmentRequestCreate,
    AdjustmentRequestItem,
    AdjustmentRequestSent,
    AdjustmentResponseItem,
    AdjustmentResponsesSubmit,
    OwnerAdjustmentDetail,
    PublicAdjustment,
    PublicAdjustmentItem,
    PublicAdjustmentOpen,
    PublicSubmission,
)
from app.schemas.agreements import AdjustmentConfirmation
from app.services.counterproposal import CounterproposalComparator
from app.services.idempotency import IdempotencyService, IdempotentOutcome
from app.services.public_tokens import PublicTokenService
from app.services.state_machine import InvalidStatusTransition


class AdjustmentService:
    """Owner-side adjustment draft, detail, and explicit send use cases."""

    def __init__(
        self,
        *,
        repository: AdjustmentRepository,
        counterproposal_comparator: CounterproposalComparator,
        idempotency: IdempotencyService,
        public_tokens: PublicTokenService,
        public_app_base_url: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._counterproposal_comparator = counterproposal_comparator
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
            items, manual_review_items = await self._validated_draft_items(
                owner_id=owner_id,
                contract_id=contract_id,
                review_item_ids=payload.review_item_ids,
                request_text_overrides=payload.request_text_overrides,
                manual_items={
                    item.document_clause_id: item.request_text
                    for item in payload.manual_items
                },
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
                manual_review_items=tuple(manual_review_items),
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
        detail = await self._repository.get_owned_adjustment_detail(
            owner_id=owner_id,
            contract_id=contract_id,
            adjustment_request_id=adjustment_request_id,
        )
        if detail is None:
            raise ResourceNotFound()
        comparisons = await self._counterproposal_comparator.compare(
            request_items=detail.request.items,
            responses=detail.responses,
        )
        return OwnerAdjustmentDetail(
            request=_adjustment_from_record(detail.request),
            responses=[_response_from_record(response) for response in detail.responses],
            comparisons=comparisons,
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

    async def get_public_request(self, *, token: str) -> PublicAdjustment:
        token_record = await self._public_tokens.resolve(
            token=token,
            expected_scope=PublicTokenScope.ADJUSTMENT_RESPONSE,
        )
        public = await self._repository.get_public_adjustment_request(
            adjustment_request_id=token_record.resource_id,
        )
        if public is None or public.request.status not in {
            AdjustmentRequestStatus.SENT,
            AdjustmentRequestStatus.OPENED,
            AdjustmentRequestStatus.RESPONDED,
            AdjustmentRequestStatus.CONFIRMED,
        }:
            raise ResourceNotFound()
        if public.request.expires_at is None:
            raise ResourceNotFound()
        return PublicAdjustment(
            contract_title=public.contract_title,
            status=public.request.status,
            expires_at=public.request.expires_at,
            items=[
                PublicAdjustmentItem(
                    item_id=self._public_item_id(
                        adjustment_request_id=public.request.id,
                        review_item_id=item.review_item_id,
                    ),
                    request_text=item.request_text,
                )
                for item in public.request.items
            ],
        )

    async def open_public_request(self, *, token: str) -> PublicAdjustmentOpen:
        token_record = await self._public_tokens.resolve(
            token=token,
            expected_scope=PublicTokenScope.ADJUSTMENT_RESPONSE,
        )
        opened = await self._repository.open_public_adjustment_request(
            adjustment_request_id=token_record.resource_id,
            opened_at=self._utc_now(),
        )
        if opened is None or opened.opened_at is None:
            raise ResourceNotFound()
        return PublicAdjustmentOpen(
            status=AdjustmentRequestStatus.OPENED,
            opened_at=opened.opened_at,
        )

    async def submit_public_responses(
        self,
        *,
        token: str,
        payload: AdjustmentResponsesSubmit,
    ) -> PublicSubmission:
        token_record = await self._public_tokens.resolve(
            token=token,
            expected_scope=PublicTokenScope.ADJUSTMENT_RESPONSE,
        )
        public = await self._repository.get_public_adjustment_request(
            adjustment_request_id=token_record.resource_id,
        )
        if public is None:
            raise ResourceNotFound()
        responses = self._response_records_from_payload(
            adjustment_request_id=public.request.id,
            request_item_ids={item.review_item_id for item in public.request.items},
            payload=payload,
        )
        submitted = await self._repository.submit_public_adjustment_responses(
            adjustment_request_id=public.request.id,
            responses=responses,
            responded_at=self._utc_now(),
        )
        if submitted is None:
            raise InvalidStatusTransition("조정 응답을 제출할 수 없는 상태입니다.")
        return PublicSubmission(submitted=True)

    async def confirm(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: AdjustmentConfirmation,
    ) -> AdjustmentRequest:
        confirmed = await self._repository.confirm_adjustment_with_audit(
            owner_id=owner_id,
            contract_id=contract_id,
            adjustment_request_id=payload.adjustment_request_id,
            resolutions=tuple(
                (item.review_item_id, item.resolution) for item in payload.confirmed_items
            ),
            confirmed_at=self._utc_now(),
        )
        if confirmed is None:
            raise InvalidStatusTransition("조정 결과를 확정할 수 없는 상태입니다.")
        return _adjustment_from_record(confirmed)

    async def _validated_draft_items(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        review_item_ids: list[UUID],
        request_text_overrides: dict[UUID, str],
        manual_items: dict[UUID, str],
    ) -> tuple[list[AdjustmentRequestItemRecord], list[ManualReviewItemRecord]]:
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
        adjustment_items = [
            _request_item_from_review(
                by_id[item_id],
                request_text_override=request_text_overrides.get(item_id),
            )
            for item_id in review_item_ids
        ]
        clauses = await self._repository.list_document_clauses_for_adjustment(
            owner_id=owner_id,
            contract_id=contract_id,
            document_clause_ids=list(manual_items),
        )
        if clauses is None:
            raise ResourceNotFound()
        clauses_by_id = {clause.id: clause for clause in clauses}
        if set(clauses_by_id) != set(manual_items):
            raise InvalidAdjustmentRequest("선택한 계약 원문 조항을 찾을 수 없습니다.")

        manual_records = [
            _manual_review_item(
                contract_id=contract_id,
                clause=clauses_by_id[clause_id],
                request_text=manual_items[clause_id],
            )
            for clause_id in manual_items
        ]
        adjustment_items.extend(
            AdjustmentRequestItemRecord(
                review_item_id=item.id,
                user_choice=SuggestionChoice.REQUEST,
                request_text=item.request_text,
                before_text=item.source_text,
            )
            for item in manual_records
        )
        return adjustment_items, manual_records

    def _replay_sent(self, stored: dict[str, Any]) -> AdjustmentRequestSent:
        token = self._public_tokens.token_for_id(UUID(stored["token_id"]))
        return AdjustmentRequestSent(
            id=UUID(stored["id"]),
            status=AdjustmentRequestStatus.SENT,
            public_url=self._public_url(token),
            expires_at=datetime.fromisoformat(stored["expires_at"].replace("Z", "+00:00")),
        )

    def _public_url(self, token: str) -> str:
        return f"{self._public_app_base_url}/r/{token}"

    def _public_item_id(
        self,
        *,
        adjustment_request_id: UUID,
        review_item_id: UUID,
    ) -> str:
        return self._public_tokens.adjustment_item_id(
            adjustment_request_id=adjustment_request_id,
            review_item_id=review_item_id,
        )

    def _response_records_from_payload(
        self,
        *,
        adjustment_request_id: UUID,
        request_item_ids: set[UUID],
        payload: AdjustmentResponsesSubmit,
    ) -> tuple[AdjustmentResponseRecord, ...]:
        item_ids_by_public_id = {
            self._public_item_id(
                adjustment_request_id=adjustment_request_id,
                review_item_id=review_item_id,
            ): review_item_id
            for review_item_id in request_item_ids
        }
        submitted_public_ids = {response.item_id for response in payload.responses}
        if submitted_public_ids != set(item_ids_by_public_id):
            raise InvalidAdjustmentRequest(
                "공개 요청의 모든 항목을 정확히 한 번씩 응답해야 합니다."
            )
        return tuple(
            AdjustmentResponseRecord(
                review_item_id=item_ids_by_public_id[response.item_id],
                decision=response.decision,
                counter_text=response.counter_text,
                reason=response.reason,
            )
            for response in payload.responses
        )

    def _utc_now(self) -> datetime:
        now = self._now()
        if now.tzinfo is None:
            raise ValueError("Adjustment timestamps must be timezone-aware.")
        return now.astimezone(UTC)


def _request_item_from_review(
    review_item: ReviewItemForAdjustment,
    *,
    request_text_override: str | None = None,
) -> AdjustmentRequestItemRecord:
    if review_item.status != ReviewItemStatus.SELECTED or review_item.user_choice not in {
        SuggestionChoice.COMPROMISE,
        SuggestionChoice.REQUEST,
    }:
        raise InvalidAdjustmentRequest(
            "SELECTED 상태의 절충안 또는 요청안만 조정 요청에 포함할 수 있습니다."
        )
    request_text = request_text_override.strip() if request_text_override is not None else (
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
        category=review_item.category,
        before_text=review_item.original_text,
    )


def _manual_review_item(
    *,
    contract_id: UUID,
    clause: DocumentClauseForAdjustment,
    request_text: str,
) -> ManualReviewItemRecord:
    item_id = uuid5(
        NAMESPACE_URL,
        f"dandi://contracts/{contract_id}/document-clauses/{clause.id}/adjustment",
    )
    return ManualReviewItemRecord(
        id=item_id,
        document_clause_id=clause.id,
        analysis_task_id=clause.analysis_task_id,
        contract_id=contract_id,
        document_id=clause.document_id,
        source_page=clause.source_page,
        source_text=clause.source_text,
        source_confidence=clause.source_confidence,
        request_text=request_text.strip(),
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


def _response_from_record(response: AdjustmentResponseRecord) -> AdjustmentResponseItem:
    return AdjustmentResponseItem(
        review_item_id=response.review_item_id,
        decision=response.decision,
        counter_text=response.counter_text,
        reason=response.reason,
    )
