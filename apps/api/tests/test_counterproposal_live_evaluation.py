from types import SimpleNamespace

import pytest

from app.adapters.solar import COUNTERPROPOSAL_PROMPT_VERSION, SOLAR_CHAT_PATH
from app.schemas.adjustments import GeneratedCounterproposalComparison
from evaluation.counterproposal_live import (
    LIVE_COUNTERPROPOSAL_INPUT,
    LiveCounterproposalReport,
    run_live_counterproposal_comparison,
)


async def test_live_counterproposal_runner_uses_production_adapter_boundary(
    monkeypatch,
) -> None:
    calls = []
    fake_settings = SimpleNamespace(
        upstage_api_key="test-key",
        upstage_base_url="https://api.upstage.ai",
        upstage_solar_timeout_seconds=120,
        upstage_solar_model="solar-pro3",
    )

    class FakeSolarReviewAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        async def compare_counterproposals(self, *, items):
            calls.append(items)
            return [
                GeneratedCounterproposalComparison(
                    review_item_id=items[0].review_item_id,
                    changed_summary="위약금 20% 삭제 요청이 10% 역제안으로 변경됐습니다.",
                    remaining_checks=["10% 적용 범위와 시점을 확인하세요."],
                    final_confirmation="10% 역제안을 채택할지 사용자가 확인하세요.",
                )
            ]

    monkeypatch.setattr(
        "evaluation.counterproposal_live.get_settings",
        lambda: fake_settings,
    )
    monkeypatch.setattr(
        "evaluation.counterproposal_live.SolarReviewAdapter",
        FakeSolarReviewAdapter,
    )

    report = await run_live_counterproposal_comparison()

    assert calls == [[LIVE_COUNTERPROPOSAL_INPUT]]
    assert report.schema_valid is True
    assert report.changed_summary_generated is True
    assert report.remaining_checks_generated is True
    assert report.final_confirmation_generated is True


def test_live_counterproposal_report_rejects_wrong_output_id() -> None:
    output = GeneratedCounterproposalComparison(
        review_item_id="20000000-0000-4000-8000-000000000099",
        changed_summary="입력과 다른 테스트 출력입니다.",
        remaining_checks=["직접 확인하세요."],
        final_confirmation="사용자가 최종 확인하세요.",
    )

    with pytest.raises(ValueError, match="출력 ID"):
        LiveCounterproposalReport(
            executed_at="2026-07-31T00:00:00Z",
            endpoint_path=SOLAR_CHAT_PATH,
            request_model="solar-pro3",
            prompt_version=COUNTERPROPOSAL_PROMPT_VERSION,
            request_count=1,
            item_count=1,
            schema_valid=True,
            changed_summary_generated=True,
            remaining_checks_generated=True,
            final_confirmation_generated=True,
            output=output,
        )
