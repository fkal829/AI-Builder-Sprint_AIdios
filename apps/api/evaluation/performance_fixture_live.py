"""Explicit live Upstage verification for the current fictitious report fixture.

The runner sends the exact repository PDF to the production Document Parse and
Solar metric-mapping adapters. Output is deliberately limited to hashes, model
metadata, counts, and per-field status; parsed text and raw responses are never
printed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.adapters.performance_metrics import (
    PERFORMANCE_METRIC_NAMES,
    PERFORMANCE_METRIC_PROMPT_VERSION,
    PerformanceMetricEvidenceError,
    SolarPerformanceMetricMapper,
)
from app.adapters.upstage import UpstageAdapter
from app.core.config import get_settings
from app.core.enums import PerformanceMetricVerificationStatus
from app.schemas.performance import PerformanceExtractedPayload

MODE = "LIVE_CURRENT_PERFORMANCE_REPORT"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXPECTATION_PATH = (
    REPOSITORY_ROOT / "fixtures" / "demo" / "performance-reports" / "expected-extraction.json"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveMetricResult(StrictModel):
    key: str
    verification_status: PerformanceMetricVerificationStatus
    value_present: bool
    source_page: int | None
    expectation_satisfied: Literal[True] = True


class LiveFixtureReport(StrictModel):
    mode: Literal["LIVE_CURRENT_PERFORMANCE_REPORT"] = MODE
    status: Literal["passed"] = "passed"
    executed_at: datetime
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str
    parse_model: str = Field(min_length=1)
    solar_model: str = Field(min_length=1)
    page_count: int = Field(ge=1)
    expected_page_count: int = Field(ge=1)
    candidate_count: Literal[10] = 10
    strict_verified_count: Literal[4] = 4
    safe_unresolved_count: Literal[6] = 6
    evidence_attached_count: int = Field(ge=0, le=10)
    status_counts: dict[PerformanceMetricVerificationStatus, int]
    metrics: list[LiveMetricResult]

    @model_validator(mode="after")
    def validate_complete_result(self) -> LiveFixtureReport:
        if self.prompt_version != PERFORMANCE_METRIC_PROMPT_VERSION:
            raise ValueError("성과 지표 prompt 버전이 현재 코드와 다릅니다.")
        if self.page_count != self.expected_page_count:
            raise ValueError("Document Parse 페이지 수가 fixture 기대와 다릅니다.")
        if len(self.metrics) != self.candidate_count:
            raise ValueError("성과 지표 후보 개수가 기대와 다릅니다.")
        if sum(self.status_counts.values()) != self.candidate_count:
            raise ValueError("성과 지표 상태 집계가 기대와 다릅니다.")
        return self


class FixtureLiveFailure(RuntimeError):
    """Safe failure carrying no report text, credentials, or raw responses."""

    def __init__(self, error_code: str) -> None:
        super().__init__("current performance report live verification failed")
        self.error_code = error_code


def load_fixture() -> tuple[bytes, dict[str, Any], Path]:
    try:
        expectation = json.loads(EXPECTATION_PATH.read_text(encoding="utf-8"))
        upload = expectation["upload"]
        report_path = EXPECTATION_PATH.parent / upload["filename"]
        content = report_path.read_bytes()
        expected_hash = expectation["source_file_sha256"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FixtureLiveFailure("FIXTURE_LOAD_FAILED") from error

    if not content.startswith(b"%PDF-"):
        raise FixtureLiveFailure("FIXTURE_NOT_PDF")
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise FixtureLiveFailure("FIXTURE_HASH_MISMATCH")
    if expectation.get("prompt_version") != PERFORMANCE_METRIC_PROMPT_VERSION:
        raise FixtureLiveFailure("FIXTURE_PROMPT_VERSION_MISMATCH")
    if set(expectation.get("expected_extraction", {})) != set(PERFORMANCE_METRIC_NAMES):
        raise FixtureLiveFailure("FIXTURE_METRIC_SET_MISMATCH")
    return content, expectation, report_path


def verify_metrics(
    payload: PerformanceExtractedPayload,
    expectation: dict[str, Any],
) -> tuple[list[LiveMetricResult], int, int]:
    expected_candidates = expectation["expected_extraction"]
    results: list[LiveMetricResult] = []
    strict_verified_count = 0
    safe_unresolved_count = 0

    for name in PERFORMANCE_METRIC_NAMES:
        candidate = getattr(payload, name)
        expected = expected_candidates[name]
        expected_status = PerformanceMetricVerificationStatus(expected["verification_status"])

        if expected_status is PerformanceMetricVerificationStatus.VERIFIED:
            if (
                candidate.verification_status is not PerformanceMetricVerificationStatus.VERIFIED
                or candidate.value != expected["value"]
                or candidate.source_page != expected["source_page"]
                or not candidate.source_text
            ):
                raise FixtureLiveFailure(f"STRICT_{name.upper()}_MISMATCH")
            strict_verified_count += 1
        elif expected_status is PerformanceMetricVerificationStatus.NEEDS_CHECK:
            if (
                candidate.value is not None
                or candidate.verification_status
                not in {
                    PerformanceMetricVerificationStatus.NEEDS_CHECK,
                    PerformanceMetricVerificationStatus.NOT_FOUND,
                }
            ):
                raise FixtureLiveFailure(f"UNSAFE_{name.upper()}_CANDIDATE")
            safe_unresolved_count += 1
        elif (
            candidate.value is not None
            or candidate.verification_status is not PerformanceMetricVerificationStatus.NOT_FOUND
        ):
            raise FixtureLiveFailure(f"UNSAFE_{name.upper()}_CANDIDATE")
        else:
            safe_unresolved_count += 1

        results.append(
            LiveMetricResult(
                key=name,
                verification_status=candidate.verification_status,
                value_present=candidate.value is not None,
                source_page=candidate.source_page,
            )
        )

    return results, strict_verified_count, safe_unresolved_count


async def run_live_fixture() -> LiveFixtureReport:
    content, expectation, _report_path = load_fixture()
    settings = get_settings()
    if settings.upstage_mode != "live" or not settings.upstage_api_key:
        raise FixtureLiveFailure("UPSTAGE_LIVE_SETTINGS_REQUIRED")
    if len(content) > settings.document_max_size_bytes:
        raise FixtureLiveFailure("FIXTURE_SIZE_LIMIT_EXCEEDED")

    parser = UpstageAdapter(
        api_key=settings.upstage_api_key,
        base_url=settings.upstage_base_url,
        mode="live",
        parse_timeout_seconds=settings.upstage_parse_timeout_seconds,
        extract_timeout_seconds=settings.upstage_extract_timeout_seconds,
        extract_model=settings.upstage_extract_model,
    )
    mapper = SolarPerformanceMetricMapper(
        api_key=settings.upstage_api_key,
        base_url=settings.upstage_base_url,
        mode="live",
        timeout_seconds=settings.upstage_solar_timeout_seconds,
        model=settings.upstage_solar_model,
    )
    parsed = await parser.parse_document(content=content, content_type="application/pdf")
    mapped = await mapper.map_metrics(parsed_document=parsed)
    metrics, strict_verified_count, safe_unresolved_count = verify_metrics(mapped, expectation)
    status_counts = Counter(result.verification_status for result in metrics)

    return LiveFixtureReport(
        executed_at=datetime.now(UTC),
        source_sha256=hashlib.sha256(content).hexdigest(),
        prompt_version=PERFORMANCE_METRIC_PROMPT_VERSION,
        parse_model=parsed.model,
        solar_model=settings.upstage_solar_model,
        page_count=len(parsed.pages),
        expected_page_count=expectation["upload"]["page_count"],
        strict_verified_count=strict_verified_count,
        safe_unresolved_count=safe_unresolved_count,
        evidence_attached_count=sum(result.source_page is not None for result in metrics),
        status_counts=dict(status_counts),
        metrics=metrics,
    )


def safe_error_payload(error: Exception) -> dict[str, Any]:
    cause = error.__cause__
    response = getattr(cause, "response", None)
    http_status = getattr(response, "status_code", None)
    return {
        "mode": MODE,
        "status": "failed",
        "error_code": (
            error.error_code if isinstance(error, FixtureLiveFailure) else "UNEXPECTED_ERROR"
        ),
        "error_type": type(error).__name__,
        "cause_type": type(cause).__name__ if cause is not None else None,
        "cause_code": (
            cause.error_code if isinstance(cause, PerformanceMetricEvidenceError) else None
        ),
        "metric_key": (
            cause.metric_name if isinstance(cause, PerformanceMetricEvidenceError) else None
        ),
        "http_status": http_status if isinstance(http_status, int) else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="현재 가상 광고성과 PDF를 실제 Upstage Parse·Solar로 검증합니다."
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="정확한 repo fixture의 실제 Upstage 호출과 AI 비용을 명시적으로 확인합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not arguments.confirm_live:
        parser.error("실제 호출에는 --confirm-live가 필요합니다.")
    try:
        report = asyncio.run(run_live_fixture())
    except Exception as error:
        print(json.dumps(safe_error_payload(error), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
