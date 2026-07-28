from pathlib import Path
from typing import Protocol

from app.schemas.analysis import ExtractedTerm


class DocumentAnalysisAdapter(Protocol):
    async def extract_terms(self, document_path: Path) -> list[ExtractedTerm]: ...


class SignatureAdapter(Protocol):
    async def create_signature_request(
        self,
        *,
        contract_id: str,
        template_data: dict[str, str],
    ) -> str: ...
