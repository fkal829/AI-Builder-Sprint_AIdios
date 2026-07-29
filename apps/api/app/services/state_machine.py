from collections.abc import Mapping
from enum import StrEnum

from app.core.enums import (
    AdjustmentRequestStatus,
    AnalysisStatus,
    ContractStatus,
    InternalSignatureStatus,
    ModusignStatus,
    ObligationStatus,
)
from app.core.errors import ErrorCode

ALLOWED_CONTRACT_TRANSITIONS: dict[ContractStatus, set[ContractStatus]] = {
    ContractStatus.DRAFT: {ContractStatus.ANALYZING},
    ContractStatus.ANALYZING: {ContractStatus.REVIEW_REQUIRED},
    ContractStatus.REVIEW_REQUIRED: {
        ContractStatus.NEGOTIATING,
        ContractStatus.READY_TO_SIGN,
    },
    ContractStatus.NEGOTIATING: {ContractStatus.READY_TO_SIGN},
    ContractStatus.READY_TO_SIGN: {ContractStatus.SIGNING},
    ContractStatus.SIGNING: {ContractStatus.SIGNED},
    ContractStatus.SIGNED: {ContractStatus.IN_PROGRESS},
    ContractStatus.IN_PROGRESS: {
        ContractStatus.COMPLETED,
        ContractStatus.RENEWAL_DUE,
    },
    ContractStatus.COMPLETED: set(),
    ContractStatus.RENEWAL_DUE: set(),
}

ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS: dict[
    AdjustmentRequestStatus, set[AdjustmentRequestStatus]
] = {
    AdjustmentRequestStatus.DRAFT: {AdjustmentRequestStatus.SENT},
    AdjustmentRequestStatus.SENT: {
        AdjustmentRequestStatus.OPENED,
        AdjustmentRequestStatus.EXPIRED,
    },
    AdjustmentRequestStatus.OPENED: {
        AdjustmentRequestStatus.RESPONDED,
        AdjustmentRequestStatus.EXPIRED,
    },
    AdjustmentRequestStatus.RESPONDED: {AdjustmentRequestStatus.CONFIRMED},
    AdjustmentRequestStatus.CONFIRMED: set(),
    AdjustmentRequestStatus.EXPIRED: set(),
}

ALLOWED_MODUSIGN_TRANSITIONS: dict[ModusignStatus, set[ModusignStatus]] = {
    ModusignStatus.DRAFT: {ModusignStatus.SCHEDULED, ModusignStatus.ON_PROCESSING},
    ModusignStatus.SCHEDULED: {
        ModusignStatus.ON_PROCESSING,
        ModusignStatus.ABORTED,
        ModusignStatus.PROCESSING_FAILED,
    },
    ModusignStatus.ON_PROCESSING: {
        ModusignStatus.ON_GOING,
        ModusignStatus.ABORTED,
        ModusignStatus.PROCESSING_FAILED,
    },
    ModusignStatus.ON_GOING: {
        ModusignStatus.COMPLETED,
        ModusignStatus.ABORTED,
        ModusignStatus.PROCESSING_FAILED,
    },
    ModusignStatus.COMPLETED: set(),
    ModusignStatus.ABORTED: set(),
    ModusignStatus.PROCESSING_FAILED: set(),
}

ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS: dict[
    InternalSignatureStatus, set[InternalSignatureStatus]
] = {
    InternalSignatureStatus.REQUEST_READY: {InternalSignatureStatus.REQUESTING},
    InternalSignatureStatus.REQUESTING: {
        InternalSignatureStatus.SIGNING,
        InternalSignatureStatus.FAILED,
    },
    InternalSignatureStatus.SIGNING: {
        InternalSignatureStatus.COMPLETED,
        InternalSignatureStatus.ABORTED,
        InternalSignatureStatus.FAILED,
    },
    InternalSignatureStatus.COMPLETED: set(),
    InternalSignatureStatus.ABORTED: set(),
    InternalSignatureStatus.FAILED: set(),
}

ALLOWED_OBLIGATION_TRANSITIONS: dict[ObligationStatus, set[ObligationStatus]] = {
    ObligationStatus.PENDING: {ObligationStatus.SUBMITTED},
    ObligationStatus.SUBMITTED: {
        ObligationStatus.APPROVED,
        ObligationStatus.DISPUTED,
    },
    ObligationStatus.APPROVED: set(),
    ObligationStatus.DISPUTED: set(),
}

ALLOWED_ANALYSIS_TASK_TRANSITIONS: dict[AnalysisStatus, set[AnalysisStatus]] = {
    AnalysisStatus.QUEUED: {AnalysisStatus.PROCESSING},
    AnalysisStatus.PROCESSING: {AnalysisStatus.COMPLETED, AnalysisStatus.FAILED},
    AnalysisStatus.COMPLETED: set(),
    AnalysisStatus.FAILED: set(),
}


class InvalidStatusTransition(ValueError):
    code = ErrorCode.INVALID_STATUS_TRANSITION


def ensure_contract_transition(
    current: ContractStatus,
    target: ContractStatus,
) -> None:
    if target not in ALLOWED_CONTRACT_TRANSITIONS[current]:
        message = f"{current}에서 {target}(으)로 변경할 수 없습니다."
        raise InvalidStatusTransition(message)


def ensure_transition[StatusT: StrEnum](
    current: StatusT,
    target: StatusT,
    transitions: Mapping[StatusT, set[StatusT]],
) -> None:
    if target not in transitions[current]:
        message = f"{current}에서 {target}(으)로 변경할 수 없습니다."
        raise InvalidStatusTransition(message)
