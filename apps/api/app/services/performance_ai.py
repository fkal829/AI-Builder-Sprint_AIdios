"""Private performance-report Parse and metric-mapping composition.

The public extraction service owns attempt state and idempotency. This module
owns only the external-AI boundary and deliberately never logs the source path,
file bytes, parsed text, or mapped payload.
"""

from typing import Protocol

from app.adapters.base import DocumentAnalysisAdapter, ParsedDocument
from app.adapters.upstage import UpstageDocumentParseError
from app.core.exceptions import ExternalStorageFailure
from app.repositories.documents import DocumentRecord, PrivateStorage
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.performance import PerformanceExtractedPayload
from app.services.performance import PERFORMANCE_REPORT_CONTENT_TYPES
from app.services.performance_extraction import (
    PerformanceDocumentParseError,
    PerformanceMetricMappingError,
)


class PerformanceMetricMapper(Protocol):
    async def map_metrics(
        self,
        *,
        parsed_document: ParsedDocument,
    ) -> PerformanceExtractedPayload: ...


class PerformanceReportAIExtractor:
    """Load one claimed private report and run Parse then strict metric mapping."""

    def __init__(
        self,
        *,
        storage: PrivateStorage,
        parser: DocumentAnalysisAdapter,
        mapper: PerformanceMetricMapper,
    ) -> None:
        self._storage = storage
        self._parser = parser
        self._mapper = mapper

    async def __call__(self, source_document: DocumentRecord) -> PerformanceExtractedPayload:
        if (
            source_document.type is not DocumentType.PERFORMANCE_REPORT
            or source_document.parse_status is not DocumentParseStatus.PROCESSING
            or source_document.content_type not in PERFORMANCE_REPORT_CONTENT_TYPES
        ):
            raise PerformanceDocumentParseError(
                "점유된 PERFORMANCE_REPORT 원본만 지표를 추출할 수 있습니다."
            )

        try:
            content = await self._storage.download_private_object(path=source_document.storage_path)
        except ExternalStorageFailure:
            # Storage availability is an infrastructure failure, not evidence that
            # Upstage failed to parse the document. Keep the boundary distinct so
            # the public orchestration can return a retryable 503.
            raise

        try:
            parsed_document = await self._parser.parse_document(
                content=content,
                content_type=source_document.content_type,
            )
        except UpstageDocumentParseError as error:
            raise PerformanceDocumentParseError(
                "광고효과 리포트 원본 구조 분석에 실패했습니다."
            ) from error

        try:
            return await self._mapper.map_metrics(parsed_document=parsed_document)
        except ValueError as error:
            raise PerformanceMetricMappingError(
                "광고효과 리포트 지표 매핑에 실패했습니다."
            ) from error
