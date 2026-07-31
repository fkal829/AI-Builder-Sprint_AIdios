from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.adapters.base import ParsedDocument, ParsedPage
from app.adapters.solar import (
    SOLAR_CHAT_PATH,
    SOLAR_PROMPT_VERSION,
    SolarReviewAdapter,
)
from app.core.config import get_settings
from app.core.enums import ExtractedField, ExtractedSourceType, ReviewSignalType
from app.schemas.analysis import ExtractedTerm, SolarReviewInput, SolarReviewOutput
from app.schemas.understood_terms import UnderstoodTerm
from app.services.analysis import (
    _build_review_items,
    _build_solar_review_inputs,
    _verify_candidate_evidence,
)
from evaluation.runner import EvaluationCase, _stable_uuid, load_cases


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveSolarTarget(StrictModel):
    case_id: str
    field: ExtractedField
    signal: ReviewSignalType


class LiveSolarItemResult(StrictModel):
    case_id: str
    category: str
    field: ExtractedField
    signal: ReviewSignalType
    output: SolarReviewOutput


class LiveSolarReport(StrictModel):
    mode: str = "LIVE_SOLAR_REVIEW"
    executed_at: datetime
    endpoint_path: str
    request_model: str
    prompt_version: str
    request_count: int = Field(ge=1)
    item_count: int = Field(ge=1)
    schema_valid: bool
    easy_explanations_generated: bool
    three_distinct_suggestions_generated: bool
    items: list[LiveSolarItemResult] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_summary(self) -> LiveSolarReport:
        if self.item_count != len(self.items):
            raise ValueError("Solar live 결과 개수와 item_count가 일치해야 합니다.")
        if not (
            self.schema_valid
            and self.easy_explanations_generated
            and self.three_distinct_suggestions_generated
        ):
            raise ValueError("Solar live 결과가 필수 문구 검증을 통과하지 못했습니다.")
        return self


LIVE_SOLAR_TARGETS = (
    LiveSolarTarget(
        case_id="01-period-total-mismatch",
        field=ExtractedField.CONTRACT_TOTAL_AMOUNT,
        signal=ReviewSignalType.MISMATCH,
    ),
    LiveSolarTarget(
        case_id="04-ambiguous-deliverables",
        field=ExtractedField.CONTENT_QUANTITY,
        signal=ReviewSignalType.UNCLEAR,
    ),
    LiveSolarTarget(
        case_id="07-shooting-safety-liability",
        field=ExtractedField.SHOOTING_SAFETY,
        signal=ReviewSignalType.NEEDS_CHECK,
    ),
)


def build_live_solar_inputs(
    cases: list[EvaluationCase],
) -> list[tuple[LiveSolarTarget, str, SolarReviewInput]]:
    cases_by_id = {case.case_id: case for case in cases}
    selected: list[tuple[LiveSolarTarget, str, SolarReviewInput]] = []

    for target in LIVE_SOLAR_TARGETS:
        case = cases_by_id.get(target.case_id)
        if case is None:
            raise ValueError(f"Solar live 평가 fixture를 찾을 수 없습니다: {target.case_id}")

        contract_id = _stable_uuid(case.case_id, "contract")
        document_id = _stable_uuid(case.case_id, "document")
        parsed = ParsedDocument(
            pages=tuple(
                ParsedPage(number=page.page, text=page.text) for page in case.contract_pages
            ),
            model="offline-evaluation-snapshot-v1",
        )
        terms = [
            ExtractedTerm(
                id=_stable_uuid(case.case_id, f"term:{observed.field.value}"),
                contract_id=contract_id,
                document_id=document_id,
                source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
                **_verify_candidate_evidence(observed.to_candidate(), parsed).model_dump(),
            )
            for observed in case.observed_terms
        ]
        understood = UnderstoodTerm(
            contract_id=contract_id,
            **case.understood_terms.model_dump(),
        )
        reviews = _build_review_items(
            contract_id=contract_id,
            terms=terms,
            understood=understood,
        )
        fields_by_term_id = {term.id: term.field for term in terms}
        matching_reviews = [
            review
            for review in reviews
            if review.type == target.signal
            and target.field
            in {fields_by_term_id[term_id] for term_id in review.related_extracted_term_ids}
        ]
        if len(matching_reviews) != 1:
            raise ValueError(
                "Solar live 평가 대상 검토 항목은 정확히 하나여야 합니다: "
                f"{target.case_id}/{target.field.value}/{target.signal.value}"
            )
        solar_inputs = _build_solar_review_inputs(
            reviews=matching_reviews,
            terms=terms,
            understood=understood,
            contract=None,
        )
        selected.append((target, case.category, solar_inputs[0]))

    return selected


async def run_live_solar_review(
    *,
    cases: list[EvaluationCase],
) -> LiveSolarReport:
    settings = get_settings()
    if not settings.upstage_api_key:
        raise ValueError("실제 호출에는 UPSTAGE_API_KEY가 필요합니다.")

    selected = build_live_solar_inputs(cases)
    inputs = [item for _, _, item in selected]
    adapter = SolarReviewAdapter(
        mode="live",
        api_key=settings.upstage_api_key,
        base_url=settings.upstage_base_url,
        timeout_seconds=settings.upstage_solar_timeout_seconds,
        model=settings.upstage_solar_model,
    )
    outputs = await adapter.generate_review_content(items=inputs)
    outputs_by_id = {output.review_item_id: output for output in outputs}
    items = [
        LiveSolarItemResult(
            case_id=target.case_id,
            category=category,
            field=target.field,
            signal=target.signal,
            output=outputs_by_id[solar_input.review_item_id],
        )
        for target, category, solar_input in selected
    ]
    easy_explanations_generated = all(item.output.plain_explanation.strip() for item in items)
    three_distinct_suggestions_generated = all(
        len(
            {
                item.output.suggestion_accept.strip(),
                item.output.suggestion_compromise.strip(),
                item.output.suggestion_request.strip(),
            }
        )
        == 3
        for item in items
    )
    return LiveSolarReport(
        executed_at=datetime.now(UTC),
        endpoint_path=SOLAR_CHAT_PATH,
        request_model=settings.upstage_solar_model,
        prompt_version=SOLAR_PROMPT_VERSION,
        request_count=(len(inputs) + adapter.review_chunk_size - 1) // adapter.review_chunk_size,
        item_count=len(items),
        schema_valid=True,
        easy_explanations_generated=bool(easy_explanations_generated),
        three_distinct_suggestions_generated=three_distinct_suggestions_generated,
        items=items,
    )


def safe_error_payload(error: Exception) -> dict[str, Any]:
    cause = error.__cause__
    status_code = None
    response = getattr(cause, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
    return {
        "mode": "LIVE_SOLAR_REVIEW",
        "status": "failed",
        "error_type": type(error).__name__,
        "cause_type": type(cause).__name__ if cause is not None else None,
        "http_status": status_code,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="가상 계약 3건으로 Solar 검토 문구를 실제 호출해 검증합니다."
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=None,
        help="평가 JSON 디렉터리. 생략하면 기본 고정 fixture를 사용합니다.",
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="실제 외부 API 호출과 비용 발생을 명시적으로 확인합니다.",
    )
    arguments = parser.parse_args(argv)
    if not arguments.confirm_live:
        parser.error("실제 호출에는 --confirm-live가 필요합니다.")

    cases = load_cases(arguments.fixtures) if arguments.fixtures else load_cases()
    try:
        report = asyncio.run(run_live_solar_review(cases=cases))
    except Exception as error:
        print(json.dumps(safe_error_payload(error), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
