import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from app.core.enums import (
    ExtractedField,
    ExtractedSourceType,
    PerformanceFlagType,
    PerformanceMetricVerificationStatus,
    PerformanceReportStatus,
    VerificationStatus,
)

PerformancePeriod = Annotated[
    str,
    Field(
        strict=True,
        pattern=r"^(?:[1-9][0-9]{3}|0[1-9][0-9]{2}|00[1-9][0-9]|000[1-9])-(0[1-9]|1[0-2])$",
    ),
]
PerformanceConfirmedStatus = Literal[
    PerformanceReportStatus.CONFIRMED,
    PerformanceReportStatus.FLAGGED,
]
POSTGRES_BIGINT_MIN = -(2**63)
POSTGRES_BIGINT_MAX = 2**63 - 1
MAX_ENGAGEMENT_RATE = Decimal("36893488147419103228.000000")
MAX_SERIALIZED_ENGAGEMENT_RATE = 36893488147419103232
NonNegativeMetric = Annotated[
    int,
    Field(strict=True, ge=0, le=POSTGRES_BIGINT_MAX),
]
SignedMetric = Annotated[
    int,
    Field(strict=True, ge=POSTGRES_BIGINT_MIN, le=POSTGRES_BIGINT_MAX),
]
EngagementRate = Annotated[
    Decimal,
    Field(ge=0, le=MAX_ENGAGEMENT_RATE, max_digits=26, decimal_places=6),
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
    WithJsonSchema(
        {
            "type": "number",
            "minimum": 0,
            # The exact Decimal maximum rounds upward by four when exposed as
            # an IEEE-754 JSON number. Runtime and DB validation remain exact.
            "maximum": MAX_SERIALIZED_ENGAGEMENT_RATE,
            "x-decimal-places": 6,
        },
        mode="serialization",
    ),
]
PerformanceMetricValue = Annotated[
    Decimal,
    Field(ge=0, decimal_places=6),
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
    WithJsonSchema(
        {
            "type": "number",
            "minimum": 0,
            "x-decimal-places": 6,
        },
        mode="serialization",
    ),
]
PerformanceMetricUnit = Literal["KRW", "COUNT", "PERCENT", "NUMBER"]

_CANONICAL_PERFORMANCE_METRIC_UNITS: dict[str, PerformanceMetricUnit] = {
    "ad_spend": "KRW",
    "impressions": "COUNT",
    "clicks": "COUNT",
    "ctr": "PERCENT",
    "cpc": "KRW",
    "published_content_count": "COUNT",
}
_DERIVED_PERFORMANCE_METRIC_KEYS = frozenset({"ctr", "cpc"})

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class StrictPerformanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _PerformanceMetricCandidate(StrictPerformanceModel):
    source_page: int | None = Field(strict=True, ge=1)
    source_text: str | None = Field(min_length=1)
    confidence: float = Field(strict=True, ge=0, le=1)
    verification_status: PerformanceMetricVerificationStatus

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        has_page = self.source_page is not None
        has_text = self.source_text is not None
        if has_page != has_text:
            raise ValueError("성과 지표의 source_page와 source_text는 함께 제공해야 합니다.")

        value = self.value
        if self.verification_status == PerformanceMetricVerificationStatus.VERIFIED:
            if value is None or not has_page:
                raise ValueError("VERIFIED 성과 지표에는 값과 원문 근거가 필요합니다.")
        elif self.verification_status == PerformanceMetricVerificationStatus.NOT_FOUND:
            if value is not None or has_page:
                raise ValueError("NOT_FOUND 성과 지표에는 값과 원문 근거를 넣을 수 없습니다.")
        elif not has_page:
            raise ValueError("NEEDS_CHECK 성과 지표에는 확인할 원문 근거가 필요합니다.")
        return self


class PerformanceNonNegativeMetricCandidate(_PerformanceMetricCandidate):
    value: NonNegativeMetric | None


class PerformanceSignedMetricCandidate(_PerformanceMetricCandidate):
    value: SignedMetric | None


def _not_found_non_negative_candidate() -> PerformanceNonNegativeMetricCandidate:
    return PerformanceNonNegativeMetricCandidate(
        value=None,
        source_page=None,
        source_text=None,
        confidence=0.0,
        verification_status=PerformanceMetricVerificationStatus.NOT_FOUND,
    )


class PerformanceExtractedPayload(StrictPerformanceModel):
    ad_spend: PerformanceNonNegativeMetricCandidate = Field(
        default_factory=_not_found_non_negative_candidate
    )
    impressions: PerformanceNonNegativeMetricCandidate
    clicks: PerformanceNonNegativeMetricCandidate = Field(
        default_factory=_not_found_non_negative_candidate
    )
    likes: PerformanceNonNegativeMetricCandidate
    comments: PerformanceNonNegativeMetricCandidate
    reach: PerformanceNonNegativeMetricCandidate
    saves: PerformanceNonNegativeMetricCandidate
    shares: PerformanceNonNegativeMetricCandidate
    follower_net_change: PerformanceSignedMetricCandidate
    published_content_count: PerformanceNonNegativeMetricCandidate


class PerformanceMetricItem(StrictPerformanceModel):
    key: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$",
    )
    label: str = Field(min_length=1, max_length=50)
    value: PerformanceMetricValue | None
    unit: PerformanceMetricUnit

    @field_validator("label", mode="before")
    @classmethod
    def reject_label_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and _CONTROL_CHARACTERS.search(value):
            raise ValueError("성과 지표 이름에는 제어문자를 사용할 수 없습니다.")
        return value

    @model_validator(mode="after")
    def validate_unit_and_value(self) -> Self:
        canonical_unit = _CANONICAL_PERFORMANCE_METRIC_UNITS.get(self.key)
        if canonical_unit is not None and self.unit != canonical_unit:
            raise ValueError(f"{self.key} 지표의 단위는 {canonical_unit}이어야 합니다.")
        if (
            self.value is not None
            and self.unit in {"COUNT", "KRW"}
            and self.value != self.value.to_integral_value()
        ):
            raise ValueError("COUNT와 KRW 지표 값은 정수여야 합니다.")
        return self


class PerformanceConfirmedPayloadInput(StrictPerformanceModel):
    impressions: NonNegativeMetric
    likes: NonNegativeMetric
    comments: NonNegativeMetric
    reach: NonNegativeMetric | None
    saves: NonNegativeMetric | None
    shares: NonNegativeMetric | None
    follower_net_change: SignedMetric | None
    published_content_count: NonNegativeMetric | None
    inquiries: NonNegativeMetric | None
    reservations: NonNegativeMetric | None
    purchases: NonNegativeMetric | None
    metric_items: list[PerformanceMetricItem] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_metric_items(self) -> Self:
        keys = [item.key for item in self.metric_items]
        if len(keys) != len(set(keys)):
            raise ValueError("성과 지표 key는 중복될 수 없습니다.")

        labels = [item.label.casefold() for item in self.metric_items]
        if len(labels) != len(set(labels)):
            raise ValueError("성과 지표 이름은 대소문자를 구분하지 않고 중복될 수 없습니다.")

        items = {item.key: item for item in self.metric_items}
        self._validate_legacy_projection(items)
        derived_values = _calculate_derived_metric_values(items)
        for key in _DERIVED_PERFORMANCE_METRIC_KEYS:
            item = items.get(key)
            if item is not None and item.value is not None and item.value != derived_values[key]:
                raise ValueError(f"{key} 값은 null이거나 서버 계산값과 정확히 같아야 합니다.")
        return self

    def _validate_legacy_projection(self, items: dict[str, PerformanceMetricItem]) -> None:
        impressions = items.get("impressions")
        if (
            impressions is not None
            and impressions.value is not None
            and impressions.value != Decimal(self.impressions)
        ):
            raise ValueError("metric_items.impressions는 legacy impressions와 같아야 합니다.")

        published_content_count = items.get("published_content_count")
        legacy_published_content_count = (
            Decimal(self.published_content_count)
            if self.published_content_count is not None
            else None
        )
        if (
            published_content_count is not None
            and published_content_count.value is not None
            and published_content_count.value != legacy_published_content_count
        ):
            raise ValueError(
                "metric_items.published_content_count는 legacy published_content_count와 "
                "같아야 합니다."
            )


class PerformanceConfirmedPayload(PerformanceConfirmedPayloadInput):
    @model_validator(mode="after")
    def populate_derived_metric_values(self) -> Self:
        items = {item.key: item for item in self.metric_items}
        derived_values = _calculate_derived_metric_values(items)
        self.metric_items = [
            item.model_copy(update={"value": derived_values[item.key]})
            if item.key in _DERIVED_PERFORMANCE_METRIC_KEYS
            else item
            for item in self.metric_items
        ]
        return self

    def calculate_engagement_rate(self) -> Decimal | None:
        if self.impressions == 0:
            return None

        numerator = self.likes + self.comments + (self.saves or 0) + (self.shares or 0)
        return (Decimal(numerator) / Decimal(self.impressions)).quantize(
            Decimal("0.000001"),
            rounding=ROUND_HALF_UP,
        )


def _calculate_derived_metric_values(
    items: dict[str, PerformanceMetricItem],
) -> dict[str, Decimal | None]:
    ad_spend = items.get("ad_spend")
    impressions = items.get("impressions")
    clicks = items.get("clicks")

    ctr: Decimal | None = None
    if (
        clicks is not None
        and clicks.value is not None
        and impressions is not None
        and impressions.value is not None
        and impressions.value != 0
    ):
        ctr = _rounded_ratio(
            clicks.value * Decimal(100),
            impressions.value,
            quantum=Decimal("0.01"),
        )

    cpc: Decimal | None = None
    if (
        ad_spend is not None
        and ad_spend.value is not None
        and clicks is not None
        and clicks.value is not None
        and clicks.value != 0
    ):
        cpc = _rounded_ratio(ad_spend.value, clicks.value, quantum=Decimal("1"))
    return {"ctr": ctr, "cpc": cpc}


def _rounded_ratio(numerator: Decimal, denominator: Decimal, *, quantum: Decimal) -> Decimal:
    digit_count = len(numerator.as_tuple().digits) + len(denominator.as_tuple().digits)
    with localcontext() as context:
        context.prec = max(28, digit_count + 12)
        return (numerator / denominator).quantize(quantum, rounding=ROUND_HALF_UP)


class PerformanceReportConfirmation(StrictPerformanceModel):
    """The confirm operation covers both version 1 confirmation and later corrections."""

    expected_revision: int = Field(strict=True, ge=0)
    confirmed_payload: PerformanceConfirmedPayloadInput
    has_issue: bool = Field(strict=True)
    issue_note: str | None = Field(min_length=1, max_length=500)
    correction_reason: str | None = Field(min_length=1, max_length=500)

    @field_validator("issue_note", "correction_reason", mode="before")
    @classmethod
    def reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and _CONTROL_CHARACTERS.search(value):
            raise ValueError("확인 사유에는 제어문자를 사용할 수 없습니다.")
        return value

    @model_validator(mode="after")
    def validate_confirmation_kind(self) -> Self:
        if self.has_issue:
            if self.issue_note is None:
                raise ValueError("이상 있음으로 저장할 때는 issue_note가 필요합니다.")
        elif self.issue_note is not None:
            raise ValueError("이상 없음으로 저장할 때는 issue_note가 null이어야 합니다.")
        if self.expected_revision == 0:
            if self.correction_reason is not None:
                raise ValueError("최초 확정에는 correction_reason을 넣을 수 없습니다.")
        elif self.correction_reason is None:
            raise ValueError("정정에는 비어 있지 않은 correction_reason이 필요합니다.")
        return self


class PerformanceFlagBasisSnapshot(StrictPerformanceModel):
    # A basis snapshot must preserve the exact ExtractedTerm evidence text so
    # the DB trigger can prove it belongs to the same verified contract term.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    extracted_term_id: UUID
    document_id: UUID
    field: Literal[ExtractedField.CONTENT_QUANTITY, ExtractedField.POSTING_FREQUENCY]
    source_type: Literal[ExtractedSourceType.CONTRACT_DOCUMENT]
    source_page: int = Field(strict=True, ge=1)
    source_text: str = Field(min_length=1)
    confidence: float = Field(strict=True, ge=0, le=1)
    verification_status: Literal[VerificationStatus.VERIFIED]

    @field_validator("source_text")
    @classmethod
    def require_nonblank_source_text_without_normalizing(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("근거 원문은 비어 있을 수 없습니다.")
        return value


class PerformanceFlag(StrictPerformanceModel):
    id: UUID
    report_revision_id: UUID
    flag_type: PerformanceFlagType
    basis_extracted_term_ids: list[UUID] = Field(max_length=2)
    basis_snapshots: list[PerformanceFlagBasisSnapshot] = Field(max_length=2)
    comparison_report_revision_id: UUID | None
    expected_content_count: NonNegativeMetric | None
    expected_period_unit: Literal["MONTH"] | None
    actual_content_count: NonNegativeMetric | None
    previous_engagement_rate: EngagementRate | None
    current_engagement_rate: EngagementRate | None
    issue_note: str | None = Field(min_length=1, max_length=500)
    created_at: datetime

    @field_validator("issue_note", mode="before")
    @classmethod
    def reject_issue_note_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and _CONTROL_CHARACTERS.search(value):
            raise ValueError("사용자 이상 사유에는 제어문자를 사용할 수 없습니다.")
        return value

    @field_validator("created_at")
    @classmethod
    def require_created_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("성과 확인 신호 시각은 시간대 정보를 포함해야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_flag_payload(self) -> Self:
        if len(set(self.basis_extracted_term_ids)) != len(self.basis_extracted_term_ids):
            raise ValueError("basis_extracted_term_ids는 중복될 수 없습니다.")
        snapshot_ids = [snapshot.extracted_term_id for snapshot in self.basis_snapshots]
        if len(set(snapshot_ids)) != len(snapshot_ids):
            raise ValueError("basis_snapshots의 추출값 ID는 중복될 수 없습니다.")
        if set(snapshot_ids) != set(self.basis_extracted_term_ids):
            raise ValueError("계약 근거 ID와 근거 snapshot은 같은 추출값을 가리켜야 합니다.")

        if self.flag_type == PerformanceFlagType.DELIVERABLE_COUNT_SHORTFALL:
            self._validate_deliverable_shortfall()
        elif self.flag_type == PerformanceFlagType.ENGAGEMENT_RATE_DROP:
            self._validate_engagement_drop()
        else:
            self._validate_owner_issue()
        return self

    def _validate_deliverable_shortfall(self) -> None:
        fields = {snapshot.field for snapshot in self.basis_snapshots}
        if len(self.basis_extracted_term_ids) != 2 or fields != {
            ExtractedField.CONTENT_QUANTITY,
            ExtractedField.POSTING_FREQUENCY,
        }:
            raise ValueError("수량 부족 신호에는 수량과 월 주기 계약 근거가 모두 필요합니다.")
        if (
            self.comparison_report_revision_id is not None
            or self.expected_content_count is None
            or self.expected_content_count < 1
            or self.expected_period_unit != "MONTH"
            or self.actual_content_count is None
            or self.actual_content_count >= self.expected_content_count
            or self.previous_engagement_rate is not None
            or self.current_engagement_rate is not None
            or self.issue_note is not None
        ):
            raise ValueError("수량 부족 신호의 비교값과 nullable 필드가 올바르지 않습니다.")

    def _validate_engagement_drop(self) -> None:
        if (
            self.basis_extracted_term_ids
            or self.basis_snapshots
            or self.comparison_report_revision_id is None
            or self.expected_content_count is not None
            or self.expected_period_unit is not None
            or self.actual_content_count is not None
            or self.previous_engagement_rate is None
            or self.previous_engagement_rate <= 0
            or self.current_engagement_rate is None
            or self.current_engagement_rate >= self.previous_engagement_rate
            or self.issue_note is not None
        ):
            raise ValueError("반응률 하락 신호의 비교값과 nullable 필드가 올바르지 않습니다.")

    def _validate_owner_issue(self) -> None:
        if (
            self.basis_extracted_term_ids
            or self.basis_snapshots
            or self.comparison_report_revision_id is not None
            or self.expected_content_count is not None
            or self.expected_period_unit is not None
            or self.actual_content_count is not None
            or self.previous_engagement_rate is not None
            or self.current_engagement_rate is not None
            or self.issue_note is None
        ):
            raise ValueError("사용자 이상 기록에는 issue_note만 포함해야 합니다.")


class PerformanceInquiryDraft(StrictPerformanceModel):
    id: UUID
    flag_id: UUID
    text: str = Field(min_length=1, max_length=1000)
    template_version: Literal["performance-inquiry-copy-v1"]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_created_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("문의 문안 시각은 시간대 정보를 포함해야 합니다.")
        return value


class PerformanceReportRevision(StrictPerformanceModel):
    id: UUID
    report_id: UUID
    version: int = Field(strict=True, ge=1)
    status: PerformanceConfirmedStatus
    confirmed_payload: PerformanceConfirmedPayload
    engagement_rate: EngagementRate | None
    corrected_from_revision_id: UUID | None
    correction_reason: str | None = Field(min_length=1, max_length=500)
    confirmed_at: datetime
    flags: list[PerformanceFlag] = Field(max_length=3)
    inquiry_drafts: list[PerformanceInquiryDraft] = Field(max_length=3)

    @field_validator("correction_reason", mode="before")
    @classmethod
    def reject_reason_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and _CONTROL_CHARACTERS.search(value):
            raise ValueError("정정 사유에는 제어문자를 사용할 수 없습니다.")
        return value

    @field_validator("confirmed_at")
    @classmethod
    def require_confirmed_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("성과 확정 시각은 시간대 정보를 포함해야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        if self.engagement_rate != self.confirmed_payload.calculate_engagement_rate():
            raise ValueError("engagement_rate는 원본 정수에서 계산한 소수 6자리 값이어야 합니다.")
        if self.version == 1:
            if self.corrected_from_revision_id is not None or self.correction_reason is not None:
                raise ValueError("version 1에는 이전 revision이나 정정 사유가 없어야 합니다.")
        elif self.corrected_from_revision_id is None or self.correction_reason is None:
            raise ValueError("version 2 이상에는 이전 revision과 정정 사유가 필요합니다.")
        if self.corrected_from_revision_id == self.id:
            raise ValueError("revision은 자신을 정정 전 revision으로 참조할 수 없습니다.")

        flag_ids = [flag.id for flag in self.flags]
        draft_ids = [draft.id for draft in self.inquiry_drafts]
        draft_flag_ids = [draft.flag_id for draft in self.inquiry_drafts]
        if len(set(flag_ids)) != len(flag_ids):
            raise ValueError("revision의 flag ID는 중복될 수 없습니다.")
        if len(set(draft_ids)) != len(draft_ids) or len(set(draft_flag_ids)) != len(draft_flag_ids):
            raise ValueError("revision의 문의 문안 또는 flag 연결은 중복될 수 없습니다.")
        if any(flag.report_revision_id != self.id for flag in self.flags):
            raise ValueError("flag는 자신이 포함된 report revision에 속해야 합니다.")
        if set(draft_flag_ids) != set(flag_ids):
            raise ValueError("각 flag에는 정확히 한 개의 저장된 문의 문안이 필요합니다.")
        if (self.status == PerformanceReportStatus.FLAGGED) != bool(self.flags):
            raise ValueError("revision 상태는 저장된 flag 존재 여부와 일치해야 합니다.")
        return self


class PerformanceReport(StrictPerformanceModel):
    id: UUID
    contract_id: UUID
    period: PerformancePeriod
    source_document_id: UUID
    status: PerformanceReportStatus
    extracted_payload: PerformanceExtractedPayload | None
    current_revision: PerformanceReportRevision | None
    revision_count: int = Field(strict=True, ge=0)
    revisions: list[PerformanceReportRevision]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_timestamp_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("성과 리포트 시각은 시간대 정보를 포함해야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_report_projection(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at은 created_at보다 빠를 수 없습니다.")

        versions = [revision.version for revision in self.revisions]
        if versions != list(range(1, len(self.revisions) + 1)):
            raise ValueError("revisions는 version 1부터 빠짐없이 오름차순이어야 합니다.")
        if any(revision.report_id != self.id for revision in self.revisions):
            raise ValueError("모든 revision은 자신이 포함된 report에 속해야 합니다.")
        if any(
            current.corrected_from_revision_id != previous.id
            for previous, current in zip(self.revisions, self.revisions[1:], strict=False)
        ):
            raise ValueError("version 2 이상의 revision은 실제 직전 revision을 참조해야 합니다.")
        if self.revision_count != len(self.revisions):
            raise ValueError("revision_count는 revisions 길이와 같아야 합니다.")

        if self.status == PerformanceReportStatus.UPLOADED:
            if self.extracted_payload is not None or self.current_revision is not None or versions:
                raise ValueError("UPLOADED 리포트에는 추출값이나 revision이 없어야 합니다.")
        elif self.status == PerformanceReportStatus.EXTRACTED:
            if self.extracted_payload is None or self.current_revision is not None or versions:
                raise ValueError("EXTRACTED 리포트에는 추출값만 있어야 합니다.")
        else:
            if self.extracted_payload is None or self.current_revision is None or not versions:
                raise ValueError("확정된 리포트에는 추출값과 현재 revision이 필요합니다.")
            if self.current_revision != self.revisions[-1]:
                raise ValueError("current_revision은 가장 최신 revision이어야 합니다.")
            if self.current_revision.status != self.status:
                raise ValueError("report 상태는 현재 revision 상태와 일치해야 합니다.")
        return self


class PerformanceReportCreated(PerformanceReport):
    status: Literal[PerformanceReportStatus.UPLOADED]
    extracted_payload: None
    current_revision: None
    revision_count: Literal[0]
    revisions: list[PerformanceReportRevision] = Field(max_length=0)


class PerformanceReportExtracted(PerformanceReport):
    status: Literal[PerformanceReportStatus.EXTRACTED]
    extracted_payload: PerformanceExtractedPayload
    current_revision: None
    revision_count: Literal[0]
    revisions: list[PerformanceReportRevision] = Field(max_length=0)


class PerformanceReportConfirmed(PerformanceReport):
    status: PerformanceConfirmedStatus
    extracted_payload: PerformanceExtractedPayload
    current_revision: PerformanceReportRevision
    revision_count: int = Field(strict=True, ge=1)
    revisions: list[PerformanceReportRevision] = Field(min_length=1)


class PerformanceConfirmedSeriesPoint(StrictPerformanceModel):
    report_id: UUID
    report_revision_id: UUID
    period: PerformancePeriod
    version: int = Field(strict=True, ge=1)
    status: PerformanceConfirmedStatus
    confirmed_payload: PerformanceConfirmedPayload
    engagement_rate: EngagementRate | None
    confirmed_at: datetime

    @field_validator("confirmed_at")
    @classmethod
    def require_confirmed_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("성과 집계 시각은 시간대 정보를 포함해야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_engagement_rate(self) -> Self:
        if self.engagement_rate != self.confirmed_payload.calculate_engagement_rate():
            raise ValueError("집계 반응률은 원본 정수에서 계산한 값과 같아야 합니다.")
        return self


class ContractPerformance(StrictPerformanceModel):
    contract_id: UUID
    reports: list[PerformanceReport]
    confirmed_series: list[PerformanceConfirmedSeriesPoint]
    flags: list[PerformanceFlag]
    inquiry_drafts: list[PerformanceInquiryDraft]

    @model_validator(mode="after")
    def validate_latest_revision_projection(self) -> Self:
        report_ids = [report.id for report in self.reports]
        report_periods = [report.period for report in self.reports]
        if len(set(report_ids)) != len(report_ids) or len(set(report_periods)) != len(
            report_periods
        ):
            raise ValueError("계약별 성과 리포트 ID와 period는 중복될 수 없습니다.")
        if report_periods != sorted(report_periods):
            raise ValueError("reports는 period 오름차순이어야 합니다.")
        if any(report.contract_id != self.contract_id for report in self.reports):
            raise ValueError("모든 성과 리포트는 조회한 계약에 속해야 합니다.")

        confirmed_reports = [
            report
            for report in self.reports
            if report.status in {PerformanceReportStatus.CONFIRMED, PerformanceReportStatus.FLAGGED}
        ]
        if [point.period for point in self.confirmed_series] != [
            report.period for report in confirmed_reports
        ]:
            raise ValueError("confirmed_series에는 각 월의 최신 확정 revision만 필요합니다.")
        for report, point in zip(confirmed_reports, self.confirmed_series, strict=True):
            current = report.current_revision
            if current is None or (
                point.report_id,
                point.report_revision_id,
                point.version,
                point.status,
                point.confirmed_payload,
                point.engagement_rate,
                point.confirmed_at,
            ) != (
                report.id,
                current.id,
                current.version,
                current.status,
                current.confirmed_payload,
                current.engagement_rate,
                current.confirmed_at,
            ):
                raise ValueError("confirmed_series 값은 report의 현재 revision과 같아야 합니다.")

        latest_flags = [
            flag
            for report in confirmed_reports
            if report.current_revision is not None
            for flag in report.current_revision.flags
        ]
        latest_drafts = [
            draft
            for report in confirmed_reports
            if report.current_revision is not None
            for draft in report.current_revision.inquiry_drafts
        ]
        if self.flags != latest_flags or self.inquiry_drafts != latest_drafts:
            raise ValueError("조회 집계에는 최신 revision의 flag와 문의 문안만 포함해야 합니다.")
        return self


class PerformanceReportResponse(StrictPerformanceModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: PerformanceReport
    error: None
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")


class PerformanceReportCreatedResponse(StrictPerformanceModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: PerformanceReportCreated
    error: None
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")


class PerformanceReportExtractedResponse(StrictPerformanceModel):
    """Strict success envelope for the public 16.3 extraction operation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: PerformanceReportExtracted
    error: None
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")


class PerformanceReportConfirmedResponse(StrictPerformanceModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: PerformanceReportConfirmed
    error: None
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")


class ContractPerformanceResponse(StrictPerformanceModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: ContractPerformance
    error: None
    request_id: str = Field(alias="requestId", pattern=r"^req_[a-f0-9]+$")
