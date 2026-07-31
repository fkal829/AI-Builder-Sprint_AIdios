from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.adapters.solar import (
    COUNTERPROPOSAL_PROMPT_VERSION,
    SOLAR_CHAT_PATH,
    SolarReviewAdapter,
)
from app.core.config import get_settings
from app.schemas.adjustments import (
    CounterproposalComparisonInput,
    GeneratedCounterproposalComparison,
)

LIVE_COUNTERPROPOSAL_INPUT = CounterproposalComparisonInput(
    review_item_id=UUID("20000000-0000-4000-8000-000000000001"),
    request_text="중도 해지 위약금 20% 조항을 삭제해 주세요.",
    counter_text="중도 해지 위약금을 10%로 낮추겠습니다.",
    reason="이미 집행한 제작비를 반영해야 합니다.",
)


class LiveCounterproposalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "LIVE_COUNTERPROPOSAL_COMPARISON"
    executed_at: datetime
    endpoint_path: str
    request_model: str
    prompt_version: str
    request_count: int
    item_count: int
    schema_valid: bool
    changed_summary_generated: bool
    remaining_checks_generated: bool
    final_confirmation_generated: bool
    output: GeneratedCounterproposalComparison

    @model_validator(mode="after")
    def validate_result(self) -> LiveCounterproposalReport:
        if self.request_count != 1 or self.item_count != 1:
            raise ValueError("역제안 live 검증은 고정 입력 한 건을 한 번 호출해야 합니다.")
        if self.output.review_item_id != LIVE_COUNTERPROPOSAL_INPUT.review_item_id:
            raise ValueError("역제안 live 출력 ID가 고정 입력과 일치하지 않습니다.")
        if not all(
            (
                self.schema_valid,
                self.changed_summary_generated,
                self.remaining_checks_generated,
                self.final_confirmation_generated,
            )
        ):
            raise ValueError("역제안 live 결과가 필수 검증을 통과하지 못했습니다.")
        return self


async def run_live_counterproposal_comparison() -> LiveCounterproposalReport:
    settings = get_settings()
    if not settings.upstage_api_key:
        raise ValueError("실제 호출에는 UPSTAGE_API_KEY가 필요합니다.")

    adapter = SolarReviewAdapter(
        mode="live",
        api_key=settings.upstage_api_key,
        base_url=settings.upstage_base_url,
        timeout_seconds=settings.upstage_solar_timeout_seconds,
        model=settings.upstage_solar_model,
    )
    outputs = await adapter.compare_counterproposals(
        items=[LIVE_COUNTERPROPOSAL_INPUT],
    )
    if len(outputs) != 1:
        raise ValueError("역제안 live 결과는 정확히 한 건이어야 합니다.")
    output = outputs[0]
    return LiveCounterproposalReport(
        executed_at=datetime.now(UTC),
        endpoint_path=SOLAR_CHAT_PATH,
        request_model=settings.upstage_solar_model,
        prompt_version=COUNTERPROPOSAL_PROMPT_VERSION,
        request_count=1,
        item_count=1,
        schema_valid=True,
        changed_summary_generated=bool(output.changed_summary.strip()),
        remaining_checks_generated=bool(
            output.remaining_checks and all(item.strip() for item in output.remaining_checks)
        ),
        final_confirmation_generated=bool(output.final_confirmation.strip()),
        output=output,
    )


def safe_error_payload(error: Exception) -> dict[str, Any]:
    cause = error.__cause__
    response = getattr(cause, "response", None)
    status_code = getattr(response, "status_code", None)
    return {
        "mode": "LIVE_COUNTERPROPOSAL_COMPARISON",
        "status": "failed",
        "error_type": type(error).__name__,
        "cause_type": type(cause).__name__ if cause is not None else None,
        "http_status": status_code if isinstance(status_code, int) else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="가상 역제안 한 건으로 Solar 비교 문구를 실제 호출해 검증합니다."
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="실제 외부 API 호출과 비용 발생을 명시적으로 확인합니다.",
    )
    arguments = parser.parse_args(argv)
    if not arguments.confirm_live:
        parser.error("실제 호출에는 --confirm-live가 필요합니다.")

    try:
        report = asyncio.run(run_live_counterproposal_comparison())
    except Exception as error:
        print(json.dumps(safe_error_payload(error), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
