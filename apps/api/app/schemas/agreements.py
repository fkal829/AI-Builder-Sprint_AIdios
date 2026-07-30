from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.enums import (
    AdjustmentResolution,
    AgreementClauseCategory,
    AgreementClauseDisposition,
    AgreementClauseOutcome,
)

AGREEMENT_TITLE = "광고대행 계약조건 변경·확인 합의서"


class AdjustmentConfirmationItem(BaseModel):
    review_item_id: UUID
    resolution: AdjustmentResolution


class AdjustmentConfirmation(BaseModel):
    adjustment_request_id: UUID
    confirmed_items: list[AdjustmentConfirmationItem] = Field(min_length=1, max_length=4)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def review_items_are_unique(self) -> "AdjustmentConfirmation":
        item_ids = [item.review_item_id for item in self.confirmed_items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("confirmed_items의 review_item_id는 중복될 수 없습니다.")
        return self


class OriginalContractReference(BaseModel):
    title: str = Field(min_length=1)
    signed_date: date
    document_id: UUID


class AgreementConditionSummary(BaseModel):
    term_and_payment: str = Field(min_length=1)
    deliverables_and_reporting: str = Field(min_length=1)
    termination_and_renewal: str = Field(min_length=1)
    rights_safety_and_liability: str = Field(min_length=1)


class AgreementClause(BaseModel):
    review_item_id: UUID
    category: AgreementClauseCategory
    outcome: AgreementClauseOutcome
    disposition: AgreementClauseDisposition
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)
    reason: str | None = None

    @model_validator(mode="after")
    def disposition_matches_outcome(self) -> "AgreementClause":
        if self.outcome == AgreementClauseOutcome.AGREED:
            if self.disposition != AgreementClauseDisposition.AGREED:
                raise ValueError("AGREED 조항의 disposition은 AGREED여야 합니다.")
        elif self.disposition not in {
            AgreementClauseDisposition.REJECTED,
            AgreementClauseDisposition.WITHDRAWN,
        }:
            raise ValueError("KEPT_ORIGINAL 조항은 REJECTED 또는 WITHDRAWN이어야 합니다.")
        if self.disposition == AgreementClauseDisposition.REJECTED and not _has_text(
            self.reason
        ):
            raise ValueError("REJECTED 조항에는 사유가 필요합니다.")
        return self


class Agreement(BaseModel):
    id: UUID
    version: int = Field(ge=1)
    contract_id: UUID
    title: Literal[AGREEMENT_TITLE]
    original_contract: OriginalContractReference
    condition_summary: AgreementConditionSummary
    clauses: list[AgreementClause] = Field(min_length=1, max_length=4)
    unchanged_terms_policy: str = Field(min_length=1)
    signature_roles: list[Literal["OWNER", "AGENCY"]] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def contains_both_signature_roles(self) -> "Agreement":
        if set(self.signature_roles) != {"OWNER", "AGENCY"}:
            raise ValueError("OWNER와 AGENCY 서명란이 각각 하나씩 필요합니다.")
        return self


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())
