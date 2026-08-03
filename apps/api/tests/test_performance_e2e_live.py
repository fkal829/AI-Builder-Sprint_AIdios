from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest
from pydantic import ValidationError
from pypdf import PdfReader
from supabase_auth.errors import AuthApiError

from app.core.enums import PerformanceMetricVerificationStatus
from app.schemas.performance import PerformanceConfirmedPayloadInput
from evaluation.performance_e2e_live import (
    EXPECTED_METRICS,
    UPLOAD_ID_NAMESPACE,
    LiveConfig,
    LiveE2EFailure,
    LivePerformanceE2ESummary,
    LiveStageSummary,
    _cleanup_created_fixture,
    _confirmation_body,
    _create_synthetic_fixture,
    _get_auth_user,
    _matches_fixture_contract_rows,
    _new_resources,
    _prepare_upload_identity,
    _validate_api_base_url,
    _verify_extracted_metrics,
    build_synthetic_performance_pdf,
    main,
    safe_error_payload,
)


def _stages() -> list[LiveStageSummary]:
    return [
        LiveStageSummary(
            stage=stage,
            http_status=http_status,
            check_count=check_count,
            passed_count=check_count,
        )
        for stage, http_status, check_count in (
            ("preflight", 200, 24),
            ("fixture", None, 4),
            ("authentication", None, 2),
            ("16.2-upload", 201, 6),
            ("16.3-extract", 200, 12),
            ("16.4-confirm", 200, 7),
            ("16.5-performance", 200, 6),
            ("persistence", None, 12),
            ("retention", None, 1),
        )
    ]


def _summary_kwargs() -> dict:
    stages = _stages()
    return {
        "cleanup_requested": False,
        "cleanup_completed": False,
        "fixture_retained": True,
        "stage_count": len(stages),
        "stages": stages,
        "tcp_http_verified": True,
        "live_modes_verified": True,
        "supabase_live_attested": True,
        "upstage_live_attested": True,
        "auth_token_verified": True,
        "private_bucket_verified": True,
        "storage_object_verified": True,
        "anonymous_read_denied": True,
        "parse_evidence_verified": True,
        "solar_metrics_verified": True,
        "replay_verified_count": 3,
        "request_id_match_count": 3,
        "no_store_response_count": 7,
        "verified_state_count": 6,
        "verified_metric_count": 10,
        "flag_count": 1,
        "inquiry_count": 1,
        "verified_audit_event_count": 3,
        "verified_idempotency_record_count": 3,
        "cleanup_target_count": 6,
        "cleanup_verified_count": 0,
    }


def _run_threads_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "evaluation.performance_e2e_live.asyncio.to_thread",
        inline,
    )


def test_cli_gate_prevents_config_or_network_without_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_config_load():
        nonlocal calls
        calls += 1
        raise AssertionError("config must not load before the live gate")

    monkeypatch.setattr(
        "evaluation.performance_e2e_live.load_live_config",
        forbidden_config_load,
    )

    with pytest.raises(SystemExit) as captured:
        main([])

    assert captured.value.code == 2
    assert calls == 0


def test_cleanup_option_alone_does_not_bypass_live_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden_config_load():
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(
        "evaluation.performance_e2e_live.load_live_config",
        forbidden_config_load,
    )

    with pytest.raises(SystemExit):
        main(["--cleanup-created-data"])

    assert called is False


def test_confirm_option_alone_does_not_bypass_cleanup_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden_config_load():
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(
        "evaluation.performance_e2e_live.load_live_config",
        forbidden_config_load,
    )

    with pytest.raises(SystemExit):
        main(["--confirm-live"])

    assert called is False


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8000",
        "https://localhost:8443",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ],
)
def test_api_base_url_allows_only_explicit_loopback_hosts(base_url: str) -> None:
    _validate_api_base_url(base_url)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com",
        "http://example.com:8000",
        "http://localhost.example.com:8000",
        "http://user:password@localhost:8000",
        "http://127.0.0.1:8000?token=private",
    ],
)
def test_api_base_url_rejects_non_loopback_or_credential_bearing_urls(base_url: str) -> None:
    with pytest.raises(LiveE2EFailure) as captured:
        _validate_api_base_url(base_url)

    assert captured.value.error_code == "INVALID_API_BASE_URL"


async def test_fixture_uses_auth_response_id_without_custom_id_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_threads_inline(monkeypatch)
    resources = _new_resources()
    returned_user_id = uuid4()
    recorded_attributes = None
    inserted_contract = None
    user = SimpleNamespace(
        id=returned_user_id,
        email=resources.email,
        user_metadata={"performance_e2e_marker": resources.marker},
    )

    class FakeAdminAuth:
        def create_user(self, attributes):
            nonlocal recorded_attributes
            recorded_attributes = attributes
            return SimpleNamespace(user=user)

    class FakeContractQuery:
        def insert(self, row):
            nonlocal inserted_contract
            inserted_contract = row
            return self

        def execute(self):
            return SimpleNamespace(
                data=[
                    {
                        **inserted_contract,
                        "end_date": None,
                        "total_amount": None,
                    }
                ]
            )

    class FakeAdmin:
        auth = SimpleNamespace(admin=FakeAdminAuth())

        def table(self, name):
            assert name == "contracts"
            return FakeContractQuery()

    await _create_synthetic_fixture(admin=FakeAdmin(), resources=resources)

    assert recorded_attributes is not None
    assert "id" not in recorded_attributes
    assert resources.user_id == returned_user_id
    assert inserted_contract["owner_id"] == str(returned_user_id)
    assert _matches_fixture_contract_rows(
        [
            {
                **inserted_contract,
                "end_date": None,
                "total_amount": None,
            }
        ],
        resources,
    )


def test_upload_identity_precomputes_exact_orphan_cleanup_path() -> None:
    resources = _new_resources()
    resources.user_id = uuid4()

    _prepare_upload_identity(resources)

    identity = f"{resources.user_id}:{resources.contract_id}:{resources.upload_key}"
    expected_report_id = uuid5(UPLOAD_ID_NAMESPACE, f"{identity}:report")
    expected_document_id = uuid5(UPLOAD_ID_NAMESPACE, f"{identity}:document")
    assert resources.report_id == expected_report_id
    assert resources.document_id == expected_document_id
    assert resources.storage_path == (
        f"{resources.user_id}/{resources.contract_id}/performance-reports/"
        f"{expected_report_id}/{expected_document_id}/source.pdf"
    )


async def test_auth_user_lookup_does_not_hide_bad_request_as_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_threads_inline(monkeypatch)

    class FakeAdminAuth:
        def get_user_by_id(self, _user_id):
            raise AuthApiError("private upstream detail", 400, None)

    admin = SimpleNamespace(auth=SimpleNamespace(admin=FakeAdminAuth()))

    with pytest.raises(AuthApiError) as captured:
        await _get_auth_user(admin, uuid4())

    assert captured.value.status == 400


async def test_cleanup_removes_deterministic_orphan_object_without_document_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_threads_inline(monkeypatch)
    resources = _new_resources()
    resources.user_id = uuid4()
    resources.user_created = True
    resources.contract_created = True
    _prepare_upload_identity(resources)
    expected_path = resources.storage_path
    assert expected_path is not None
    contract_row = {
        "id": str(resources.contract_id),
        "owner_id": str(resources.user_id),
        "title": resources.marker,
        "status": "SIGNED",
    }
    state = {
        "contract": contract_row,
        "object_exists": True,
        "user_exists": True,
        "removed_paths": [],
    }
    user = SimpleNamespace(
        id=resources.user_id,
        email=resources.email,
        user_metadata={"performance_e2e_marker": resources.marker},
    )

    class FakeQuery:
        def __init__(self, table):
            self.table = table
            self.deleting = False

        def select(self, _columns):
            return self

        def delete(self):
            self.deleting = True
            return self

        def eq(self, _column, _value):
            return self

        def limit(self, _value):
            return self

        def execute(self):
            if self.table == "contracts":
                if self.deleting:
                    state["contract"] = None
                    return SimpleNamespace(data=[])
                return SimpleNamespace(
                    data=[state["contract"]] if state["contract"] is not None else []
                )
            if self.table == "documents":
                return SimpleNamespace(data=[])
            if self.table == "idempotency_records":
                return SimpleNamespace(data=[])
            raise AssertionError(self.table)

    class FakeBucket:
        def exists(self, path):
            assert path == expected_path
            return state["object_exists"]

        def remove(self, paths):
            assert paths == [expected_path]
            state["removed_paths"].extend(paths)
            state["object_exists"] = False
            return []

    class FakeStorage:
        def from_(self, name):
            assert name == "contracts"
            return FakeBucket()

    class FakeAuthAdmin:
        def get_user_by_id(self, _user_id):
            if not state["user_exists"]:
                raise AuthApiError("not found", 404, None)
            return SimpleNamespace(user=user)

        def delete_user(self, _user_id):
            state["user_exists"] = False

    class FakeAdmin:
        auth = SimpleNamespace(admin=FakeAuthAdmin())
        storage = FakeStorage()

        def table(self, name):
            return FakeQuery(name)

    config = LiveConfig(
        api_base_url="http://127.0.0.1:8000",
        timeout_seconds=30,
        supabase_url="https://example.supabase.co",
        service_role_key="private-test-key",
        storage_bucket="contracts",
    )

    target_count, verified_count = await _cleanup_created_fixture(
        admin=FakeAdmin(),
        config=config,
        resources=resources,
    )

    assert target_count == 6
    assert verified_count == 6
    assert state["removed_paths"] == [expected_path]
    assert state["object_exists"] is False
    assert state["contract"] is None
    assert state["user_exists"] is False


def test_synthetic_pdf_is_valid_single_page_and_contains_all_expected_metrics() -> None:
    content = build_synthetic_performance_pdf()
    reader = PdfReader(BytesIO(content), strict=True)
    text = reader.pages[0].extract_text()

    assert content.startswith(b"%PDF-")
    assert len(reader.pages) == 1
    assert "SYNTHETIC" in text
    assert "Ad spend: KRW 438200" in text
    assert "Impressions: 12000" in text
    assert "Clicks: 2035" in text
    assert "Likes: 420" in text
    assert "Comments: 35" in text
    assert "Reach: 9500" in text
    assert "Saves: 88" in text
    assert "Shares: 47" in text
    assert "Follower net change: 120" in text
    assert "Published content count: 4" in text
    assert len(EXPECTED_METRICS) == 10


def test_confirmation_body_projects_ten_ai_candidates_into_the_public_input_contract() -> None:
    body = _confirmation_body()
    confirmed = PerformanceConfirmedPayloadInput.model_validate(body["confirmed_payload"])
    items = {item.key: item for item in confirmed.metric_items}

    assert len(EXPECTED_METRICS) == 10
    assert confirmed.impressions == EXPECTED_METRICS["impressions"]
    assert confirmed.published_content_count == EXPECTED_METRICS["published_content_count"]
    assert items["ad_spend"].value == EXPECTED_METRICS["ad_spend"]
    assert items["clicks"].value == EXPECTED_METRICS["clicks"]
    assert items["ctr"].value is None
    assert items["cpc"].value is None


def test_metric_verification_rejects_needs_check_even_when_value_matches() -> None:
    candidates = {
        name: SimpleNamespace(
            value=value,
            source_page=1,
            source_text=f"{name}: {value}",
            verification_status=PerformanceMetricVerificationStatus.VERIFIED,
        )
        for name, value in EXPECTED_METRICS.items()
    }
    candidates["shares"].verification_status = PerformanceMetricVerificationStatus.NEEDS_CHECK
    response = SimpleNamespace(
        data=SimpleNamespace(extracted_payload=SimpleNamespace(**candidates))
    )

    with pytest.raises(LiveE2EFailure) as captured:
        _verify_extracted_metrics(response, stage="16.3-extract")

    assert captured.value.error_code == "EXPECTED_METRIC_MISMATCH"


def test_safe_error_payload_never_includes_exception_text_or_private_values() -> None:
    private_values = (
        "service-role-secret",
        "access-token-secret",
        "fixture@example.com",
        "%PDF-private-bytes",
        "source_text=private report line",
        "user/contract/performance-reports/private/source.pdf",
        '{"raw":"response"}',
    )
    cause = ValueError(" ".join(private_values))
    error = LiveE2EFailure(
        stage="16.3-extract",
        error_code="REPORT_EXTRACT_FAILED",
        http_status=502,
    )
    error.__cause__ = cause

    serialized = json.dumps(safe_error_payload(error), ensure_ascii=False)

    assert all(value not in serialized for value in private_values)
    assert "REPORT_EXTRACT_FAILED" in serialized
    assert "16.3-extract" in serialized
    assert "502" in serialized


def test_safe_error_payload_redacts_unexpected_exception_completely() -> None:
    serialized = json.dumps(
        safe_error_payload(RuntimeError("token email@example.com source_text storage/path")),
        ensure_ascii=False,
    )

    assert "email@example.com" not in serialized
    assert "source_text" not in serialized
    assert "storage/path" not in serialized
    assert "UNEXPECTED_ERROR" in serialized


def test_success_summary_accepts_complete_retained_fixture_result() -> None:
    summary = LivePerformanceE2ESummary(**_summary_kwargs())

    assert summary.status == "passed"
    assert summary.fixture_retained is True
    assert summary.expected_metric_count == 10
    assert summary.verified_metric_count == 10
    assert summary.replay_verified_count == 3


def test_success_summary_accepts_complete_cleanup_result() -> None:
    values = _summary_kwargs()
    values.update(
        {
            "cleanup_requested": True,
            "cleanup_completed": True,
            "fixture_retained": False,
            "cleanup_verified_count": 6,
        }
    )
    values["stages"][-1] = LiveStageSummary(
        stage="cleanup",
        check_count=6,
        passed_count=6,
    )

    summary = LivePerformanceE2ESummary(**values)

    assert summary.cleanup_completed is True
    assert summary.cleanup_target_count == summary.cleanup_verified_count


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verified_metric_count", 9),
        ("replay_verified_count", 2),
        ("request_id_match_count", 2),
        ("no_store_response_count", 6),
        ("verified_state_count", 5),
        ("verified_audit_event_count", 2),
        ("verified_idempotency_record_count", 2),
        ("supabase_live_attested", False),
        ("upstage_live_attested", False),
        ("private_bucket_verified", False),
        ("storage_object_verified", False),
        ("anonymous_read_denied", False),
        ("fixture_retained", False),
    ],
)
def test_success_summary_rejects_incomplete_verification(field: str, value: object) -> None:
    values = _summary_kwargs()
    values[field] = value

    with pytest.raises(ValidationError):
        LivePerformanceE2ESummary(**values)


def test_stage_summary_rejects_partial_pass_count() -> None:
    with pytest.raises(ValidationError):
        LiveStageSummary(
            stage="preflight",
            check_count=3,
            passed_count=2,
        )
