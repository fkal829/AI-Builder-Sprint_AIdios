import argparse
import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.adapters.base import ParsedDocument, ParsedPage
from app.core.enums import (
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
    ReviewSignalType,
    VerificationStatus,
)
from app.schemas.analysis import (
    EXPECTED_VALUE_TYPES,
    ExtractedTerm,
    ExtractedTermCandidate,
)
from app.schemas.understood_terms import UnderstoodTerm, UnderstoodTermInput
from app.services.analysis import _build_review_items, _verify_candidate_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE_DIRECTORY = REPOSITORY_ROOT / "fixtures" / "evaluation" / "cases"
EXTRACTION_ACCURACY_TARGET = 90.0
EVIDENCE_PAGE_ACCURACY_TARGET = 90.0
SCHEMA_SUCCESS_TARGET = 100.0
MISMATCH_DETECTION_TARGET = 100.0
EXPECTED_CASE_COUNT = 10


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationPage(StrictModel):
    page: int = Field(ge=1)
    text: str = Field(min_length=1)


class EvaluationTerm(StrictModel):
    field: ExtractedField
    value: Any = None
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = Field(default=None, min_length=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    verification_status: VerificationStatus = VerificationStatus.VERIFIED

    @model_validator(mode="after")
    def validate_as_extracted_candidate(self) -> "EvaluationTerm":
        self.to_candidate()
        return self

    def to_candidate(self) -> ExtractedTermCandidate:
        return ExtractedTermCandidate(
            field=self.field,
            value_type=EXPECTED_VALUE_TYPES.get(self.field, ExtractedValueType.TEXT),
            value=self.value,
            source_page=self.source_page,
            source_text=self.source_text,
            confidence=self.confidence,
            verification_status=self.verification_status,
        )


class ExpectedSignal(StrictModel):
    field: ExtractedField
    signal: ReviewSignalType


class EvaluationCase(StrictModel):
    case_id: str = Field(pattern=r"^\d{2}-[a-z0-9-]+$")
    category: str = Field(min_length=1)
    contract_pages: list[EvaluationPage] = Field(min_length=1)
    understood_terms: UnderstoodTermInput
    observed_terms: list[EvaluationTerm] = Field(min_length=1)
    expected_terms: list[EvaluationTerm] = Field(min_length=1)
    expected_signals: list[ExpectedSignal]
    mismatch_targets: list[ExtractedField]

    @model_validator(mode="after")
    def validate_fixture_consistency(self) -> "EvaluationCase":
        page_numbers = [page.page for page in self.contract_pages]
        if len(page_numbers) != len(set(page_numbers)):
            raise ValueError("계약 원문 페이지 번호는 중복될 수 없습니다.")
        if page_numbers != list(range(1, len(page_numbers) + 1)):
            raise ValueError("계약 원문 페이지는 1부터 연속되어야 합니다.")

        observed_fields = [term.field for term in self.observed_terms]
        expected_fields = [term.field for term in self.expected_terms]
        if len(observed_fields) != len(set(observed_fields)):
            raise ValueError("오프라인 추출 스냅샷의 필드는 중복될 수 없습니다.")
        if len(expected_fields) != len(set(expected_fields)):
            raise ValueError("사람이 검증한 정답 필드는 중복될 수 없습니다.")
        if set(observed_fields) != set(expected_fields):
            raise ValueError("오프라인 추출 스냅샷과 정답의 평가 필드가 일치해야 합니다.")

        signal_pairs = [(signal.field, signal.signal) for signal in self.expected_signals]
        if len(signal_pairs) != len(set(signal_pairs)):
            raise ValueError("기대 확인 신호는 중복될 수 없습니다.")
        expected_mismatches = {
            signal.field
            for signal in self.expected_signals
            if signal.signal == ReviewSignalType.MISMATCH
        }
        if not set(self.mismatch_targets).issubset(expected_mismatches):
            raise ValueError("불일치 평가 대상은 MISMATCH 기대 신호에 포함되어야 합니다.")

        page_text = {page.page: _normalize(page.text) for page in self.contract_pages}
        for term in self.expected_terms:
            if term.source_page is None:
                continue
            expected_page = page_text.get(term.source_page)
            if (
                expected_page is None
                or term.source_text is None
                or _normalize(term.source_text) not in expected_page
            ):
                raise ValueError("정답 원문 근거가 지정한 계약 페이지에 없습니다.")
        return self


class EvaluationReport(StrictModel):
    mode: str
    case_count: int
    schema_valid_cases: int
    schema_success_rate: float
    extraction_correct: int
    extraction_total: int
    extraction_accuracy: float
    evidence_page_correct: int
    evidence_page_total: int
    evidence_page_accuracy: float
    mismatch_detected: int
    mismatch_total: int
    mismatch_detection_rate: float
    expected_signals_detected: int
    expected_signals_total: int
    expected_signal_recall: float
    unsupported_confirmed_warning_count: int
    meets_all_targets: bool


def load_cases(directory: Path = DEFAULT_FIXTURE_DIRECTORY) -> list[EvaluationCase]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError(f"평가 fixture를 찾을 수 없습니다: {directory}")
    if len(paths) != EXPECTED_CASE_COUNT:
        raise ValueError(
            f"고정 평가는 정확히 {EXPECTED_CASE_COUNT}건이어야 합니다: {len(paths)}건"
        )
    cases = [
        EvaluationCase.model_validate_json(path.read_text(encoding="utf-8"))
        for path in paths
    ]
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("평가 case_id는 중복될 수 없습니다.")
    return cases


def evaluate_cases(cases: list[EvaluationCase]) -> EvaluationReport:
    extraction_correct = 0
    extraction_total = 0
    evidence_page_correct = 0
    evidence_page_total = 0
    mismatch_detected = 0
    mismatch_total = 0
    expected_signals_detected = 0
    expected_signals_total = 0
    unsupported_confirmed_warning_count = 0

    for case in cases:
        contract_id = _stable_uuid(case.case_id, "contract")
        document_id = _stable_uuid(case.case_id, "document")
        parsed = ParsedDocument(
            pages=tuple(
                ParsedPage(number=page.page, text=page.text)
                for page in case.contract_pages
            ),
            model="offline-evaluation-snapshot-v1",
        )
        observed_candidates = {
            term.field: _verify_candidate_evidence(term.to_candidate(), parsed)
            for term in case.observed_terms
        }
        expected_terms = {term.field: term for term in case.expected_terms}

        for field, expected in expected_terms.items():
            observed = observed_candidates[field]
            extraction_total += 1
            if observed.value == expected.value:
                extraction_correct += 1
            if expected.source_page is not None:
                evidence_page_total += 1
                if observed.source_page == expected.source_page:
                    evidence_page_correct += 1

        extracted_terms = [
            ExtractedTerm(
                id=_stable_uuid(case.case_id, f"term:{field.value}"),
                contract_id=contract_id,
                document_id=document_id,
                source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
                **candidate.model_dump(),
            )
            for field, candidate in observed_candidates.items()
        ]
        understood = UnderstoodTerm(
            contract_id=contract_id,
            **case.understood_terms.model_dump(),
        )
        reviews = _build_review_items(
            contract_id=contract_id,
            terms=extracted_terms,
            understood=understood,
        )
        fields_by_term_id = {term.id: term.field for term in extracted_terms}
        actual_signal_pairs = {
            (fields_by_term_id[term_id], review.type)
            for review in reviews
            for term_id in review.related_extracted_term_ids
        }

        expected_pairs = {
            (expected.field, expected.signal) for expected in case.expected_signals
        }
        expected_signals_total += len(expected_pairs)
        expected_signals_detected += len(expected_pairs & actual_signal_pairs)
        mismatch_total += len(case.mismatch_targets)
        mismatch_detected += sum(
            (field, ReviewSignalType.MISMATCH) in actual_signal_pairs
            for field in case.mismatch_targets
        )
        unsupported_confirmed_warning_count += sum(
            review.verification_status
            in {VerificationStatus.VERIFIED, VerificationStatus.NEEDS_CHECK}
            and (
                review.source_document_id is None
                or review.source_page is None
                or review.source_text is None
                or review.source_confidence is None
            )
            for review in reviews
        )

    schema_success_rate = _percentage(len(cases), len(cases))
    extraction_accuracy = _percentage(extraction_correct, extraction_total)
    evidence_page_accuracy = _percentage(evidence_page_correct, evidence_page_total)
    mismatch_detection_rate = _percentage(mismatch_detected, mismatch_total)
    expected_signal_recall = _percentage(
        expected_signals_detected,
        expected_signals_total,
    )
    meets_all_targets = (
        extraction_accuracy >= EXTRACTION_ACCURACY_TARGET
        and evidence_page_accuracy >= EVIDENCE_PAGE_ACCURACY_TARGET
        and schema_success_rate >= SCHEMA_SUCCESS_TARGET
        and mismatch_detection_rate >= MISMATCH_DETECTION_TARGET
        and unsupported_confirmed_warning_count == 0
    )
    return EvaluationReport(
        mode="OFFLINE_SNAPSHOT",
        case_count=len(cases),
        schema_valid_cases=len(cases),
        schema_success_rate=schema_success_rate,
        extraction_correct=extraction_correct,
        extraction_total=extraction_total,
        extraction_accuracy=extraction_accuracy,
        evidence_page_correct=evidence_page_correct,
        evidence_page_total=evidence_page_total,
        evidence_page_accuracy=evidence_page_accuracy,
        mismatch_detected=mismatch_detected,
        mismatch_total=mismatch_total,
        mismatch_detection_rate=mismatch_detection_rate,
        expected_signals_detected=expected_signals_detected,
        expected_signals_total=expected_signals_total,
        expected_signal_recall=expected_signal_recall,
        unsupported_confirmed_warning_count=unsupported_confirmed_warning_count,
        meets_all_targets=meets_all_targets,
    )


def render_markdown_report(report: EvaluationReport) -> str:
    target_text = "통과" if report.meets_all_targets else "미달"
    rows = "\n".join(
        (
            _metric_row(
                "핵심 필드 추출 정확도",
                (
                    f"{report.extraction_accuracy:.2f}% "
                    f"({report.extraction_correct}/{report.extraction_total})"
                ),
                "90% 이상",
                report.extraction_accuracy >= EXTRACTION_ACCURACY_TARGET,
            ),
            _metric_row(
                "근거 페이지 연결 정확도",
                (
                    f"{report.evidence_page_accuracy:.2f}% "
                    f"({report.evidence_page_correct}/{report.evidence_page_total})"
                ),
                "90% 이상",
                report.evidence_page_accuracy >= EVIDENCE_PAGE_ACCURACY_TARGET,
            ),
            _metric_row(
                "필수 JSON 스키마 성공률",
                (
                    f"{report.schema_success_rate:.2f}% "
                    f"({report.schema_valid_cases}/{report.case_count})"
                ),
                "100%",
                report.schema_success_rate >= SCHEMA_SUCCESS_TARGET,
            ),
            _metric_row(
                "기간·총액 불일치 탐지율",
                (
                    f"{report.mismatch_detection_rate:.2f}% "
                    f"({report.mismatch_detected}/{report.mismatch_total})"
                ),
                "100%",
                report.mismatch_detection_rate >= MISMATCH_DETECTION_TARGET,
            ),
            _metric_row(
                "근거 없는 확정 경고",
                f"{report.unsupported_confirmed_warning_count}건",
                "0건",
                report.unsupported_confirmed_warning_count == 0,
            ),
            (
                "| 전체 기대 확인 신호 재현율 "
                f"| {report.expected_signal_recall:.2f}% "
                f"({report.expected_signals_detected}/{report.expected_signals_total}) "
                "| 참고값 | - |"
            ),
        )
    )
    return f"""# 고정 계약 10건 오프라인 평가 결과

이 결과는 `fixtures/evaluation/cases`의 사람이 작성한 계약 원문과 오프라인 추출
스냅샷을 현재 Pydantic 스키마, 원문 근거 검증, 결정적 확인 신호 생성 코드로 평가한
결과다. 실제 Upstage·Solar 모델 정확도나 운영 성능으로 해석하지 않는다.

| 지표 | 결과 | 목표 | 판정 |
| --- | ---: | ---: | --- |
{rows}

전체 목표 판정: **{target_text}**

## 실행 방법

```bash
cd apps/api
.venv/bin/python -m evaluation --format markdown
.venv/bin/python -m pytest tests/test_evaluation_fixtures.py -q
```

## 해석 제한

- `OFFLINE_SNAPSHOT`은 외부 네트워크를 사용하지 않는 회귀 기준선이다.
- 실제 모델 평가는 같은 계약 원문을 live Adapter로 실행한 별도 결과로 기록해야 한다.
- 낮은 OCR 품질 케이스의 의도적인 오인식과 근거 누락도 결과에 그대로 포함한다.
- 목표를 달성하지 못하면 fixture 정답이나 수치를 맞추지 않고 실패 결과를 공개한다.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="고정 계약 10건 오프라인 평가")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURE_DIRECTORY,
        help="평가 JSON 디렉터리",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="출력 형식",
    )
    arguments = parser.parse_args(argv)
    report = evaluate_cases(load_cases(arguments.fixtures))
    if arguments.format == "markdown":
        print(render_markdown_report(report), end="")
    else:
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.meets_all_targets else 1


def _stable_uuid(case_id: str, resource: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"ansim-contract:{case_id}:{resource}")


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 100.0
    return round(numerator / denominator * 100, 2)


def _normalize(value: str) -> str:
    return "".join(value.split()).lower()


def _pass_fail(value: bool) -> str:
    return "통과" if value else "미달"


def _metric_row(label: str, result: str, target: str, passed: bool) -> str:
    return f"| {label} | {result} | {target} | {_pass_fail(passed)} |"
