from types import SimpleNamespace
from uuid import UUID

import pytest

from app.adapters.solar import SOLAR_CHAT_PATH, SOLAR_PROMPT_VERSION
from app.core.enums import ExtractedField, ReviewSignalType
from app.schemas.analysis import SolarReviewOutput
from evaluation.runner import load_cases
from evaluation.solar_live import (
    LiveSolarItemResult,
    LiveSolarReport,
    build_live_solar_inputs,
    run_live_solar_review,
)


def test_builds_three_live_inputs_from_fixed_fictitious_cases() -> None:
    selected = build_live_solar_inputs(load_cases())

    assert [(target.field, target.signal) for target, _, _ in selected] == [
        (ExtractedField.CONTRACT_TOTAL_AMOUNT, ReviewSignalType.MISMATCH),
        (ExtractedField.CONTENT_QUANTITY, ReviewSignalType.UNCLEAR),
        (ExtractedField.SHOOTING_SAFETY, ReviewSignalType.NEEDS_CHECK),
    ]
    assert all(item.source_excerpt for _, _, item in selected)
    assert len({item.review_item_id for _, _, item in selected}) == 3


def test_live_report_requires_easy_explanation_and_three_distinct_suggestions() -> None:
    selected = build_live_solar_inputs(load_cases())
    target, category, solar_input = selected[0]
    output = SolarReviewOutput(
        review_item_id=solar_input.review_item_id,
        plain_explanation="계약 총액이 이해한 내용과 달라 직접 확인해야 합니다.",
        suggestion_accept="계약 원문의 총액을 그대로 수용합니다.",
        suggestion_compromise="총액 차이를 확인하고 조정 범위를 협의합니다.",
        suggestion_request="합의한 총액을 계약서에 명시해 달라고 요청합니다.",
        self_reported_confidence=0.8,
        model_limitations="제공된 가상 계약 일부만 반영했습니다.",
    )

    report = LiveSolarReport(
        executed_at="2026-07-31T00:00:00Z",
        endpoint_path=SOLAR_CHAT_PATH,
        request_model="solar-pro3",
        prompt_version=SOLAR_PROMPT_VERSION,
        request_count=1,
        item_count=1,
        schema_valid=True,
        easy_explanations_generated=True,
        three_distinct_suggestions_generated=True,
        items=[
            LiveSolarItemResult(
                case_id=target.case_id,
                category=category,
                field=target.field,
                signal=target.signal,
                output=output,
            )
        ],
    )

    assert report.mode == "LIVE_SOLAR_REVIEW"
    assert report.items[0].output.review_item_id == UUID(str(solar_input.review_item_id))


@pytest.mark.parametrize(
    (
        "schema_valid",
        "easy_explanations_generated",
        "three_distinct_suggestions_generated",
    ),
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ],
)
def test_live_report_rejects_failed_validation_summary(
    schema_valid: bool,
    easy_explanations_generated: bool,
    three_distinct_suggestions_generated: bool,
) -> None:
    with pytest.raises(ValueError):
        LiveSolarReport(
            executed_at="2026-07-31T00:00:00Z",
            endpoint_path=SOLAR_CHAT_PATH,
            request_model="solar-pro3",
            prompt_version=SOLAR_PROMPT_VERSION,
            request_count=1,
            item_count=1,
            schema_valid=schema_valid,
            easy_explanations_generated=easy_explanations_generated,
            three_distinct_suggestions_generated=three_distinct_suggestions_generated,
            items=[],
        )


async def test_live_runner_uses_same_chunked_adapter_boundary_as_production(
    monkeypatch,
) -> None:
    adapter_calls = []
    fake_settings = SimpleNamespace(
        upstage_api_key="test-key",
        upstage_base_url="https://api.upstage.ai",
        upstage_solar_timeout_seconds=120,
        upstage_solar_model="solar-pro3",
    )

    class FakeSolarReviewAdapter:
        review_chunk_size = 1

        def __init__(self, **_kwargs) -> None:
            pass

        async def generate_review_content(self, *, items):
            adapter_calls.append([item.review_item_id for item in items])
            return [
                SolarReviewOutput(
                    review_item_id=item.review_item_id,
                    plain_explanation="입력된 계약 조건을 직접 확인해야 합니다.",
                    suggestion_accept="현재 계약 문구를 그대로 수용합니다.",
                    suggestion_compromise="확인할 조건의 범위를 협의해 조정합니다.",
                    suggestion_request="확인할 조건을 계약서에 명확히 적어 달라고 요청합니다.",
                    self_reported_confidence=0.8,
                    model_limitations="제공된 가상 계약 일부만 반영했습니다.",
                )
                for item in items
            ]

    monkeypatch.setattr(
        "evaluation.solar_live.get_settings",
        lambda: fake_settings,
    )
    monkeypatch.setattr(
        "evaluation.solar_live.SolarReviewAdapter",
        FakeSolarReviewAdapter,
    )

    report = await run_live_solar_review(cases=load_cases())

    assert len(adapter_calls) == 1
    assert len(adapter_calls[0]) == 3
    assert report.request_count == 3
    assert report.item_count == 3
