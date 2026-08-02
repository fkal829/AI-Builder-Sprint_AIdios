import json
import logging
from pathlib import Path

import httpx
import pytest

from app.adapters.base import ParsedDocument, ParsedPage
from app.adapters.performance_metrics import (
    PERFORMANCE_METRIC_NAMES,
    PERFORMANCE_METRIC_OUTPUT_SCHEMA,
    PERFORMANCE_METRIC_PROMPT_VERSION,
    SolarPerformanceMetricMapper,
    SolarPerformanceMetricMapperError,
)
from app.adapters.solar import SOLAR_CHAT_PATH
from app.core.enums import PerformanceMetricVerificationStatus
from app.schemas.performance import PerformanceExtractedPayload

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "fixtures" / "evaluation" / "performance-metrics"


def load_fixture(name: str) -> tuple[ParsedDocument, PerformanceExtractedPayload]:
    raw = json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))
    parsed = ParsedDocument(
        pages=tuple(ParsedPage(number=page["page"], text=page["text"]) for page in raw["pages"]),
        model="fixture-document-parse-v1",
    )
    return parsed, PerformanceExtractedPayload.model_validate(raw["expected_payload"])


@pytest.mark.parametrize(
    "fixture_name",
    ["01-published-count-not-found.json", "02-explicit-zero.json"],
)
async def test_mock_fixture_mapping_is_network_free_and_preserves_null_zero(
    monkeypatch,
    fixture_name: str,
) -> None:
    def fail_network(**_kwargs):
        raise AssertionError("mock 성과 지표 매핑은 네트워크를 사용하면 안 됩니다.")

    monkeypatch.setattr(httpx, "AsyncClient", fail_network)
    parsed, expected = load_fixture(fixture_name)
    mapper = SolarPerformanceMetricMapper(
        mode="mock",
        api_key="",
        base_url="https://api.upstage.ai",
    )

    mapped = await mapper.map_metrics(parsed_document=parsed)

    assert mapped == expected
    published = mapped.published_content_count
    if fixture_name.startswith("01-"):
        assert published.value is None
        assert published.verification_status is PerformanceMetricVerificationStatus.NOT_FOUND
        assert mapped.shares.value is None
    else:
        assert published.value == 0
        assert published.verification_status is PerformanceMetricVerificationStatus.VERIFIED
        assert mapped.ad_spend.value is None
        assert mapped.clicks.value is None
        assert all(
            getattr(mapped, field).value == 0
            for field in PERFORMANCE_METRIC_NAMES
            if field not in {"ad_spend", "clicks"}
        )


def test_live_output_schema_requires_all_ten_strict_metric_candidates() -> None:
    schema = PERFORMANCE_METRIC_OUTPUT_SCHEMA

    assert schema["required"] == list(PERFORMANCE_METRIC_NAMES)
    assert schema["additionalProperties"] is False
    for name in PERFORMANCE_METRIC_NAMES:
        candidate = schema["properties"][name]
        assert candidate["additionalProperties"] is False
        assert set(candidate["required"]) == {
            "value",
            "source_page",
            "source_text",
            "confidence",
            "verification_status",
        }
    assert "minimum" not in schema["properties"]["follower_net_change"]["properties"]["value"]
    assert schema["properties"]["ad_spend"]["properties"]["value"]["minimum"] == 0
    assert schema["properties"]["clicks"]["properties"]["value"]["minimum"] == 0
    assert schema["properties"]["published_content_count"]["properties"]["value"]["minimum"] == 0


async def test_live_fake_transport_uses_strict_schema_and_logs_metadata_only(caplog) -> None:
    parsed, expected = load_fixture("02-explicit-zero.json")
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == SOLAR_CHAT_PATH
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "solar-pro3-test",
                "choices": [
                    {
                        "message": {
                            "content": expected.model_dump_json(),
                        }
                    }
                ],
            },
        )

    caplog.set_level(logging.INFO, logger="app.adapters.performance_metrics")
    mapper = SolarPerformanceMetricMapper(
        mode="live",
        api_key="private-test-key",
        base_url="https://api.upstage.ai",
        model="solar-pro3",
        transport=httpx.MockTransport(handler),
    )

    mapped = await mapper.map_metrics(parsed_document=parsed)

    assert mapped == expected
    assert len(calls) == 1
    body = calls[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == PERFORMANCE_METRIC_OUTPUT_SCHEMA
    assert PERFORMANCE_METRIC_PROMPT_VERSION in body["messages"][1]["content"]
    assert body["messages"][1]["content"].count("게시물 수: 0건") == 1

    log_text = caplog.text
    assert "solar_performance_metric_mapping_run" in log_text
    assert "model=solar-pro3" in log_text
    assert "solar-pro3-test" not in log_text
    assert "status=completed" in log_text
    assert "http_status=200" in log_text
    assert "page_count=1" in log_text
    assert "metric_count=10" in log_text
    assert "schema_valid=True" in log_text
    assert "private-test-key" not in log_text
    assert parsed.pages[0].text not in log_text
    assert expected.published_content_count.source_text not in log_text


async def test_mock_extracts_clicks_and_krw_ad_spend_with_grounded_units() -> None:
    parsed = ParsedDocument(
        pages=(
            ParsedPage(
                number=1,
                text="2026년 8월 광고 성과\n광고비: ₩12,345\n클릭 수: 25회",
            ),
        ),
        model="fixture-document-parse-v1",
    )
    mapper = SolarPerformanceMetricMapper(
        mode="mock",
        api_key="",
        base_url="https://api.upstage.ai",
    )

    mapped = await mapper.map_metrics(parsed_document=parsed)

    assert mapped.ad_spend.value == 12_345
    assert mapped.ad_spend.source_text == "광고비: ₩12,345"
    assert mapped.clicks.value == 25
    assert mapped.clicks.source_text == "클릭 수: 25회"


async def test_mock_treats_unitless_ad_spend_as_not_found() -> None:
    parsed = ParsedDocument(
        pages=(ParsedPage(number=1, text="광고비: 12,345"),),
        model="fixture-document-parse-v1",
    )
    mapper = SolarPerformanceMetricMapper(
        mode="mock",
        api_key="",
        base_url="https://api.upstage.ai",
    )

    mapped = await mapper.map_metrics(parsed_document=parsed)

    assert mapped.ad_spend.value is None
    assert mapped.ad_spend.verification_status is PerformanceMetricVerificationStatus.NOT_FOUND


async def test_live_retries_one_transient_failure_before_returning_valid_payload() -> None:
    parsed, expected = load_fixture("02-explicit-zero.json")
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(503, request=request, json={"error": "temporary"})
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "ignored-response-model",
                "choices": [{"message": {"content": expected.model_dump_json()}}],
            },
        )

    mapper = SolarPerformanceMetricMapper(
        mode="live",
        api_key="private-test-key",
        base_url="https://api.upstage.ai",
        retry_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    assert await mapper.map_metrics(parsed_document=parsed) == expected
    assert request_count == 2


async def test_live_rejects_a_number_taken_from_another_metric_label() -> None:
    parsed, expected = load_fixture("01-published-count-not-found.json")
    raw_output = expected.model_dump(mode="json")
    raw_output["likes"].update(
        {
            "value": expected.impressions.value,
            "source_page": 1,
            "source_text": parsed.pages[0].text,
            "confidence": 1.0,
            "verification_status": "VERIFIED",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "solar-pro3",
                "choices": [{"message": {"content": json.dumps(raw_output)}}],
            },
        )

    mapper = SolarPerformanceMetricMapper(
        mode="live",
        api_key="private-test-key",
        base_url="https://api.upstage.ai",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SolarPerformanceMetricMapperError):
        await mapper.map_metrics(parsed_document=parsed)


@pytest.mark.parametrize(
    "source_text",
    [
        "광고비: 42",
        "광고비: 42 USD",
        "ad spend: $42",
    ],
)
async def test_live_rejects_ad_spend_without_explicit_krw_evidence(
    source_text: str,
) -> None:
    parsed = ParsedDocument(
        pages=(ParsedPage(number=1, text=source_text),),
        model="fixture-document-parse-v1",
    )
    missing = {
        "value": None,
        "source_page": None,
        "source_text": None,
        "confidence": 0.0,
        "verification_status": "NOT_FOUND",
    }
    raw_output = {name: dict(missing) for name in PERFORMANCE_METRIC_NAMES}
    raw_output["ad_spend"] = {
        "value": 42,
        "source_page": 1,
        "source_text": source_text,
        "confidence": 1.0,
        "verification_status": "VERIFIED",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "solar-pro3",
                "choices": [{"message": {"content": json.dumps(raw_output)}}],
            },
        )

    mapper = SolarPerformanceMetricMapper(
        mode="live",
        api_key="private-test-key",
        base_url="https://api.upstage.ai",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SolarPerformanceMetricMapperError):
        await mapper.map_metrics(parsed_document=parsed)


@pytest.mark.parametrize(
    ("metric_name", "source_text"),
    [
        ("likes", "dislikes: 42"),
        ("reach", "outreach campaign: 42"),
        ("published_content_count", "reposts: 42"),
        ("reach", "미도달: 42"),
        ("comments", "댓글아님: 42"),
    ],
)
async def test_live_rejects_metric_labels_inside_other_words(
    metric_name: str,
    source_text: str,
) -> None:
    parsed = ParsedDocument(
        pages=(ParsedPage(number=1, text=source_text),),
        model="fixture-document-parse-v1",
    )
    missing = {
        "value": None,
        "source_page": None,
        "source_text": None,
        "confidence": 0.0,
        "verification_status": "NOT_FOUND",
    }
    raw_output = {name: dict(missing) for name in PERFORMANCE_METRIC_NAMES}
    raw_output[metric_name] = {
        "value": 42,
        "source_page": 1,
        "source_text": source_text,
        "confidence": 1.0,
        "verification_status": "VERIFIED",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "solar-pro3",
                "choices": [{"message": {"content": json.dumps(raw_output)}}],
            },
        )

    mapper = SolarPerformanceMetricMapper(
        mode="live",
        api_key="private-test-key",
        base_url="https://api.upstage.ai",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SolarPerformanceMetricMapperError):
        await mapper.map_metrics(parsed_document=parsed)


@pytest.mark.parametrize(
    ("metric_name", "value", "source_text"),
    [
        ("likes", 30, "좋아요 증가율: 30%"),
        ("likes", 30, "좋아요: 30%"),
        ("likes", 30, "likes: 30 %"),
        ("likes", 30, "좋아요: 30％"),
        ("likes", 30, "좋아요: 30퍼센트입니다"),
        ("likes", 30, "좋아요: 30원입니다"),
        ("saves", 30, "데이터 저장 기간: 30일"),
        ("impressions", 7, "광고 노출 기간: 7일"),
    ],
)
async def test_live_rejects_rate_or_duration_as_a_metric_count(
    metric_name: str,
    value: int,
    source_text: str,
) -> None:
    parsed = ParsedDocument(
        pages=(ParsedPage(number=1, text=source_text),),
        model="fixture-document-parse-v1",
    )
    missing = {
        "value": None,
        "source_page": None,
        "source_text": None,
        "confidence": 0.0,
        "verification_status": "NOT_FOUND",
    }
    raw_output = {name: dict(missing) for name in PERFORMANCE_METRIC_NAMES}
    raw_output[metric_name] = {
        "value": value,
        "source_page": 1,
        "source_text": source_text,
        "confidence": 1.0,
        "verification_status": "VERIFIED",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "solar-pro3",
                "choices": [{"message": {"content": json.dumps(raw_output)}}],
            },
        )

    mapper = SolarPerformanceMetricMapper(
        mode="live",
        api_key="private-test-key",
        base_url="https://api.upstage.ai",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SolarPerformanceMetricMapperError):
        await mapper.map_metrics(parsed_document=parsed)


@pytest.mark.parametrize("failure_kind", ["schema", "evidence", "value"])
async def test_live_rejects_invalid_payload_without_logging_raw_content(
    caplog,
    failure_kind: str,
) -> None:
    parsed, expected = load_fixture("02-explicit-zero.json")
    raw_output = expected.model_dump(mode="json")
    secret = "raw-response-must-not-appear-in-logs"
    if failure_kind == "schema":
        raw_output["unexpected"] = secret
    elif failure_kind == "evidence":
        raw_output["published_content_count"]["source_text"] = secret
    else:
        raw_output["published_content_count"]["value"] = 7

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "solar-pro3",
                "choices": [{"message": {"content": json.dumps(raw_output)}}],
            },
        )

    caplog.set_level(logging.INFO, logger="app.adapters.performance_metrics")
    mapper = SolarPerformanceMetricMapper(
        mode="live",
        api_key="private-test-key",
        base_url="https://api.upstage.ai",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SolarPerformanceMetricMapperError):
        await mapper.map_metrics(parsed_document=parsed)

    assert "status=failed" in caplog.text
    assert "schema_valid=False" in caplog.text
    assert secret not in caplog.text
    assert "private-test-key" not in caplog.text
    assert parsed.pages[0].text not in caplog.text
