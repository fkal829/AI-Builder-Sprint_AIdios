import hashlib
import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from app.adapters.base import ParsedDocument, ParsedPage
from app.adapters.performance_metrics import (
    PERFORMANCE_METRIC_PROMPT_VERSION,
    _validate_metric_evidence,
)
from app.core.enums import PerformanceMetricVerificationStatus
from app.schemas.performance import PerformanceConfirmedPayload, PerformanceExtractedPayload

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "fixtures" / "demo" / "performance-reports"
EXPECTED_PATH = FIXTURE_DIRECTORY / "expected-extraction.json"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def test_current_performance_demo_pdf_matches_versioned_expectations() -> None:
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    pdf_path = FIXTURE_DIRECTORY / expected["upload"]["filename"]
    pdf_bytes = pdf_path.read_bytes()
    reader = PdfReader(pdf_path, strict=True)

    assert expected["fictional"] is True
    assert expected["prompt_version"] == PERFORMANCE_METRIC_PROMPT_VERSION
    assert hashlib.sha256(pdf_bytes).hexdigest() == expected["source_file_sha256"]
    assert len(reader.pages) == expected["upload"]["page_count"] == 3
    assert list(FIXTURE_DIRECTORY.glob("*.pdf")) == [pdf_path]

    pages = {
        page_number: _normalize(page.extract_text() or "")
        for page_number, page in enumerate(reader.pages, start=1)
    }
    extracted = PerformanceExtractedPayload.model_validate(expected["expected_extraction"])
    for candidate in extracted:
        value = candidate[1]
        if value.source_text is not None:
            assert value.source_page is not None
            assert _normalize(value.source_text) in pages[value.source_page]

    _validate_metric_evidence(
        extracted,
        ParsedDocument(
            pages=tuple(
                ParsedPage(number=index, text=page.extract_text() or "")
                for index, page in enumerate(reader.pages, start=1)
            ),
            model="pypdf-fixture-verification",
        ),
    )

    assert extracted.follower_net_change.verification_status is (
        PerformanceMetricVerificationStatus.NOT_FOUND
    )
    assert extracted.likes.verification_status is PerformanceMetricVerificationStatus.NEEDS_CHECK
    assert extracted.likes.value is None
    assert extracted.published_content_count.value == 10


def test_current_performance_demo_confirmation_keeps_server_derived_values_deterministic() -> None:
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    confirmed = PerformanceConfirmedPayload.model_validate(
        expected["expected_confirmation_payload"]
    )
    items = {item.key: item.value for item in confirmed.metric_items}

    assert confirmed.calculate_engagement_rate() == Decimal(
        expected["expected_server_derived"]["engagement_rate"]
    )
    assert items["ctr"] == Decimal(expected["expected_server_derived"]["ctr_percent"])
    assert items["cpc"] == Decimal(expected["expected_server_derived"]["cpc_krw"])
