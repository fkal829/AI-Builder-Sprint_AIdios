from uuid import UUID

import pytest

from app.adapters.solar import SolarCounterproposalError
from app.core.enums import (
    AdjustmentResponseDecision,
    SuggestionChoice,
)
from app.core.errors import ErrorCode
from app.core.exceptions import CounterproposalComparisonUnavailable
from app.repositories.adjustments import (
    AdjustmentRequestItemRecord,
    AdjustmentResponseRecord,
)
from app.schemas.adjustments import (
    CounterproposalComparisonInput,
    GeneratedCounterproposalComparison,
)
from app.services.counterproposal import CounterproposalComparator

ACCEPT_ID = UUID("20000000-0000-4000-8000-000000000001")
REJECT_ID = UUID("20000000-0000-4000-8000-000000000002")
COUNTER_ID = UUID("20000000-0000-4000-8000-000000000003")
OTHER_ID = UUID("20000000-0000-4000-8000-000000000004")


class RecordingComparisonAdapter:
    def __init__(
        self,
        outputs: list[GeneratedCounterproposalComparison] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.outputs = outputs or []
        self.error = error
        self.calls: list[list[CounterproposalComparisonInput]] = []

    async def compare_counterproposals(
        self,
        *,
        items: list[CounterproposalComparisonInput],
    ) -> list[GeneratedCounterproposalComparison]:
        self.calls.append(items)
        if self.error is not None:
            raise self.error
        return self.outputs


class EchoComparisonAdapter:
    def __init__(self) -> None:
        self.calls: list[list[CounterproposalComparisonInput]] = []

    async def compare_counterproposals(
        self,
        *,
        items: list[CounterproposalComparisonInput],
    ) -> list[GeneratedCounterproposalComparison]:
        self.calls.append(items)
        return [
            GeneratedCounterproposalComparison(
                review_item_id=item.review_item_id,
                changed_summary=f"{item.review_item_id}의 역제안을 비교했습니다.",
                remaining_checks=["변경 내용을 확인하세요."],
                final_confirmation="반영 여부를 최종 확인하세요.",
            )
            for item in reversed(items)
        ]


def request_item(item_id: UUID, text: str) -> AdjustmentRequestItemRecord:
    return AdjustmentRequestItemRecord(
        review_item_id=item_id,
        user_choice=SuggestionChoice.REQUEST,
        request_text=text,
    )


def response_item(
    item_id: UUID,
    decision: AdjustmentResponseDecision,
    *,
    counter_text: str | None = None,
    reason: str | None = None,
) -> AdjustmentResponseRecord:
    return AdjustmentResponseRecord(
        review_item_id=item_id,
        decision=decision,
        counter_text=counter_text,
        reason=reason,
    )


async def test_comparator_sends_actual_counterproposal_only_and_preserves_order() -> None:
    generated = GeneratedCounterproposalComparison(
        review_item_id=COUNTER_ID,
        changed_summary="계약기간 요청이 1년에서 2년으로 변경되었습니다.",
        remaining_checks=["2년 동안 같은 월 보고 범위가 유지되는지 확인하세요."],
        final_confirmation="계약기간 2년을 반영할지 최종 확인하세요.",
    )
    adapter = RecordingComparisonAdapter([generated])
    comparator = CounterproposalComparator(adapter)
    requests = (
        request_item(ACCEPT_ID, "월 보고서를 매월 제공해 주세요."),
        request_item(REJECT_ID, "위약금 조항을 삭제해 주세요."),
        request_item(COUNTER_ID, "계약기간을 1년으로 조정해 주세요."),
    )
    responses = (
        response_item(ACCEPT_ID, AdjustmentResponseDecision.ACCEPT),
        response_item(
            REJECT_ID,
            AdjustmentResponseDecision.REJECT,
            reason="제작비가 이미 집행되었습니다.",
        ),
        response_item(
            COUNTER_ID,
            AdjustmentResponseDecision.COUNTER,
            counter_text="계약기간을 2년으로 조정하겠습니다.",
            reason="초기 촬영 비용을 회수할 기간이 필요합니다.",
        ),
    )

    comparisons = await comparator.compare(
        request_items=requests,
        responses=responses,
    )

    assert [comparison.review_item_id for comparison in comparisons] == [
        ACCEPT_ID,
        REJECT_ID,
        COUNTER_ID,
    ]
    assert comparisons[0].remaining_checks == []
    assert "거절 사유" in comparisons[1].remaining_checks[0]
    assert comparisons[2].changed_summary == generated.changed_summary
    assert len(adapter.calls) == 1
    assert adapter.calls[0] == [
        CounterproposalComparisonInput(
            review_item_id=COUNTER_ID,
            request_text="계약기간을 1년으로 조정해 주세요.",
            counter_text="계약기간을 2년으로 조정하겠습니다.",
            reason="초기 촬영 비용을 회수할 기간이 필요합니다.",
        )
    ]


async def test_comparator_does_not_call_solar_without_counterproposal() -> None:
    adapter = RecordingComparisonAdapter()
    comparator = CounterproposalComparator(adapter)

    comparisons = await comparator.compare(
        request_items=(request_item(ACCEPT_ID, "요청 문구"),),
        responses=(
            response_item(ACCEPT_ID, AdjustmentResponseDecision.ACCEPT),
        ),
    )

    assert len(comparisons) == 1
    assert adapter.calls == []


async def test_comparator_chunks_more_than_four_counterproposals_and_preserves_order() -> None:
    item_ids = [UUID(int=index) for index in range(1, 7)]
    adapter = EchoComparisonAdapter()
    comparator = CounterproposalComparator(adapter)

    comparisons = await comparator.compare(
        request_items=tuple(
            request_item(item_id, f"{index}번 요청 문구")
            for index, item_id in enumerate(item_ids, start=1)
        ),
        responses=tuple(
            response_item(
                item_id,
                AdjustmentResponseDecision.COUNTER,
                counter_text=f"{index}번 역제안 문구",
                reason=f"{index}번 역제안 사유",
            )
            for index, item_id in enumerate(item_ids, start=1)
        ),
    )

    assert [[item.review_item_id for item in call] for call in adapter.calls] == [
        item_ids[:4],
        item_ids[4:],
    ]
    assert [comparison.review_item_id for comparison in comparisons] == item_ids


@pytest.mark.parametrize(
    "adapter",
    [
        RecordingComparisonAdapter(error=SolarCounterproposalError("invalid")),
        RecordingComparisonAdapter(
            outputs=[
                GeneratedCounterproposalComparison(
                    review_item_id=OTHER_ID,
                    changed_summary="다른 항목의 비교 결과입니다.",
                    remaining_checks=["항목 ID를 확인하세요."],
                    final_confirmation="항목을 확인하세요.",
                )
            ]
        ),
    ],
)
async def test_comparator_maps_solar_failure_or_mismatched_ids_to_stable_error(
    adapter: RecordingComparisonAdapter,
) -> None:
    comparator = CounterproposalComparator(adapter)

    with pytest.raises(CounterproposalComparisonUnavailable) as raised:
        await comparator.compare(
            request_items=(request_item(COUNTER_ID, "계약기간을 1년으로 조정해 주세요."),),
            responses=(
                response_item(
                    COUNTER_ID,
                    AdjustmentResponseDecision.COUNTER,
                    counter_text="계약기간을 2년으로 조정하겠습니다.",
                    reason="촬영 비용 회수 기간이 필요합니다.",
                ),
            ),
        )

    assert raised.value.status_code == 502
    assert raised.value.code == ErrorCode.ANALYSIS_SCHEMA_INVALID
