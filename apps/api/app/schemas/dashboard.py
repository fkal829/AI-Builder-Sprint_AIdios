from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ReviewSignalType


class Dashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    signing: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    completed: int = Field(ge=0)
    expiring_soon: int = Field(ge=0)
    unresolved_signals: int = Field(ge=0)
    adjustment_requested_clauses: int = Field(ge=0)
    adjustment_agreed_clauses: int = Field(ge=0)
    adjustment_rejected_clauses: int = Field(ge=0)
    obligation_pending: int = Field(ge=0)
    obligation_submitted: int = Field(ge=0)
    obligation_approved: int = Field(ge=0)
    total_committed: int = Field(ge=0)
    payment_condition_met_amount: int = Field(ge=0)
    most_common_signal: ReviewSignalType | None = None
