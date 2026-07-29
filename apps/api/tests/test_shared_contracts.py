import json
from pathlib import Path

from app.core.enums import (
    AdjustmentRequestStatus,
    ContractStatus,
    ModusignStatus,
    ObligationStatus,
)
from app.services.state_machine import (
    ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
    ALLOWED_CONTRACT_TRANSITIONS,
    ALLOWED_MODUSIGN_TRANSITIONS,
    ALLOWED_OBLIGATION_TRANSITIONS,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SHARED_CONTRACTS = REPOSITORY_ROOT / "packages" / "contracts"


def _as_string_transitions(transitions):
    return {
        current.value: sorted(target.value for target in targets)
        for current, targets in transitions.items()
    }


def _normalize_shared_transitions(transitions):
    return {current: sorted(targets) for current, targets in transitions.items()}


def test_shared_state_machines_match_backend() -> None:
    shared = json.loads((SHARED_CONTRACTS / "state-machines.json").read_text())

    assert _normalize_shared_transitions(shared["contract"]) == _as_string_transitions(
        ALLOWED_CONTRACT_TRANSITIONS
    )
    assert _normalize_shared_transitions(
        shared["adjustment_request"]
    ) == _as_string_transitions(
        ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS
    )
    assert _normalize_shared_transitions(shared["signature"]) == _as_string_transitions(
        ALLOWED_MODUSIGN_TRANSITIONS
    )
    assert _normalize_shared_transitions(shared["obligation"]) == _as_string_transitions(
        ALLOWED_OBLIGATION_TRANSITIONS
    )


def test_shared_state_machines_include_every_enum_member() -> None:
    shared = json.loads((SHARED_CONTRACTS / "state-machines.json").read_text())

    assert set(shared["contract"]) == {status.value for status in ContractStatus}
    assert set(shared["adjustment_request"]) == {
        status.value for status in AdjustmentRequestStatus
    }
    assert set(shared["signature"]) == {status.value for status in ModusignStatus}
    assert set(shared["obligation"]) == {status.value for status in ObligationStatus}


def test_evidence_schemas_use_api_snake_case() -> None:
    for filename in ("extracted-term.schema.json", "review-item.schema.json"):
        schema = json.loads((SHARED_CONTRACTS / "schemas" / filename).read_text())
        properties = schema["properties"]

        assert "source_page" in properties
        assert "source_text" in properties
        assert "sourcePage" not in properties
        assert "sourceText" not in properties
