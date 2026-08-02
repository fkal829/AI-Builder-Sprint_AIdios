import json
from pathlib import Path

import yaml

from app.core.enums import (
    AdjustmentRequestStatus,
    AnalysisStatus,
    AuditEventType,
    ContractStatus,
    ExtractedField,
    InternalSignatureStatus,
    ModusignStatus,
    ObligationStatus,
    PerformanceMetricVerificationStatus,
)
from app.schemas.analysis import DocumentClause
from app.schemas.performance import PerformanceExtractedPayload
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


def test_document_clause_schema_matches_runtime_and_openapi() -> None:
    schema = json.loads(
        (SHARED_CONTRACTS / "schemas" / "document-clause.schema.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_schema = DocumentClause.model_json_schema()
    openapi = yaml.safe_load(
        (SHARED_CONTRACTS / "openapi" / "openapi.yaml").read_text(encoding="utf-8")
    )["components"]["schemas"]["DocumentClause"]

    expected_fields = {
        "id",
        "document_id",
        "ordinal",
        "heading",
        "title",
        "source_page",
        "source_text",
        "confidence",
    }
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == expected_fields
    assert set(schema["required"]) == expected_fields
    assert set(runtime_schema["properties"]) == expected_fields
    assert set(runtime_schema["required"]) == expected_fields
    assert set(openapi["properties"]) == expected_fields
    assert set(openapi["required"]) == expected_fields


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
    assert set(schema["properties"]["field"]["enum"]) == {field.value for field in ExtractedField}
    assert {
        "id",
        "contract_id",
        "document_id",
        "source_type",
        "source_page",
        "source_text",
        "confidence",
    } <= set(schema["required"])


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
    assert {
        "model_limitations",
        "basis_type",
        "basis_text",
        "basis_citation",
        "related_extracted_term_ids",
        "source_document_id",
        "user_choice",
    } <= set(schema["required"])


def test_performance_extracted_payload_schema_matches_runtime_and_openapi() -> None:
    schema = json.loads(
        (SHARED_CONTRACTS / "schemas" / "performance-extracted-payload.schema.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_schema = PerformanceExtractedPayload.model_json_schema()
    openapi = yaml.safe_load(
        (SHARED_CONTRACTS / "openapi" / "openapi.yaml").read_text(encoding="utf-8")
    )["components"]["schemas"]["PerformanceExtractedPayload"]

    legacy_fields = {
        "impressions",
        "likes",
        "comments",
        "reach",
        "saves",
        "shares",
        "follower_net_change",
        "published_content_count",
    }
    expected_fields = legacy_fields | {"ad_spend", "clicks"}
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == expected_fields
    assert set(schema["required"]) == legacy_fields
    assert set(runtime_schema["properties"]) == expected_fields
    assert set(runtime_schema["required"]) == legacy_fields
    assert set(openapi["properties"]) == expected_fields
    assert set(openapi["required"]) == legacy_fields


def test_performance_extracted_payload_schema_keeps_metric_boundaries() -> None:
    schema = json.loads(
        (SHARED_CONTRACTS / "schemas" / "performance-extracted-payload.schema.json").read_text(
            encoding="utf-8"
        )
    )
    definitions = schema["$defs"]
    openapi_definitions = yaml.safe_load(
        (SHARED_CONTRACTS / "openapi" / "openapi.yaml").read_text(encoding="utf-8")
    )["components"]["schemas"]
    non_negative = definitions["PerformanceNonNegativeMetricCandidate"]
    signed = definitions["PerformanceSignedMetricCandidate"]
    required_candidate_fields = {
        "value",
        "source_page",
        "source_text",
        "confidence",
        "verification_status",
    }

    assert non_negative["additionalProperties"] is False
    assert signed["additionalProperties"] is False
    assert set(non_negative["required"]) == required_candidate_fields
    assert set(signed["required"]) == required_candidate_fields
    assert non_negative["properties"]["value"] == {
        "type": ["integer", "null"],
        "format": "int64",
        "minimum": 0,
        "maximum": 9223372036854775807,
    }
    assert signed["properties"]["value"] == {
        "type": ["integer", "null"],
        "format": "int64",
        "minimum": -9223372036854775808,
        "maximum": 9223372036854775807,
    }
    assert schema["properties"]["published_content_count"] == {
        "$ref": "#/$defs/PerformanceNonNegativeMetricCandidate"
    }
    assert schema["properties"]["follower_net_change"] == {
        "$ref": "#/$defs/PerformanceSignedMetricCandidate"
    }
    assert set(definitions["PerformanceMetricVerificationStatus"]["enum"]) == {
        status.value for status in PerformanceMetricVerificationStatus
    }

    for name, definition in (
        ("PerformanceNonNegativeMetricCandidate", non_negative),
        ("PerformanceSignedMetricCandidate", signed),
    ):
        openapi_definition = openapi_definitions[name]
        assert definition["additionalProperties"] == openapi_definition["additionalProperties"]
        assert set(definition["properties"]) == set(openapi_definition["properties"])
        assert set(definition["required"]) == set(openapi_definition["required"])
        assert definition["properties"]["value"] == openapi_definition["properties"]["value"]
        assert definition["allOf"] == openapi_definition["allOf"]

    non_negative_rules = {
        rule["if"]["properties"]["verification_status"]["const"]: rule["then"]
        for rule in non_negative["allOf"]
    }
    assert non_negative_rules["NOT_FOUND"]["properties"] == {
        "value": {"type": "null"},
        "source_page": {"type": "null"},
        "source_text": {"type": "null"},
    }
    assert non_negative_rules["NEEDS_CHECK"]["properties"]["source_page"] == {
        "type": "integer",
        "minimum": 1,
    }


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
