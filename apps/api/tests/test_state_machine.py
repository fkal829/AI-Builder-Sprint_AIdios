import pytest

from app.core.enums import ContractStatus
from app.services.state_machine import InvalidStatusTransition, ensure_contract_transition


def test_allows_expected_contract_transition() -> None:
    ensure_contract_transition(ContractStatus.DRAFT, ContractStatus.ANALYZING)


def test_rejects_skipped_contract_transition() -> None:
    with pytest.raises(InvalidStatusTransition):
        ensure_contract_transition(ContractStatus.DRAFT, ContractStatus.SIGNED)
