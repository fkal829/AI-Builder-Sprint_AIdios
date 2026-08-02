import json
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml"
EXTRACTED_SCHEMA_PATH = (
    REPOSITORY_ROOT
    / "packages"
    / "contracts"
    / "schemas"
    / "performance-extracted-payload.schema.json"
)

LEGACY_EXTRACTED_FIELDS = {
    "impressions",
    "likes",
    "comments",
    "reach",
    "saves",
    "shares",
    "follower_net_change",
    "published_content_count",
}
LEGACY_CONFIRMED_FIELDS = {
    "impressions",
    "likes",
    "comments",
    "reach",
    "saves",
    "shares",
    "follower_net_change",
    "published_content_count",
    "inquiries",
    "reservations",
    "purchases",
}
CANONICAL_UNITS = {
    "ad_spend": "KRW",
    "impressions": "COUNT",
    "clicks": "COUNT",
    "ctr": "PERCENT",
    "cpc": "KRW",
    "published_content_count": "COUNT",
}


def load_openapi_schemas() -> dict:
    canonical = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    return canonical["components"]["schemas"]


def test_extracted_contract_adds_optional_ad_spend_and_clicks_compatibly() -> None:
    openapi = load_openapi_schemas()["PerformanceExtractedPayload"]
    shared = json.loads(EXTRACTED_SCHEMA_PATH.read_text(encoding="utf-8"))

    for schema in (openapi, shared):
        assert set(schema["required"]) == LEGACY_EXTRACTED_FIELDS
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == LEGACY_EXTRACTED_FIELDS | {"ad_spend", "clicks"}
        for key in ("ad_spend", "clicks"):
            assert key not in schema["required"]

    assert openapi["properties"]["ad_spend"] == {
        "$ref": "#/components/schemas/PerformanceNonNegativeMetricCandidate"
    }
    assert openapi["properties"]["clicks"] == {
        "$ref": "#/components/schemas/PerformanceNonNegativeMetricCandidate"
    }
    assert shared["properties"]["ad_spend"] == {
        "$ref": "#/$defs/PerformanceNonNegativeMetricCandidate"
    }
    assert shared["properties"]["clicks"] == {
        "$ref": "#/$defs/PerformanceNonNegativeMetricCandidate"
    }


def test_metric_item_contract_has_strict_shape_units_and_numeric_rules() -> None:
    schemas = load_openapi_schemas()
    item = schemas["PerformanceMetricItem"]

    assert schemas["PerformanceMetricItemUnit"] == {
        "type": "string",
        "enum": ["KRW", "COUNT", "PERCENT", "NUMBER"],
    }
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {"key", "label", "value", "unit"}
    assert item["properties"]["key"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
        "pattern": "^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$",
        "description": "같은 revision 안에서 고유한 소문자 snake_case slug",
    }
    assert item["properties"]["label"]["minLength"] == 1
    assert item["properties"]["label"]["maxLength"] == 50
    assert item["properties"]["label"]["pattern"] == (
        r"^(?!\s)(?!.*\s$)[^\u0000-\u001F\u007F]+$"
    )
    assert item["properties"]["value"] == {
        "type": ["number", "null"],
        "minimum": 0,
        "multipleOf": 0.000001,
        "description": "알 수 없으면 null. 값이 있으면 0 이상이고 소수점 이하 최대 6자리다.",
    }

    integer_rule = item["allOf"][0]
    assert integer_rule["if"]["properties"]["unit"]["enum"] == ["KRW", "COUNT"]
    assert integer_rule["then"]["properties"]["value"] == {
        "type": ["integer", "null"],
        "minimum": 0,
    }
    canonical_units = {
        rule["if"]["properties"]["key"]["const"]: rule["then"]["properties"]["unit"][
            "const"
        ]
        for rule in item["allOf"][1:]
    }
    assert canonical_units == CANONICAL_UNITS


def test_confirmed_contract_keeps_legacy_fields_and_adds_bounded_metric_items() -> None:
    schemas = load_openapi_schemas()
    input_schema = schemas["PerformanceConfirmedPayloadInput"]
    output_schema = schemas["PerformanceConfirmedPayload"]

    assert set(input_schema["required"]) == LEGACY_CONFIRMED_FIELDS
    assert set(output_schema["required"]) == LEGACY_CONFIRMED_FIELDS
    assert input_schema["additionalProperties"] is False
    assert output_schema["additionalProperties"] is False

    input_items = input_schema["properties"]["metric_items"]
    output_items = output_schema["properties"]["metric_items"]
    assert input_items["default"] == []
    assert input_items["maxItems"] == 50
    assert output_items["maxItems"] == 50
    assert input_items["items"] == {"$ref": "#/components/schemas/PerformanceMetricItem"}
    assert output_items["items"] == {"$ref": "#/components/schemas/PerformanceMetricItem"}
    assert "metric_items" not in input_schema["required"]
    assert "metric_items" not in output_schema["required"]
