from pathlib import Path

from app.adapters.base import DocumentAnalysisAdapter
from app.schemas.analysis import ExtractedTerm


class AnalysisService:
    def __init__(self, adapter: DocumentAnalysisAdapter) -> None:
        self.adapter = adapter

    async def analyze(self, document_path: Path) -> list[ExtractedTerm]:
        """Evaluator loop entry point; validation and at most two retries belong here."""
        return await self.adapter.extract_terms(document_path)
