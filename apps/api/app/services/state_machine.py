from app.core.enums import ContractStatus
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


class InvalidStatusTransition(ValueError):
    code = ErrorCode.INVALID_STATUS_TRANSITION


def ensure_contract_transition(
    current: ContractStatus,
    target: ContractStatus,
) -> None:
    if target not in ALLOWED_CONTRACT_TRANSITIONS[current]:
        raise InvalidStatusTransition(f"{current}에서 {target}(으)로 변경할 수 없습니다.")
