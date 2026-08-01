"""Security and failure-classification tests for the 17.5 AI composition."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.adapters.base import ParsedDocument, ParsedPage
from app.adapters.performance_metrics import SolarPerformanceMetricMapperError
from app.adapters.upstage import UpstageDocumentParseError
from app.core.exceptions import ExternalStorageFailure
from app.repositories.documents import DocumentRecord
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.performance import PerformanceExtractedPayload
from app.services.performance_ai import PerformanceReportAIExtractor
from app.services.performance_extraction import (
    PerformanceDocumentParseError,
    PerformanceMetricMappingError,
)

CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000081")
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
PRIVATE_PATH_CANARY = "owner/private/storage/secret-performance-report.pdf"
SOURCE_CANARY = "노출수: 987654321"


def source_document(
    *,
    document_type: DocumentType = DocumentType.PERFORMANCE_REPORT,
    parse_status: DocumentParseStatus = DocumentParseStatus.PROCESSING,
) -> DocumentRecord:
    return DocumentRecord(
        id=DOCUMENT_ID,
        contract_id=CONTRACT_ID,
        type=document_type,
        parse_status=parse_status,
        storage_path=PRIVATE_PATH_CANARY,
        content_type="application/pdf",
        size_bytes=128,
        page_count=1,
        created_at=NOW,
    )


def extracted_payload() -> PerformanceExtractedPayload:
    def found(name: str, value: int) -> dict[str, Any]:
        return {
            "value": value,
            "source_page": 1,
            "source_text": f"{name}: {value}",
            "confidence": 1.0,
            "verification_status": "VERIFIED",
        }

    return PerformanceExtractedPayload.model_validate(
        {
            "impressions": found("노출수", 987654321),
            "likes": found("좋아요", 0),
            "comments": found("댓글", 0),
            "reach": found("도달", 0),
            "saves": found("저장", 0),
            "shares": found("공유", 0),
            "follower_net_change": found("팔로워 순증", 0),
            "published_content_count": found("게시물 수", 0),
        }
    )


@dataclass
class StubStorage:
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    async def download_private_object(self, *, path: str) -> bytes:
        self.calls.append(path)
        if self.error is not None:
            raise self.error
        return b"private-report-bytes-canary"


@dataclass
class StubParser:
    error: Exception | None = None
    calls: list[tuple[bytes, str]] = field(default_factory=list)

    async def parse_document(self, *, content: bytes, content_type: str) -> ParsedDocument:
        self.calls.append((content, content_type))
        if self.error is not None:
            raise self.error
        return ParsedDocument(
            pages=(
                ParsedPage(
                    number=1,
                    text=(
                        f"{SOURCE_CANARY}\n좋아요: 0\n댓글: 0\n도달: 0\n저장: 0\n"
                        "공유: 0\n팔로워 순증: 0\n게시물 수: 0"
                    ),
                ),
            ),
            model="fake-parse-v1",
        )


@dataclass
class StubMapper:
    error: Exception | None = None
    calls: list[ParsedDocument] = field(default_factory=list)

    async def map_metrics(
        self,
        *,
        parsed_document: ParsedDocument,
    ) -> PerformanceExtractedPayload:
        self.calls.append(parsed_document)
        if self.error is not None:
            raise self.error
        return extracted_payload()


async def test_private_download_parse_and_mapping_run_in_order_without_logging_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = StubStorage()
    parser = StubParser()
    mapper = StubMapper()
    extractor = PerformanceReportAIExtractor(
        storage=storage,
        parser=parser,  # type: ignore[arg-type]
        mapper=mapper,
    )

    with caplog.at_level(logging.DEBUG):
        result = await extractor(source_document())

    assert result == extracted_payload()
    assert storage.calls == [PRIVATE_PATH_CANARY]
    assert parser.calls == [(b"private-report-bytes-canary", "application/pdf")]
    assert len(mapper.calls) == 1
    logs = caplog.text
    assert PRIVATE_PATH_CANARY not in logs
    assert SOURCE_CANARY not in logs
    assert "987654321" not in logs
    assert "private-report-bytes-canary" not in logs


async def test_private_storage_failure_remains_an_infrastructure_failure() -> None:
    mapper = StubMapper()
    extractor = PerformanceReportAIExtractor(
        storage=StubStorage(error=ExternalStorageFailure("private storage failed")),
        parser=StubParser(),  # type: ignore[arg-type]
        mapper=mapper,
    )

    with pytest.raises(ExternalStorageFailure):
        await extractor(source_document())

    assert mapper.calls == []


async def test_upstage_parse_failure_is_classified_as_a_parse_failure() -> None:
    mapper = StubMapper()
    extractor = PerformanceReportAIExtractor(
        storage=StubStorage(),
        parser=StubParser(error=UpstageDocumentParseError("parse failed")),  # type: ignore[arg-type]
        mapper=mapper,
    )

    with pytest.raises(PerformanceDocumentParseError):
        await extractor(source_document())

    assert mapper.calls == []


async def test_solar_failure_is_classified_after_parse_completed() -> None:
    mapper = StubMapper(error=SolarPerformanceMetricMapperError("mapping failed"))
    extractor = PerformanceReportAIExtractor(
        storage=StubStorage(),
        parser=StubParser(),  # type: ignore[arg-type]
        mapper=mapper,
    )

    with pytest.raises(PerformanceMetricMappingError):
        await extractor(source_document())

    assert len(mapper.calls) == 1


@pytest.mark.parametrize(
    ("document_type", "parse_status"),
    [
        (DocumentType.CONTRACT, DocumentParseStatus.PROCESSING),
        (DocumentType.PERFORMANCE_REPORT, DocumentParseStatus.PENDING),
    ],
)
async def test_only_claimed_performance_documents_cross_the_ai_boundary(
    document_type: DocumentType,
    parse_status: DocumentParseStatus,
) -> None:
    storage = StubStorage()
    extractor = PerformanceReportAIExtractor(
        storage=storage,
        parser=StubParser(),  # type: ignore[arg-type]
        mapper=StubMapper(),
    )

    with pytest.raises(PerformanceDocumentParseError):
        await extractor(source_document(document_type=document_type, parse_status=parse_status))

    assert storage.calls == []
