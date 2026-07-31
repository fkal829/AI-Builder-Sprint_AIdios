"""P2-C-1: PerformanceReportRevision / PerformanceFlag / PerformanceInquiryDraft
data model. `PerformanceReport` itself (status UPLOADED/EXTRACTED, upload,
Upstage/Solar extraction) is P2-B's schema; this module only models what a
confirmed owner revision, its flags, and the resulting inquiry draft look
like, so P2-C can be developed against a fake before P2-B's foundation lands.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import PerformanceFlagType, PerformanceRevisionStatus

INQUIRY_TEMPLATE_VERSION = "performance-inquiry-copy-v1"


class PerformanceMetrics(BaseModel):
    """The owner-confirmed payload. `engagement_rate` is never part of this —
    it is server-derived and stored separately on the revision."""

    model_config = ConfigDict(extra="forbid")

    impressions: int = Field(ge=0)
    likes: int = Field(ge=0)
    comments: int = Field(ge=0)
    reach: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    follower_net_change: int | None = None
    published_content_count: int | None = Field(default=None, ge=0)
    inquiries: int | None = Field(default=None, ge=0)
    reservations: int | None = Field(default=None, ge=0)
    purchases: int | None = Field(default=None, ge=0)


class PerformanceFlagBasisTerm(BaseModel):
    """A frozen snapshot of one `ExtractedTerm` cited as a flag's basis.

    Snapshotting the evidence (not just linking `extracted_term_id`) keeps a
    flag's stated reasoning immutable even if the underlying term row is
    reprocessed later.
    """

    model_config = ConfigDict(extra="forbid")

    extracted_term_id: UUID
    document_id: UUID
    source_page: int = Field(ge=1)
    source_text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class PerformanceFlag(BaseModel):
    """Belongs to a revision, not the report — a flag raised on version N
    does not automatically carry over to version N+1's re-confirmation."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    report_revision_id: UUID
    flag_type: PerformanceFlagType
    basis_terms: tuple[PerformanceFlagBasisTerm, ...] = Field(default_factory=tuple)
    comparison_report_revision_id: UUID | None = None
    expected_quantity: int | None = Field(default=None, ge=0)
    expected_quantity_unit: str | None = Field(default=None, min_length=1)
    owner_issue_note: str | None = Field(default=None, min_length=1, max_length=500)
    created_at: datetime

    @model_validator(mode="after")
    def validate_flag_shape(self) -> "PerformanceFlag":
        if self.flag_type == PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL:
            if len(self.basis_terms) != 2:
                raise ValueError(
                    "수량 부족 신호는 CONTENT_QUANTITY·POSTING_FREQUENCY 근거"
                    " 2개가 모두 필요합니다."
                )
            if self.expected_quantity is None or self.expected_quantity_unit is None:
                raise ValueError("수량 부족 신호는 기대 수량과 단위 snapshot이 필요합니다.")
            if self.comparison_report_revision_id is not None or self.owner_issue_note is not None:
                raise ValueError("수량 부족 신호에는 비교 revision이나 이상 사유를 넣지 않습니다.")
        elif self.flag_type == PerformanceFlagType.ENGAGEMENT_RATE_DROP:
            if self.basis_terms:
                raise ValueError("반응률 하락 신호는 계약 원문 근거를 갖지 않습니다.")
            if self.comparison_report_revision_id is None:
                raise ValueError("반응률 하락 신호는 비교 대상 전월 revision이 필요합니다.")
            if self.expected_quantity is not None or self.owner_issue_note is not None:
                raise ValueError("반응률 하락 신호에는 기대 수량이나 이상 사유를 넣지 않습니다.")
        elif self.flag_type == PerformanceFlagType.OWNER_REPORTED_ISSUE:
            if self.basis_terms:
                raise ValueError("소상공인 이상 신고 신호는 계약 원문 근거를 갖지 않습니다.")
            if not self.owner_issue_note:
                raise ValueError("소상공인 이상 신고 신호는 사유가 필요합니다.")
            if self.comparison_report_revision_id is not None or self.expected_quantity is not None:
                raise ValueError("이상 신고 신호에는 비교 revision이나 기대 수량을 넣지 않습니다.")
        return self


class PerformanceInquiryDraft(BaseModel):
    """A decision-deterministic snapshot, one per flag. Never regenerated on
    read — GET always returns exactly what was stored at confirm/correct
    time."""

    model_config = ConfigDict(extra="forbid")

    flag_id: UUID
    text: str = Field(min_length=1, max_length=1000)
    template_version: Literal["performance-inquiry-copy-v1"] = INQUIRY_TEMPLATE_VERSION
    created_at: datetime


class PerformanceReportRevision(BaseModel):
    """One immutable confirmation snapshot. Version 1 is the report's first
    confirmation; version N>1 is an append-only correction that never
    replaces version N-1."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    report_id: UUID
    version: int = Field(ge=1)
    confirmed_payload: PerformanceMetrics
    engagement_rate: Decimal | None = None
    status: PerformanceRevisionStatus
    corrected_from_revision_id: UUID | None = None
    correction_reason: str | None = Field(default=None, min_length=1, max_length=500)
    confirmed_at: datetime

    @model_validator(mode="after")
    def validate_correction_pairing(self) -> "PerformanceReportRevision":
        if self.version == 1:
            if self.corrected_from_revision_id is not None or self.correction_reason is not None:
                raise ValueError(
                    "최초 확정 revision(version 1)에는 정정 이전 참조나 사유를 넣지 않습니다."
                )
        else:
            if self.corrected_from_revision_id is None or not self.correction_reason:
                raise ValueError(
                    "정정 revision(version 2 이상)에는 이전 revision 참조와 사유가 필요합니다."
                )
        return self
