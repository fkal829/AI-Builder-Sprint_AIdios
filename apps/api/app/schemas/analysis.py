from typing import Any

from pydantic import BaseModel, Field


class ExtractedTerm(BaseModel):
    field: str = Field(min_length=1)
    value: Any
    source_page: int = Field(ge=1)
    source_text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
