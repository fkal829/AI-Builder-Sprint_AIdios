from collections.abc import Sequence
from uuid import UUID

from app.adapters.base import CounterproposalComparisonAdapter
from app.adapters.solar import SolarCounterproposalError
from app.core.enums import AdjustmentResponseDecision
from app.core.exceptions import CounterproposalComparisonUnavailable
from app.repositories.adjustments import (
    AdjustmentRequestItemRecord,
    AdjustmentResponseRecord,
)
from app.schemas.adjustments import (
    CounterproposalComparison,
    CounterproposalComparisonInput,
    GeneratedCounterproposalComparison,
)

COUNTERPROPOSAL_BATCH_SIZE = 4


class CounterproposalComparator:
    """Compare persisted agency responses with the owner's actual request copy."""

    def __init__(self, adapter: CounterproposalComparisonAdapter) -> None:
        self._adapter = adapter

    async def compare(
        self,
        *,
        request_items: Sequence[AdjustmentRequestItemRecord],
        responses: Sequence[AdjustmentResponseRecord],
    ) -> list[CounterproposalComparison]:
        requests_by_id = {item.review_item_id: item for item in request_items}
        if len(requests_by_id) != len(request_items):
            raise ValueError("조정 요청 항목 ID는 중복될 수 없습니다.")

        response_ids = [response.review_item_id for response in responses]
        if len(response_ids) != len(set(response_ids)):
            raise ValueError("대행사 응답 항목 ID는 중복될 수 없습니다.")
        if not set(response_ids).issubset(requests_by_id):
            raise ValueError("대행사 응답이 조정 요청 항목과 일치하지 않습니다.")

        counter_inputs = [
            _counter_input(requests_by_id[response.review_item_id], response)
            for response in responses
            if response.decision == AdjustmentResponseDecision.COUNTER
        ]
        generated_by_id = await self._generated_comparisons(counter_inputs)

        comparisons: list[CounterproposalComparison] = []
        for response in responses:
            if response.decision == AdjustmentResponseDecision.ACCEPT:
                comparisons.append(_accepted_comparison(response.review_item_id))
            elif response.decision == AdjustmentResponseDecision.REJECT:
                comparisons.append(_rejected_comparison(response.review_item_id))
            else:
                generated = generated_by_id[response.review_item_id]
                comparisons.append(
                    CounterproposalComparison(
                        review_item_id=generated.review_item_id,
                        changed_summary=generated.changed_summary,
                        remaining_checks=generated.remaining_checks,
                        final_confirmation=generated.final_confirmation,
                    )
                )
        return comparisons

    async def _generated_comparisons(
        self,
        items: list[CounterproposalComparisonInput],
    ) -> dict[UUID, GeneratedCounterproposalComparison]:
        if not items:
            return {}
        try:
            generated = []
            for start in range(0, len(items), COUNTERPROPOSAL_BATCH_SIZE):
                generated.extend(
                    await self._adapter.compare_counterproposals(
                        items=items[start : start + COUNTERPROPOSAL_BATCH_SIZE]
                    )
                )
        except SolarCounterproposalError as error:
            raise CounterproposalComparisonUnavailable() from error

        generated_by_id = {item.review_item_id: item for item in generated}
        requested_ids = {item.review_item_id for item in items}
        if len(generated_by_id) != len(generated) or set(generated_by_id) != requested_ids:
            raise CounterproposalComparisonUnavailable()
        return generated_by_id


def _counter_input(
    request: AdjustmentRequestItemRecord,
    response: AdjustmentResponseRecord,
) -> CounterproposalComparisonInput:
    if not _has_text(response.counter_text) or not _has_text(response.reason):
        raise ValueError("COUNTER 응답에는 역제안 문구와 사유가 필요합니다.")
    return CounterproposalComparisonInput(
        review_item_id=response.review_item_id,
        request_text=request.request_text,
        counter_text=response.counter_text,
        reason=response.reason,
    )


def _accepted_comparison(review_item_id: UUID) -> CounterproposalComparison:
    return CounterproposalComparison(
        review_item_id=review_item_id,
        changed_summary="대행사가 요청 문구를 수락했습니다.",
        remaining_checks=[],
        final_confirmation="요청안을 최종 반영할 수 있습니다.",
    )


def _rejected_comparison(review_item_id: UUID) -> CounterproposalComparison:
    return CounterproposalComparison(
        review_item_id=review_item_id,
        changed_summary="대행사가 요청을 거절했습니다.",
        remaining_checks=["대행사가 입력한 거절 사유를 확인하세요."],
        final_confirmation="원안 유지 여부를 최종 확인하세요.",
    )


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())
