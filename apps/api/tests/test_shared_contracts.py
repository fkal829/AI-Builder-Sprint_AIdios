import json
from pathlib import Path

from app.core.enums import (
    AdjustmentRequestStatus,
    AnalysisStatus,
    AuditEventType,
    ContractStatus,
    InternalSignatureStatus,
    ModusignStatus,
    ObligationStatus,
)
from app.services.state_machine import (
    ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
    ALLOWED_ANALYSIS_TASK_TRANSITIONS,
    ALLOWED_CONTRACT_TRANSITIONS,
    ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
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
    shared = json.loads((SHARED_CONTRACTS / "state-machines.json").read_text(encoding="utf-8"))

    assert _normalize_shared_transitions(shared["contract"]) == _as_string_transitions(
        ALLOWED_CONTRACT_TRANSITIONS
    )
    assert _normalize_shared_transitions(shared["adjustment_request"]) == _as_string_transitions(
        ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS
    )
    assert _normalize_shared_transitions(shared["internal_signature"]) == _as_string_transitions(
        ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS
    )
    assert _normalize_shared_transitions(shared["modusign"]) == _as_string_transitions(
        ALLOWED_MODUSIGN_TRANSITIONS
    )
    assert _normalize_shared_transitions(shared["obligation"]) == _as_string_transitions(
        ALLOWED_OBLIGATION_TRANSITIONS
    )
    assert _normalize_shared_transitions(shared["analysis_task"]) == _as_string_transitions(
        ALLOWED_ANALYSIS_TASK_TRANSITIONS
    )


def test_shared_state_machines_include_every_enum_member() -> None:
    shared = json.loads((SHARED_CONTRACTS / "state-machines.json").read_text(encoding="utf-8"))

    assert set(shared["contract"]) == {status.value for status in ContractStatus}
    assert set(shared["adjustment_request"]) == {status.value for status in AdjustmentRequestStatus}
    assert set(shared["internal_signature"]) == {status.value for status in InternalSignatureStatus}
    assert set(shared["modusign"]) == {status.value for status in ModusignStatus}
    assert set(shared["obligation"]) == {status.value for status in ObligationStatus}
    assert set(shared["analysis_task"]) == {status.value for status in AnalysisStatus}


def test_evidence_schemas_use_api_snake_case() -> None:
    for filename in ("extracted-term.schema.json", "review-item.schema.json"):
        schema = json.loads((SHARED_CONTRACTS / "schemas" / filename).read_text(encoding="utf-8"))
        properties = schema["properties"]

        assert "source_page" in properties
        assert "source_text" in properties
        assert "sourcePage" not in properties
        assert "sourceText" not in properties


def test_extracted_term_schema_has_structured_fields_and_values() -> None:
    schema = json.loads(
        (SHARED_CONTRACTS / "schemas" / "extracted-term.schema.json").read_text(encoding="utf-8")
    )

    assert schema["additionalProperties"] is False
    assert "enum" in schema["properties"]["field"]
    assert schema["properties"]["value_type"]["enum"] == [
        "TEXT",
        "DATE",
        "MONEY_KRW",
        "INTEGER",
        "PERCENT",
        "BOOLEAN",
    ]
    assert "confidence" in schema["properties"]


def test_review_schema_distinguishes_source_and_model_confidence() -> None:
    schema = json.loads(
        (SHARED_CONTRACTS / "schemas" / "review-item.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["detection_method"]["enum"] == [
        "DETERMINISTIC",
        "MODEL",
        "HYBRID",
    ]
    assert "source_confidence" in schema["required"]
    assert "source_confidence" in schema["properties"]
    assert "model_confidence" in schema["properties"]


def test_openapi_declares_security_and_separate_public_contracts() -> None:
    openapi = (SHARED_CONTRACTS / "openapi" / "openapi.yaml").read_text(encoding="utf-8")

    assert "BearerAuth:" in openapi
    assert "ModusignWebhookSecret:" in openapi
    assert "AdjustmentToken:" in openapi
    assert "ObligationToken:" in openapi
    assert "PublicSubmissionResponse:" in openapi
    assert "Evidence:" not in openapi
    assert "requestId:" in openapi


def test_openapi_declares_every_audit_event_type() -> None:
    openapi = (SHARED_CONTRACTS / "openapi" / "openapi.yaml").read_text(encoding="utf-8")

    for event_type in AuditEventType:
        assert f"        - {event_type.value}" in openapi
