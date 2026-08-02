import logging
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from uvicorn.logging import AccessFormatter

from app.core.exceptions import ResourceNotFound
from app.core.http import CANONICAL_OPERATION_IDS, install_http_contract
from app.core.logging import (
    PUBLIC_TOKEN_REDACTION,
    PublicTokenPathFilter,
    install_uvicorn_access_log_filter,
    redact_public_token_paths,
)
from app.main import app, invalid_status_transition_handler
from app.schemas.common import ApiError, ApiResponse
from app.services.state_machine import InvalidStatusTransition

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _implemented_canonical_operations(canonical: dict):
    """Yield operations that are expected to exist in the FastAPI runtime now."""

    for path, path_item in canonical["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if operation.get("x-implementation-status") == "planned":
                continue
            yield path, method, operation


def test_canonical_openapi_marks_no_operations_as_planned() -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    declared_statuses = {
        operation.get("x-implementation-status")
        for path_item in canonical["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    planned = {
        (method.upper(), path): operation["operationId"]
        for path, path_item in canonical["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
        and operation.get("x-implementation-status") == "planned"
    }

    assert declared_statuses <= {None, "planned"}
    assert planned == {}


def test_public_adjustment_original_text_contract_matches_runtime() -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )["components"]["schemas"]["PublicAdjustment"]
    canonical_item = canonical["properties"]["items"]["items"]
    runtime_item = app.openapi()["components"]["schemas"]["PublicAdjustmentItem"]

    expected_fields = {"item_id", "before_text", "source_page", "request_text"}
    assert set(canonical_item["properties"]) == expected_fields
    assert set(canonical_item["required"]) == expected_fields
    assert set(runtime_item["properties"]) == expected_fields
    assert set(runtime_item["required"]) == expected_fields
    assert canonical_item["properties"]["before_text"]["type"] == ["string", "null"]
    assert {entry["type"] for entry in runtime_item["properties"]["before_text"]["anyOf"]} == {
        "string",
        "null",
    }
    assert canonical_item["properties"]["source_page"]["type"] == ["integer", "null"]
    assert {entry["type"] for entry in runtime_item["properties"]["source_page"]["anyOf"]} == {
        "integer",
        "null",
    }


def test_performance_extraction_runtime_contract_matches_canonical() -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    path = "/contracts/{contract_id}/performance-reports/{report_id}/extract"
    canonical_operation = canonical["paths"][path]["post"]
    runtime_operation = app.openapi()["paths"][f"/api/v1{path}"]["post"]

    assert runtime_operation["operationId"] == canonical_operation["operationId"]
    assert runtime_operation["summary"] == canonical_operation["summary"]
    assert set(runtime_operation["responses"]) == set(canonical_operation["responses"])
    assert "requestBody" not in runtime_operation

    runtime_schemas = app.openapi()["components"]["schemas"]
    assert runtime_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PerformanceReportExtractedResponse"
    }
    success_schema = runtime_schemas["PerformanceReportExtractedResponse"]
    assert success_schema["properties"]["data"] == {
        "$ref": "#/components/schemas/PerformanceReportExtracted"
    }
    assert success_schema["properties"]["error"]["type"] == "null"

    for status in {"401", "404", "409", "422", "502", "503"}:
        assert runtime_operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
    error_schema = runtime_schemas["ErrorResponse"]
    assert error_schema["properties"]["data"]["type"] == "null"
    assert error_schema["properties"]["error"] == {"$ref": "#/components/schemas/ApiError"}


@pytest.mark.parametrize(
    ("path", "method", "success_status", "success_schema", "data_schema"),
    [
        (
            "/contracts/{contract_id}/performance-reports",
            "post",
            "201",
            "PerformanceReportCreatedResponse",
            "PerformanceReportCreated",
        ),
        (
            "/contracts/{contract_id}/performance-reports/{report_id}/extract",
            "post",
            "200",
            "PerformanceReportExtractedResponse",
            "PerformanceReportExtracted",
        ),
        (
            "/contracts/{contract_id}/performance-reports/{report_id}",
            "patch",
            "200",
            "PerformanceReportConfirmedResponse",
            "PerformanceReportConfirmed",
        ),
        (
            "/contracts/{contract_id}/performance",
            "get",
            "200",
            "ContractPerformanceResponse",
            "ContractPerformance",
        ),
    ],
)
def test_performance_runtime_response_schemas_match_canonical(
    path: str,
    method: str,
    success_status: str,
    success_schema: str,
    data_schema: str,
) -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    runtime = app.openapi()
    canonical_operation = canonical["paths"][path][method]
    runtime_operation = runtime["paths"][f"/api/v1{path}"][method]

    for status, canonical_response in canonical_operation["responses"].items():
        if "$ref" in canonical_response:
            response_name = canonical_response["$ref"].rsplit("/", 1)[1]
            canonical_response = canonical["components"]["responses"][response_name]
        expected_schema = canonical_response["content"]["application/json"]["schema"]
        actual_schema = runtime_operation["responses"][status]["content"]["application/json"][
            "schema"
        ]
        assert actual_schema == expected_schema, (method, path, status)

    assert runtime_operation["responses"][success_status]["content"]["application/json"][
        "schema"
    ] == {"$ref": f"#/components/schemas/{success_schema}"}
    generated_success = runtime["components"]["schemas"][success_schema]
    assert set(generated_success["required"]) == {"data", "error", "requestId"}
    assert generated_success["properties"]["data"] == {
        "$ref": f"#/components/schemas/{data_schema}"
    }
    assert generated_success["properties"]["error"]["type"] == "null"

    generated_error = runtime["components"]["schemas"]["ErrorResponse"]
    assert set(generated_error["required"]) == {"data", "error", "requestId"}
    assert generated_error["properties"]["data"]["type"] == "null"
    assert generated_error["properties"]["error"] == {"$ref": "#/components/schemas/ApiError"}


def test_runtime_api_error_codes_match_canonical_public_enum() -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    canonical_codes = canonical["components"]["schemas"]["ApiError"]["properties"]["code"]["enum"]
    runtime_codes = app.openapi()["components"]["schemas"]["ApiError"]["properties"]["code"]["enum"]

    assert runtime_codes == canonical_codes
    with pytest.raises(ValidationError):
        ApiError(code="INVALID", message="허용되지 않는 공개 오류 코드")


@pytest.mark.parametrize(
    ("schema_name", "field_name"),
    [
        ("PerformanceReportRevision", "engagement_rate"),
        ("PerformanceConfirmedSeriesPoint", "engagement_rate"),
        ("PerformanceFlag", "previous_engagement_rate"),
        ("PerformanceFlag", "current_engagement_rate"),
    ],
)
def test_runtime_engagement_rates_are_numeric_in_response_schema(
    schema_name: str,
    field_name: str,
) -> None:
    field_schema = app.openapi()["components"]["schemas"][schema_name]["properties"][field_name]
    variants = field_schema["anyOf"]

    assert {variant["type"] for variant in variants} == {"number", "null"}
    numeric_schema = next(variant for variant in variants if variant["type"] == "number")
    assert numeric_schema["minimum"] == 0
    assert numeric_schema["x-decimal-places"] == 6


def test_performance_upload_runtime_multipart_schema_matches_canonical_constraints() -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    canonical_schema = canonical["paths"]["/contracts/{contract_id}/performance-reports"]["post"][
        "requestBody"
    ]["content"]["multipart/form-data"]["schema"]
    runtime_schema = app.openapi()["paths"]["/api/v1/contracts/{contract_id}/performance-reports"][
        "post"
    ]["requestBody"]["content"]["multipart/form-data"]["schema"]
    canonical_period = canonical["components"]["schemas"]["PerformancePeriod"]

    assert runtime_schema["type"] == canonical_schema["type"] == "object"
    assert runtime_schema["additionalProperties"] is False
    assert canonical_schema["additionalProperties"] is False
    assert runtime_schema["required"] == canonical_schema["required"] == ["period", "file"]
    assert runtime_schema["properties"]["period"] == canonical_period
    assert runtime_schema["properties"]["file"] == canonical_schema["properties"]["file"]


async def test_invalid_transition_body_and_header_share_request_id() -> None:
    test_app = FastAPI()
    install_http_contract(test_app)
    test_app.add_exception_handler(
        InvalidStatusTransition,
        invalid_status_transition_handler,
    )

    @test_app.get("/conflict")
    async def conflict() -> None:
        raise InvalidStatusTransition("현재 상태에서는 처리할 수 없습니다.")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/conflict")

    assert response.status_code == 409
    assert response.json()["requestId"] == response.headers["X-Request-ID"]


async def test_performance_success_and_error_responses_are_never_cached() -> None:
    test_app = FastAPI()
    install_http_contract(test_app)

    @test_app.get("/api/v1/contracts/contract-id/performance")
    async def performance_success() -> dict[str, bool]:
        return {"ok": True}

    @test_app.post("/api/v1/contracts/contract-id/performance-reports")
    async def performance_error() -> None:
        raise ResourceNotFound()

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as client:
        success = await client.get("/api/v1/contracts/contract-id/performance")
        error = await client.post("/api/v1/contracts/contract-id/performance-reports")

    assert success.status_code == 200
    assert error.status_code == 404
    assert success.headers["Cache-Control"] == "no-store"
    assert error.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/public/adjustment-requests/raw-adjustment-token",
        "/api/v1/public/adjustment-requests/raw-adjustment-token/open?from=demo",
        "/api/v1/public/adjustment-requests/raw-adjustment-token/responses",
        "/api/v1/public/obligations/raw-obligation-token/evidence",
        "/custom/prefix/public/obligations/raw-obligation-token/evidence",
        "/api/v1/_mock/storage/raw-storage-access-token",
        "/custom/prefix/_mock/storage/raw-storage-access-token?download=1",
    ],
)
def test_public_token_path_filter_redacts_uvicorn_access_records(path: str) -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", path, "1.1", 200),
        exc_info=None,
    )

    assert PublicTokenPathFilter().filter(record) is True
    rendered = AccessFormatter().format(record)

    assert "raw-adjustment-token" not in rendered
    assert "raw-obligation-token" not in rendered
    assert "raw-storage-access-token" not in rendered
    assert PUBLIC_TOKEN_REDACTION in rendered


def test_public_token_path_redaction_leaves_non_public_paths_unchanged() -> None:
    path = "/api/v1/contracts/00000000-0000-4000-8000-000000000041"

    assert redact_public_token_paths(path) == path


def test_uvicorn_access_filter_installation_is_idempotent() -> None:
    logger = logging.getLogger("uvicorn.access")

    install_uvicorn_access_log_filter()
    install_uvicorn_access_log_filter()

    installed = [
        item for item in logger.filters if getattr(item, "_ansim_public_token_path_filter", False)
    ]
    assert len(installed) == 1


def test_api_response_accepts_success_and_error_envelopes() -> None:
    success = ApiResponse[dict[str, bool]](
        data={"ok": True},
        error=None,
        request_id="req_123abc",
    )
    failure = ApiResponse[None](
        data=None,
        error=ApiError(code="NOT_FOUND", message="찾을 수 없습니다."),
        request_id="req_456def",
    )

    assert success.error is None
    assert failure.data is None


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (None, None),
        ({"ok": True}, ApiError(code="VALIDATION_ERROR", message="잘못된 응답")),
    ],
)
def test_api_response_rejects_ambiguous_envelopes(data, error) -> None:
    with pytest.raises(
        ValidationError,
        match="data 또는 error 중 정확히 하나",
    ):
        ApiResponse[dict[str, bool]](
            data=data,
            error=error,
            request_id="req_123abc",
        )


def test_fastapi_operation_ids_match_canonical_openapi() -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        (method.upper(), f"/api/v1{path}"): operation["operationId"]
        for path, method, operation in _implemented_canonical_operations(canonical)
    }
    relative_expected = {
        (method, path.removeprefix("/api/v1")): operation_id
        for (method, path), operation_id in expected.items()
    }
    generated = {
        (method.upper(), path): operation["operationId"]
        for path, path_item in app.openapi()["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert CANONICAL_OPERATION_IDS == relative_expected
    assert {key: expected[key] for key in generated} == generated
    assert set(expected) == set(generated)
    assert CANONICAL_OPERATION_IDS[("GET", "/dashboard")] == "getDashboard"


@pytest.mark.parametrize(
    ("path", "method", "statuses"),
    [
        (
            "/api/v1/contracts/{contract_id}/obligations/{obligation_id}/evidence-link",
            "post",
            ("201", "401", "404", "409", "422"),
        ),
        (
            "/api/v1/public/obligations/{token}/evidence",
            "post",
            ("200", "404", "409", "410", "422"),
        ),
    ],
)
def test_runtime_openapi_declares_no_store_for_sensitive_responses(
    path: str,
    method: str,
    statuses: tuple[str, ...],
) -> None:
    responses = app.openapi()["paths"][path][method]["responses"]

    for status in statuses:
        cache_control = responses[status]["headers"]["Cache-Control"]
        assert cache_control["schema"]["example"] == "no-store"


def test_runtime_openapi_response_statuses_and_sensitive_headers_match_canonical() -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    generated = app.openapi()

    for path, method, operation in _implemented_canonical_operations(canonical):
        runtime_path = generated["paths"][f"/api/v1{path}"]
        expected_responses = operation["responses"]
        actual_responses = runtime_path[method]["responses"]
        assert set(actual_responses) == set(expected_responses), (
            method,
            path,
        )
        for status, response in expected_responses.items():
            if "$ref" in response:
                response = canonical["components"]["responses"][response["$ref"].rsplit("/", 1)[1]]
            if "Cache-Control" in response.get("headers", {}):
                assert "Cache-Control" in actual_responses[status].get(
                    "headers",
                    {},
                ), (method, path, status)


def test_runtime_openapi_metadata_and_security_match_canonical() -> None:
    canonical = yaml.safe_load(
        (REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    generated = app.openapi()

    assert generated["info"] == canonical["info"]
    assert generated["servers"] == canonical["servers"]
    assert generated["security"] == canonical["security"]
    assert generated["components"]["securitySchemes"] == canonical["components"]["securitySchemes"]
    for path, method, operation in _implemented_canonical_operations(canonical):
        runtime_path = generated["paths"][f"/api/v1{path}"]
        assert runtime_path[method].get("security") == operation.get("security"), (method, path)
