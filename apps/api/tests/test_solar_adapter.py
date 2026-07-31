import json
from uuid import UUID

import httpx
import pytest

from app.adapters.solar import (
    COUNTERPROPOSAL_PROMPT_VERSION,
    SOLAR_CHAT_PATH,
    SOLAR_PROMPT_VERSION,
    SolarCounterproposalError,
    SolarReviewAdapter,
    SolarReviewError,
)
from app.core.enums import (
    ReviewSeverity,
    ReviewSignalType,
    VerificationStatus,
)
from app.schemas.adjustments import CounterproposalComparisonInput
from app.schemas.analysis import SolarReviewInput, SolarReviewOutput

FIRST_ID = UUID("10000000-0000-4000-8000-000000000001")
SECOND_ID = UUID("10000000-0000-4000-8000-000000000002")


class FakeAsyncClient:
    calls: list[tuple[str, dict]] = []
    init_kwargs: dict = {}
    responses: list[httpx.Response | Exception] = []

    def __init__(self, **kwargs) -> None:
        self.__class__.init_kwargs = kwargs

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, path: str, *, json: dict) -> httpx.Response:
        self.__class__.calls.append((path, json))
        response = self.__class__.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_input(
    *,
    item_id: UUID = FIRST_ID,
    label: str = "월 납부액",
    signal: ReviewSignalType = ReviewSignalType.MISMATCH,
) -> SolarReviewInput:
    return SolarReviewInput(
        review_item_id=item_id,
        signal=signal,
        severity=ReviewSeverity.IMPORTANT,
        verification_status=VerificationStatus.VERIFIED,
        field_labels=[label],
        deterministic_explanation=f"사용자가 이해한 {label}과 계약 원문이 다릅니다.",
        contract_values=[f"{label}: 500000"],
        user_understanding=f"사용자가 이해한 {label}: 400000",
        source_excerpt=f"{label}은 500000원이다.",
    )


def make_output(
    *,
    item_id: UUID = FIRST_ID,
    plain_explanation: str = "월 납부액 400000원과 500000원이 다르므로 확인이 필요합니다.",
) -> dict:
    return {
        "review_item_id": str(item_id),
        "plain_explanation": plain_explanation,
        "suggestion_accept": "계약 원문의 월 납부액 500000원을 수용합니다.",
        "suggestion_compromise": "월 납부액 차이를 확인하고 조정합니다.",
        "suggestion_request": "합의한 월 납부액을 계약서에 적어 달라고 요청합니다.",
        "self_reported_confidence": 0.84,
        "model_limitations": "제공된 일부 원문만 반영했으므로 당사자 확인이 필요합니다.",
    }


def make_counterproposal_input(
    *,
    item_id: UUID = FIRST_ID,
    request_text: str = "위약금 20% 조항을 삭제해 주세요.",
    counter_text: str = "위약금을 10%로 낮추고 월 보고서를 제공하겠습니다.",
    reason: str = "이미 집행한 제작비를 고려해야 합니다.",
) -> CounterproposalComparisonInput:
    return CounterproposalComparisonInput(
        review_item_id=item_id,
        request_text=request_text,
        counter_text=counter_text,
        reason=reason,
    )


def make_counterproposal_output(
    *,
    item_id: UUID = FIRST_ID,
    changed_summary: str = "원 요청의 위약금 20% 삭제가 역제안의 위약금 10%로 변경되었습니다.",
) -> dict:
    return {
        "review_item_id": str(item_id),
        "changed_summary": changed_summary,
        "remaining_checks": [
            "월 보고서 제공 범위와 시점이 구체적인지 확인하세요.",
        ],
        "final_confirmation": "위약금 10%와 월 보고서 조건을 반영할지 최종 확인하세요.",
    }


def response_with_items(items: list[dict], *, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", f"https://api.upstage.ai{SOLAR_CHAT_PATH}")
    if status_code != 200:
        return httpx.Response(status_code, request=request, json={"error": {}})
    return httpx.Response(
        status_code,
        request=request,
        json={
            "model": "solar-pro3",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"items": items}, ensure_ascii=False),
                    }
                }
            ],
        },
    )


def test_safe_legal_disclaimer_is_allowed() -> None:
    payload = {
        **make_output(),
        "model_limitations": "이 설명은 법률 자문을 대체하지 않습니다.",
    }

    output = SolarReviewOutput.model_validate(payload)

    assert "대체하지 않습니다" in output.model_limitations


async def test_mock_generates_item_specific_copy_without_network(monkeypatch) -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("mock 모드는 네트워크를 호출하면 안 됩니다.")

    monkeypatch.setattr(httpx, "AsyncClient", fail_if_called)
    adapter = SolarReviewAdapter(
        mode="mock",
        api_key="",
        base_url="https://api.upstage.ai",
    )
    first = make_input()
    second = make_input(
        item_id=SECOND_ID,
        label="촬영 안전",
        signal=ReviewSignalType.MISSING,
    )

    outputs = await adapter.generate_review_content(items=[first, second])

    assert [output.review_item_id for output in outputs] == [FIRST_ID, SECOND_ID]
    assert outputs[0].plain_explanation != outputs[1].plain_explanation
    assert "월 납부액" in outputs[0].suggestion_request
    assert "촬영 안전" in outputs[1].suggestion_request
    assert "실제 Solar 응답이 아닙니다" in outputs[0].model_limitations


async def test_mock_compares_actual_counterproposal_without_network(monkeypatch) -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("mock 모드는 네트워크를 호출하면 안 됩니다.")

    monkeypatch.setattr(httpx, "AsyncClient", fail_if_called)
    adapter = SolarReviewAdapter(
        mode="mock",
        api_key="",
        base_url="https://api.upstage.ai",
    )
    first = make_counterproposal_input()
    second = make_counterproposal_input(
        item_id=SECOND_ID,
        request_text="계약기간을 1년으로 조정해 주세요.",
        counter_text="계약기간을 2년으로 조정하겠습니다.",
        reason="초기 촬영 비용 회수 기간이 필요합니다.",
    )

    outputs = await adapter.compare_counterproposals(items=[first, second])

    assert [output.review_item_id for output in outputs] == [FIRST_ID, SECOND_ID]
    assert "위약금 20%" in outputs[0].changed_summary
    assert "위약금을 10%" in outputs[0].changed_summary
    assert "계약기간을 1년" in outputs[1].changed_summary
    assert "계약기간을 2년" in outputs[1].changed_summary
    assert outputs[0].changed_summary != outputs[1].changed_summary
    assert "mock 모드" in outputs[0].final_confirmation


async def test_live_uses_current_chat_endpoint_and_strict_structured_output(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [response_with_items([make_output()])]
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = SolarReviewAdapter(
        mode="live",
        api_key="test-key",
        base_url="https://api.upstage.ai",
        timeout_seconds=45,
        model="solar-pro3",
    )

    outputs = await adapter.generate_review_content(items=[make_input()])

    path, body = FakeAsyncClient.calls[0]
    assert path == SOLAR_CHAT_PATH
    assert body["model"] == "solar-pro3"
    assert body["reasoning_effort"] == "medium"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert (
        body["response_format"]["json_schema"]["schema"]["additionalProperties"]
        is False
    )
    assert SOLAR_PROMPT_VERSION in body["messages"][1]["content"]
    assert FakeAsyncClient.init_kwargs["timeout"] == 45
    assert FakeAsyncClient.init_kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert outputs[0].self_reported_confidence == 0.84


async def test_live_counterproposal_uses_strict_structured_output(monkeypatch) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [
        response_with_items([make_counterproposal_output()])
    ]
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = SolarReviewAdapter(
        mode="live",
        api_key="test-key",
        base_url="https://api.upstage.ai",
        timeout_seconds=45,
        model="solar-pro3",
    )

    outputs = await adapter.compare_counterproposals(
        items=[make_counterproposal_input()]
    )

    path, body = FakeAsyncClient.calls[0]
    assert path == SOLAR_CHAT_PATH
    assert body["model"] == "solar-pro3"
    assert body["temperature"] == 0.2
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["name"] == "counterproposal_comparison"
    assert COUNTERPROPOSAL_PROMPT_VERSION in body["messages"][1]["content"]
    assert "위약금 20%" in outputs[0].changed_summary
    assert outputs[0].remaining_checks


@pytest.mark.parametrize(
    "invalid_output",
    [
        make_counterproposal_output(item_id=SECOND_ID),
        make_counterproposal_output(
            changed_summary="입력에 없는 위약금 30% 조건으로 변경되었습니다."
        ),
        make_counterproposal_output(
            changed_summary="이 대행사는 사기 업체이므로 역제안을 거절해야 합니다."
        ),
        {**make_counterproposal_output(), "remaining_checks": []},
        {**make_counterproposal_output(), "unexpected": "field"},
    ],
)
async def test_live_counterproposal_rejects_invalid_or_ungrounded_output(
    monkeypatch,
    invalid_output: dict,
) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [response_with_items([invalid_output])]
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = SolarReviewAdapter(
        mode="live",
        api_key="test-key",
        base_url="https://api.upstage.ai",
        retry_delay_seconds=0,
    )

    with pytest.raises(SolarCounterproposalError):
        await adapter.compare_counterproposals(
            items=[make_counterproposal_input()]
        )


async def test_live_retries_transient_status_once(monkeypatch) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [
        response_with_items([], status_code=429),
        response_with_items([make_output()]),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = SolarReviewAdapter(
        mode="live",
        api_key="test-key",
        base_url="https://api.upstage.ai",
        retry_delay_seconds=0,
    )

    outputs = await adapter.generate_review_content(items=[make_input()])

    assert len(FakeAsyncClient.calls) == 2
    assert outputs[0].review_item_id == FIRST_ID


async def test_live_timeout_after_retry_maps_to_solar_review_error(monkeypatch) -> None:
    FakeAsyncClient.calls = []
    request = httpx.Request("POST", f"https://api.upstage.ai{SOLAR_CHAT_PATH}")
    FakeAsyncClient.responses = [
        httpx.ReadTimeout("timed out", request=request),
        httpx.ReadTimeout("timed out", request=request),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = SolarReviewAdapter(
        mode="live",
        api_key="test-key",
        base_url="https://api.upstage.ai",
        retry_delay_seconds=0,
    )

    with pytest.raises(SolarReviewError):
        await adapter.generate_review_content(items=[make_input()])

    assert len(FakeAsyncClient.calls) == 2


async def test_live_rejects_malformed_json_content(monkeypatch) -> None:
    FakeAsyncClient.calls = []
    request = httpx.Request("POST", f"https://api.upstage.ai{SOLAR_CHAT_PATH}")
    FakeAsyncClient.responses = [
        httpx.Response(
            200,
            request=request,
            json={
                "model": "solar-pro3",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"items": [',
                        }
                    }
                ],
            },
        )
    ]
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = SolarReviewAdapter(
        mode="live",
        api_key="test-key",
        base_url="https://api.upstage.ai",
        retry_delay_seconds=0,
    )

    with pytest.raises(SolarReviewError):
        await adapter.generate_review_content(items=[make_input()])

    assert len(FakeAsyncClient.calls) == 1


@pytest.mark.parametrize(
    "invalid_output",
    [
        make_output(item_id=SECOND_ID),
        make_output(plain_explanation="이 업체는 사기 업체이므로 계약하면 안 됩니다."),
        make_output(plain_explanation="이곳은 사기업체입니다."),
        make_output(plain_explanation="이 계약은 불법 계약입니다."),
        make_output(plain_explanation="이 조건이면 승소할 가능성이 높습니다."),
        make_output(plain_explanation="이 설명이 법률 자문을 완전히 대체합니다."),
        make_output(
            plain_explanation="월 납부액 외에 위약금 300000원을 추가해야 합니다."
        ),
        {**make_output(), "model_limitations": " "},
        {**make_output(), "self_reported_confidence": "0.84"},
        {**make_output(), "self_reported_confidence": True},
    ],
)
async def test_live_rejects_mismatched_unsafe_or_ungrounded_output(
    monkeypatch,
    invalid_output: dict,
) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [response_with_items([invalid_output])]
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = SolarReviewAdapter(
        mode="live",
        api_key="test-key",
        base_url="https://api.upstage.ai",
        retry_delay_seconds=0,
    )

    with pytest.raises(SolarReviewError):
        await adapter.generate_review_content(items=[make_input()])
