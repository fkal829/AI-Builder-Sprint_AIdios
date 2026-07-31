from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import ObligationStatus, PublicTokenScope


class Obligation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    contract_id: UUID
    title: str = Field(min_length=1)
    due_date: date
    assignee: Literal["AGENCY"]
    evidence_type: Literal["URL"]
    source_document_id: UUID
    source_page: int = Field(ge=1)
    source_text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_url: str | None = Field(
        default=None,
        pattern=r"^https?://",
        max_length=2048,
    )
    status: ObligationStatus
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    payment_condition_met: bool

    @field_validator("title", "source_text")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("이행 항목의 제목과 원문 근거는 비어 있을 수 없습니다.")
        return value

    @field_validator("submitted_at", "reviewed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("이행 항목 시각은 시간대 정보를 포함해야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_status_fields(self) -> "Obligation":
        if self.status == ObligationStatus.PENDING:
            if any(
                value is not None
                for value in (self.evidence_url, self.submitted_at, self.reviewed_at)
            ) or self.payment_condition_met:
                raise ValueError("PENDING 이행 항목에는 제출 또는 검토 결과가 없어야 합니다.")
            return self

        if self.evidence_url is None or self.submitted_at is None:
            raise ValueError("제출된 이행 항목에는 증빙 URL과 제출 시각이 필요합니다.")

        if self.status == ObligationStatus.SUBMITTED:
            if self.reviewed_at is not None or self.payment_condition_met:
                raise ValueError("SUBMITTED 이행 항목에는 검토 결과가 없어야 합니다.")
            return self

        if self.reviewed_at is None:
            raise ValueError("검토가 끝난 이행 항목에는 검토 시각이 필요합니다.")
        if self.payment_condition_met != (self.status == ObligationStatus.APPROVED):
            raise ValueError("지급 조건 충족 표시는 APPROVED 상태와 일치해야 합니다.")
        return self


ObligationList = Annotated[list[Obligation], Field(max_length=1)]


class PublicLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_in_hours: int = Field(ge=1, le=168)


class PublicLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_url: AnyHttpUrl
    scope: Literal[PublicTokenScope.OBLIGATION_EVIDENCE]
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def require_expiry_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("증빙 제출 링크 만료 시각은 시간대 정보를 포함해야 합니다.")
        return value
