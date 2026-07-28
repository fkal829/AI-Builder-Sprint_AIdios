from pathlib import Path

from app.schemas.analysis import ExtractedTerm


class UpstageAdapter:
    """Document Parse, Information Extract and Solar boundary."""

    def __init__(self, *, api_key: str, base_url: str, mode: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.mode = mode

    async def extract_terms(self, document_path: Path) -> list[ExtractedTerm]:
        raise NotImplementedError("Day 2 vertical slice에서 mock/live 구현을 연결합니다.")
