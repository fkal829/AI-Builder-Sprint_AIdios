import pytest

from app.core.enums import (
    AdjustmentRequestStatus,
    ContractStatus,
    InternalSignatureStatus,
    ModusignStatus,
    ObligationStatus,
)
from app.services.state_machine import (
    ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
    ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
    ALLOWED_MODUSIGN_TRANSITIONS,
    ALLOWED_OBLIGATION_TRANSITIONS,
    InvalidStatusTransition,
    ensure_contract_transition,
    ensure_transition,
)


def test_allows_expected_contract_transition() -> None:
    ensure_contract_transition(ContractStatus.DRAFT, ContractStatus.ANALYZING)


def test_rejects_skipped_contract_transition() -> None:
    with pytest.raises(InvalidStatusTransition):
        ensure_contract_transition(ContractStatus.DRAFT, ContractStatus.SIGNED)


@pytest.mark.parametrize(
    ("current", "target", "transitions"),
    [
        (
            AdjustmentRequestStatus.OPENED,
            AdjustmentRequestStatus.RESPONDED,
            ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
        ),
        (
            InternalSignatureStatus.REQUESTING,
            InternalSignatureStatus.SIGNING,
            ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
        ),
        (
            ModusignStatus.ON_GOING,
            ModusignStatus.COMPLETED,
            ALLOWED_MODUSIGN_TRANSITIONS,
        ),
        (
            ObligationStatus.SUBMITTED,
            ObligationStatus.APPROVED,
            ALLOWED_OBLIGATION_TRANSITIONS,
        ),
    ],
)
def test_allows_domain_state_transitions(current, target, transitions) -> None:
    ensure_transition(current, target, transitions)


@pytest.mark.parametrize(
    ("current", "target", "transitions"),
    [
        (
            AdjustmentRequestStatus.RESPONDED,
            AdjustmentRequestStatus.OPENED,
            ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
        ),
        (
            InternalSignatureStatus.COMPLETED,
            InternalSignatureStatus.SIGNING,
            ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
        ),
        (
            ModusignStatus.COMPLETED,
            ModusignStatus.ON_GOING,
            ALLOWED_MODUSIGN_TRANSITIONS,
        ),
        (
            ObligationStatus.PENDING,
            ObligationStatus.APPROVED,
            ALLOWED_OBLIGATION_TRANSITIONS,
        ),
    ],
)
def test_rejects_domain_state_transitions(current, target, transitions) -> None:
    with pytest.raises(InvalidStatusTransition):
        ensure_transition(current, target, transitions)
