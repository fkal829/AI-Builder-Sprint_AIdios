import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.runner import (
    EvaluationCase,
    evaluate_cases,
    load_cases,
    render_markdown_report,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "fixtures" / "evaluation" / "cases"
RESULTS_PATH = REPOSITORY_ROOT / "fixtures" / "evaluation" / "RESULTS.md"
EXPECTED_CATEGORIES = [
    "기간·총액 불일치",
    "환불 설명 누락",
    "자동갱신",
    "모호한 산출물",
    "빈칸 다수",
    "위약금 조건",
    "촬영 안전·손해 책임",
    "콘텐츠 권리",
    "정상 계약",
    "낮은 OCR 품질",
]


def test_loads_ten_unique_schema_valid_evaluation_cases() -> None:
    cases = load_cases(FIXTURE_DIRECTORY)

    assert len(cases) == 10
    assert [case.category for case in cases] == EXPECTED_CATEGORIES
    assert len({case.case_id for case in cases}) == 10
    assert all(len(case.contract_pages) >= 1 for case in cases)
    assert all(len(case.observed_terms) == len(case.expected_terms) for case in cases)


def test_offline_evaluation_meets_declared_targets_without_network(
    monkeypatch,
) -> None:
    def fail_network(*_args, **_kwargs):
        raise AssertionError("오프라인 고정 평가는 네트워크를 사용하면 안 됩니다.")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    report = evaluate_cases(load_cases(FIXTURE_DIRECTORY))

    assert report.mode == "OFFLINE_SNAPSHOT"
    assert report.case_count == 10
    assert report.schema_success_rate == 100.0
    assert report.extraction_accuracy == 96.67
    assert report.evidence_page_accuracy == 96.36
    assert report.mismatch_detection_rate == 100.0
    assert report.expected_signal_recall == 100.0
    assert report.unsupported_confirmed_warning_count == 0
    assert report.meets_all_targets is True


def test_fixture_schema_rejects_wrong_extracted_value_type() -> None:
    path = FIXTURE_DIRECTORY / "01-period-total-mismatch.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    monthly = next(
        term for term in payload["observed_terms"] if term["field"] == "monthly_amount"
    )
    monthly["value"] = "600000"

    with pytest.raises(ValidationError):
        EvaluationCase.model_validate(payload)


def test_checked_in_results_match_current_evaluation() -> None:
    report = evaluate_cases(load_cases(FIXTURE_DIRECTORY))

    assert RESULTS_PATH.read_text(encoding="utf-8") == render_markdown_report(report)
