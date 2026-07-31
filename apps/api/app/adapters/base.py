from dataclasses import dataclass
from typing import Protocol

from app.core.enums import ExtractedField
from app.schemas.adjustments import (
    CounterproposalComparisonInput,
    GeneratedCounterproposalComparison,
)
from app.schemas.analysis import (
    ExtractedTermCandidate,
    SolarReviewInput,
    SolarReviewOutput,
)


@dataclass(frozen=True)
class ParsedPage:
    number: int
    text: str


@dataclass(frozen=True)
class ParsedElement:
    page: int
    text: str
    coordinates: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class ParsedDocument:
    pages: tuple[ParsedPage, ...]
    model: str
    elements: tuple[ParsedElement, ...] = ()


class DocumentAnalysisAdapter(Protocol):
    async def parse_document(
        self,
        *,
        content: bytes,
        content_type: str,
    ) -> ParsedDocument: ...

    async def extract_terms(
        self,
        *,
        content: bytes,
        content_type: str,
        parsed_document: ParsedDocument,
        target_fields: tuple[ExtractedField, ...],
    ) -> list[ExtractedTermCandidate]: ...


class ContractReviewAdapter(Protocol):
    async def generate_review_content(
        self,
        *,
        items: list[SolarReviewInput],
    ) -> list[SolarReviewOutput]: ...


class CounterproposalComparisonAdapter(Protocol):
    async def compare_counterproposals(
        self,
        *,
        items: list[CounterproposalComparisonInput],
    ) -> list[GeneratedCounterproposalComparison]: ...


class SignatureAdapter(Protocol):
    async def create_embedded_draft(
        self,
        *,
        document_pdf: bytes,
        document_title: str,
        redirect_url: str,
    ) -> str: ...
