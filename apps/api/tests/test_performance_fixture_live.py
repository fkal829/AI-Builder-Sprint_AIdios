from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.adapters.performance_metrics import PerformanceMetricEvidenceError
from app.core.enums import PerformanceMetricVerificationStatus
from evaluation.performance_fixture_live import (
    EXPECTATION_PATH,
    FixtureLiveFailure,
    load_fixture,
    main,
    safe_error_payload,
    verify_metrics,
)


def _candidate(*, value, status: str, page: int | None):
    return SimpleNamespace(
        value=value,
        verification_status=PerformanceMetricVerificationStatus(status),
        source_page=page,
        source_text=f"safe evidence page {page}" if page is not None else None,
    )


def _expected_payload():
    expectation = json.loads(EXPECTATION_PATH.read_text(encoding="utf-8"))
    candidates = {
        name: _candidate(
            value=expected["value"],
            status=expected["verification_status"],
            page=expected["source_page"],
        )
        for name, expected in expectation["expected_extraction"].items()
    }
    return expectation, SimpleNamespace(**candidates)


def test_cli_gate_prevents_fixture_or_settings_load_without_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden_load():
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr("evaluation.performance_fixture_live.load_fixture", forbidden_load)
    with pytest.raises(SystemExit) as captured:
        main([])

    assert captured.value.code == 2
    assert called is False


def test_fixture_loader_pins_exact_current_pdf_hash() -> None:
    content, expectation, path = load_fixture()

    assert path.name == "브릿지웨이브_2026-07_광고성과리포트.pdf"
    assert hashlib.sha256(content).hexdigest() == expectation["source_file_sha256"]
    assert expectation["prompt_version"] == "performance-report-metrics-v3"


def test_fixture_expectations_accept_four_verified_and_six_safe_unresolved() -> None:
    expectation, payload = _expected_payload()

    results, strict_count, unresolved_count = verify_metrics(payload, expectation)

    assert len(results) == 10
    assert strict_count == 4
    assert unresolved_count == 6
    assert all(result.expectation_satisfied for result in results)


@pytest.mark.parametrize("field", ["likes", "comments", "reach", "saves", "shares"])
def test_fixture_expectations_reject_unreviewed_table_or_platform_values(field: str) -> None:
    expectation, payload = _expected_payload()
    candidate = getattr(payload, field)
    candidate.value = expectation["expected_confirmation_payload"][field]
    candidate.verification_status = PerformanceMetricVerificationStatus.VERIFIED

    with pytest.raises(FixtureLiveFailure, match="live verification failed") as captured:
        verify_metrics(payload, expectation)

    assert captured.value.error_code == f"UNSAFE_{field.upper()}_CANDIDATE"


def test_fixture_expectations_reject_summed_or_invented_follower_total() -> None:
    expectation, payload = _expected_payload()
    payload.follower_net_change.value = 278
    payload.follower_net_change.verification_status = (
        PerformanceMetricVerificationStatus.VERIFIED
    )

    with pytest.raises(FixtureLiveFailure) as captured:
        verify_metrics(payload, expectation)

    assert captured.value.error_code == "UNSAFE_FOLLOWER_NET_CHANGE_CANDIDATE"


def test_safe_error_payload_redacts_external_exception_details() -> None:
    serialized = json.dumps(
        safe_error_payload(RuntimeError("api-key report text raw response")),
        ensure_ascii=False,
    )

    assert "api-key" not in serialized
    assert "report text" not in serialized
    assert "raw response" not in serialized
    assert "UNEXPECTED_ERROR" in serialized
    assert "RuntimeError" in serialized


def test_safe_error_payload_classifies_only_known_evidence_failure() -> None:
    cause = PerformanceMetricEvidenceError(
        metric_name="likes",
        error_code="SOURCE_EVIDENCE_NOT_ON_PAGE",
    )
    error = RuntimeError("private wrapper")
    error.__cause__ = cause

    payload = safe_error_payload(error)

    assert payload["cause_code"] == "SOURCE_EVIDENCE_NOT_ON_PAGE"
    assert payload["metric_key"] == "likes"
