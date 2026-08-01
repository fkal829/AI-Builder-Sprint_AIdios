"""Explicit live end-to-end verification for performance-report APIs.

This runner deliberately uses a real TCP HTTP client and a disposable Supabase
Auth user. It never imports the FastAPI application and never uses an in-process
ASGI transport. No external call is possible until ``--confirm-live`` is given.

The JSON emitted by this module is intentionally aggregate-only. Identifiers,
credentials, report bytes/text, storage paths, and raw external responses stay
inside the process.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Literal
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4, uuid5

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from supabase import Client, ClientOptions, create_client
from supabase_auth.errors import AuthApiError

from app.core.config import get_settings
from app.core.enums import PerformanceMetricVerificationStatus, PerformanceReportStatus
from app.schemas.performance import (
    ContractPerformanceResponse,
    PerformanceReportConfirmedResponse,
    PerformanceReportCreatedResponse,
    PerformanceReportExtractedResponse,
)

MODE = "LIVE_PERFORMANCE_E2E"
API_BASE_URL_ENV = "PERFORMANCE_E2E_BASE_URL"
TIMEOUT_SECONDS_ENV = "PERFORMANCE_E2E_TIMEOUT_SECONDS"
PERIOD = "2026-08"
SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
UPLOAD_ID_NAMESPACE = UUID("cdce6a82-929f-4af6-ae30-8a88c0fc71b2")

EXPECTED_METRICS: dict[str, int] = {
    "impressions": 12000,
    "likes": 420,
    "comments": 35,
    "reach": 9500,
    "saves": 88,
    "shares": 47,
    "follower_net_change": 120,
    "published_content_count": 4,
}

PERFORMANCE_TABLE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("contracts", "id"),
    ("documents", "id"),
    ("audit_events", "id"),
    ("idempotency_records", "owner_id"),
    ("performance_reports", "id"),
    ("performance_report_revisions", "id"),
    ("performance_flags", "id"),
    ("performance_flag_basis_terms", "flag_id"),
    ("performance_inquiry_drafts", "id"),
    ("understood_terms", "contract_id"),
    ("renewal_decisions", "contract_id"),
)

PERFORMANCE_RPCS: tuple[str, ...] = (
    "create_performance_report_upload_with_audit",
    "claim_performance_report_extraction",
    "complete_performance_report_extraction",
    "fail_performance_report_extraction",
    "confirm_performance_report_with_audit",
    "get_owned_contract_performance_snapshot",
    "claim_idempotency",
    "complete_idempotency",
    "abandon_idempotency",
)

EXPECTED_AUDIT_EVENTS = Counter(
    {
        "PERFORMANCE_REPORT_UPLOADED": 1,
        "PERFORMANCE_REPORT_EXTRACTED": 1,
        "PERFORMANCE_REPORT_FLAGGED": 1,
    }
)

IDEMPOTENCY_TARGETS = (
    ("PERFORMANCE_REPORT_UPLOAD", "contract"),
    ("PERFORMANCE_REPORT_EXTRACT", "report"),
    ("PERFORMANCE_REPORT_CONFIRM", "report"),
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveStageSummary(StrictModel):
    stage: str = Field(min_length=1, max_length=48, pattern=r"^[a-z0-9_.-]+$")
    status: Literal["passed"] = "passed"
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_code: None = None
    check_count: int = Field(ge=1)
    passed_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_counts(self) -> LiveStageSummary:
        if self.check_count != self.passed_count:
            raise ValueError("통과 단계의 검사 개수는 모두 통과해야 합니다.")
        return self


class LivePerformanceE2ESummary(StrictModel):
    mode: Literal["LIVE_PERFORMANCE_E2E"] = MODE
    status: Literal["passed"] = "passed"
    cleanup_requested: bool
    cleanup_completed: bool
    fixture_retained: bool
    synthetic_fixture_count: Literal[1] = 1
    stage_count: int = Field(ge=1)
    stages: list[LiveStageSummary] = Field(min_length=1)
    tcp_http_verified: bool
    live_modes_verified: bool
    supabase_live_attested: bool
    upstage_live_attested: bool
    auth_token_verified: bool
    private_bucket_verified: bool
    storage_object_verified: bool
    anonymous_read_denied: bool
    parse_evidence_verified: bool
    solar_metrics_verified: bool
    write_api_count: Literal[3] = 3
    replay_verified_count: int = Field(ge=0)
    request_id_match_count: int = Field(ge=0)
    no_store_response_count: int = Field(ge=0)
    expected_state_count: Literal[6] = 6
    verified_state_count: int = Field(ge=0)
    expected_metric_count: Literal[8] = 8
    verified_metric_count: int = Field(ge=0)
    flag_count: int = Field(ge=0)
    inquiry_count: int = Field(ge=0)
    expected_audit_event_count: Literal[3] = 3
    verified_audit_event_count: int = Field(ge=0)
    expected_idempotency_record_count: Literal[3] = 3
    verified_idempotency_record_count: int = Field(ge=0)
    cleanup_target_count: int = Field(ge=0)
    cleanup_verified_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_complete_success(self) -> LivePerformanceE2ESummary:
        if self.stage_count != len(self.stages):
            raise ValueError("stage_count가 실제 단계 개수와 다릅니다.")
        required_booleans = (
            self.tcp_http_verified,
            self.live_modes_verified,
            self.supabase_live_attested,
            self.upstage_live_attested,
            self.auth_token_verified,
            self.private_bucket_verified,
            self.storage_object_verified,
            self.anonymous_read_denied,
            self.parse_evidence_verified,
            self.solar_metrics_verified,
        )
        if not all(required_booleans):
            raise ValueError("live E2E 필수 검증이 모두 참이어야 합니다.")
        if (
            self.replay_verified_count != self.write_api_count
            or self.request_id_match_count != self.write_api_count
            or self.no_store_response_count != 7
            or self.verified_state_count != self.expected_state_count
            or self.verified_metric_count != self.expected_metric_count
            or self.flag_count < 1
            or self.inquiry_count < 1
            or self.verified_audit_event_count != self.expected_audit_event_count
            or self.verified_idempotency_record_count != self.expected_idempotency_record_count
        ):
            raise ValueError("live E2E 검증 개수가 완료 조건을 충족하지 않습니다.")
        if self.cleanup_requested:
            if (
                not self.cleanup_completed
                or self.fixture_retained
                or self.cleanup_verified_count != self.cleanup_target_count
            ):
                raise ValueError("요청된 합성 fixture 정리가 완전히 검증되지 않았습니다.")
        elif (
            self.cleanup_completed or not self.fixture_retained or self.cleanup_verified_count != 0
        ):
            raise ValueError("정리를 요청하지 않은 경우 합성 fixture 보존만 알려야 합니다.")
        return self


@dataclass(frozen=True)
class LiveConfig:
    api_base_url: str
    timeout_seconds: float
    supabase_url: str = field(repr=False)
    service_role_key: str = field(repr=False)
    storage_bucket: str


@dataclass
class LiveResources:
    marker: str = field(repr=False)
    contract_id: UUID
    email: str = field(repr=False)
    password: str = field(repr=False)
    upload_key: UUID
    extract_key: UUID
    confirm_key: UUID
    user_id: UUID | None = None
    user_created: bool = False
    contract_created: bool = False
    report_id: UUID | None = None
    document_id: UUID | None = None
    storage_path: str | None = field(default=None, repr=False)

    @property
    def retained(self) -> bool:
        return bool(
            self.user_created
            or self.contract_created
            or self.report_id is not None
            or self.storage_path is not None
        )


class LiveE2EFailure(RuntimeError):
    """A safe, aggregate-only failure that can be emitted by the CLI."""

    def __init__(
        self,
        *,
        stage: str,
        error_code: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__("live performance E2E verification failed")
        self.stage = stage
        self.error_code = _safe_error_code(error_code)
        self.http_status = http_status if isinstance(http_status, int) else None
        self.cleanup_requested = False
        self.cleanup_completed = False
        self.fixture_retained = False
        self.cleanup_target_count = 0
        self.cleanup_verified_count = 0


def build_synthetic_performance_pdf() -> bytes:
    """Build one in-memory, fictitious report with all eight AI metrics."""

    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, pageCompression=0)
    canvas.setTitle("Synthetic Advertisement Performance Report")
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawString(72, 790, "SYNTHETIC MONTHLY ADVERTISEMENT PERFORMANCE REPORT")
    canvas.setFont("Helvetica", 11)
    lines = (
        "Reporting period: 2026-08",
        "Impressions: 12000",
        "Likes: 420",
        "Comments: 35",
        "Reach: 9500",
        "Saves: 88",
        "Shares: 47",
        "Follower net change: 120",
        "Published content count: 4",
        "This is fictitious data created only for an explicit live verification.",
    )
    y = 750
    for line in lines:
        canvas.drawString(72, y, line)
        y -= 26
    canvas.showPage()
    canvas.save()
    content = buffer.getvalue()
    if not content.startswith(b"%PDF-"):
        raise RuntimeError("synthetic PDF generation failed")
    return content


def load_live_config(env: Mapping[str, str] | None = None) -> LiveConfig:
    values = os.environ if env is None else env
    base_url = values.get(API_BASE_URL_ENV, "").strip()
    timeout_raw = values.get(TIMEOUT_SECONDS_ENV, "").strip()
    if not base_url or not timeout_raw:
        raise LiveE2EFailure(stage="preflight", error_code="LIVE_ENV_REQUIRED")
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as error:
        raise LiveE2EFailure(stage="preflight", error_code="INVALID_LIVE_TIMEOUT") from error
    if not 1 <= timeout_seconds <= 1800:
        raise LiveE2EFailure(stage="preflight", error_code="INVALID_LIVE_TIMEOUT")
    _validate_api_base_url(base_url)

    try:
        settings = get_settings()
    except Exception as error:
        raise LiveE2EFailure(stage="preflight", error_code="INVALID_LIVE_SETTINGS") from error
    if settings.supabase_mode != "live" or settings.upstage_mode != "live":
        raise LiveE2EFailure(stage="preflight", error_code="LIVE_MODE_REQUIRED")
    if not (
        settings.supabase_url and settings.supabase_service_role_key and settings.upstage_api_key
    ):
        raise LiveE2EFailure(stage="preflight", error_code="LIVE_CREDENTIALS_REQUIRED")
    return LiveConfig(
        api_base_url=base_url.rstrip("/"),
        timeout_seconds=timeout_seconds,
        supabase_url=settings.supabase_url.rstrip("/"),
        service_role_key=settings.supabase_service_role_key,
        storage_bucket=settings.supabase_storage_bucket,
    )


def safe_error_payload(error: Exception) -> dict[str, Any]:
    if isinstance(error, LiveE2EFailure):
        return {
            "mode": MODE,
            "status": "failed",
            "stage": error.stage,
            "http_status": error.http_status,
            "error_code": error.error_code,
            "cleanup_requested": error.cleanup_requested,
            "cleanup_completed": error.cleanup_completed,
            "fixture_retained": error.fixture_retained,
            "cleanup_target_count": error.cleanup_target_count,
            "cleanup_verified_count": error.cleanup_verified_count,
        }
    return {
        "mode": MODE,
        "status": "failed",
        "stage": "unknown",
        "http_status": None,
        "error_code": "UNEXPECTED_ERROR",
        "cleanup_requested": False,
        "cleanup_completed": False,
        "fixture_retained": False,
        "cleanup_target_count": 0,
        "cleanup_verified_count": 0,
    }


async def run_live_performance_e2e(
    *,
    config: LiveConfig,
    cleanup_created_data: bool,
) -> LivePerformanceE2ESummary:
    resources = _new_resources()
    admin = _new_supabase_client(config)
    stages: list[LiveStageSummary] = []
    current_stage = "preflight"
    failure: LiveE2EFailure | None = None
    cleanup_target_count = 0
    cleanup_verified_count = 0

    try:
        preflight_checks = await _run_read_only_preflight(config=config, admin=admin)
        stages.append(_passed_stage("preflight", check_count=preflight_checks, http_status=200))

        current_stage = "fixture"
        await _create_synthetic_fixture(admin=admin, resources=resources)
        stages.append(_passed_stage("fixture", check_count=4))

        current_stage = "authentication"
        access_token = await _sign_in_fixture_user(config=config, resources=resources)
        _prepare_upload_identity(resources)
        stages.append(_passed_stage("authentication", check_count=2))

        current_stage = "16.2-upload"
        pdf_content = build_synthetic_performance_pdf()
        no_store_count = 0
        async with _new_tcp_api_client(config=config, access_token=access_token) as api:
            upload_first_response = await api.post(
                f"/api/v1/contracts/{resources.contract_id}/performance-reports",
                headers={"Idempotency-Key": str(resources.upload_key)},
                data={"period": PERIOD},
                files={
                    "file": (
                        "synthetic-performance-report.pdf",
                        pdf_content,
                        "application/pdf",
                    )
                },
            )
            upload_first = _validated_response(
                upload_first_response,
                expected_status=201,
                schema=PerformanceReportCreatedResponse,
                stage=current_stage,
            )
            no_store_count += 1
            if (
                upload_first.data.id != resources.report_id
                or upload_first.data.source_document_id != resources.document_id
            ):
                raise LiveE2EFailure(
                    stage=current_stage,
                    error_code="UPLOAD_IDENTITY_MISMATCH",
                )

            upload_replay_response = await api.post(
                f"/api/v1/contracts/{resources.contract_id}/performance-reports",
                headers={"Idempotency-Key": str(resources.upload_key)},
                data={"period": PERIOD},
                files={
                    "file": (
                        "synthetic-performance-report.pdf",
                        pdf_content,
                        "application/pdf",
                    )
                },
            )
            upload_replay = _validated_response(
                upload_replay_response,
                expected_status=201,
                schema=PerformanceReportCreatedResponse,
                stage=current_stage,
            )
            no_store_count += 1
            _require_exact_replay(upload_first, upload_replay, stage=current_stage)
            if upload_first.data.status is not PerformanceReportStatus.UPLOADED:
                raise LiveE2EFailure(stage=current_stage, error_code="INVALID_UPLOAD_STATE")
            stages.append(_passed_stage(current_stage, check_count=6, http_status=201))

            current_stage = "16.3-extract"
            report_id = _require_report_id(resources, stage=current_stage)
            extract_path = (
                f"/api/v1/contracts/{resources.contract_id}/performance-reports/{report_id}/extract"
            )
            extract_first_response = await api.post(
                extract_path,
                headers={"Idempotency-Key": str(resources.extract_key)},
            )
            extract_first = _validated_response(
                extract_first_response,
                expected_status=200,
                schema=PerformanceReportExtractedResponse,
                stage=current_stage,
            )
            no_store_count += 1
            verified_metric_count = _verify_extracted_metrics(extract_first, stage=current_stage)

            extract_replay_response = await api.post(
                extract_path,
                headers={"Idempotency-Key": str(resources.extract_key)},
            )
            extract_replay = _validated_response(
                extract_replay_response,
                expected_status=200,
                schema=PerformanceReportExtractedResponse,
                stage=current_stage,
            )
            no_store_count += 1
            _require_exact_replay(extract_first, extract_replay, stage=current_stage)
            if extract_first.data.status is not PerformanceReportStatus.EXTRACTED:
                raise LiveE2EFailure(stage=current_stage, error_code="INVALID_EXTRACT_STATE")
            stages.append(_passed_stage(current_stage, check_count=12, http_status=200))

            current_stage = "16.4-confirm"
            confirm_path = (
                f"/api/v1/contracts/{resources.contract_id}/performance-reports/{report_id}"
            )
            confirmation_body = _confirmation_body()
            confirm_first_response = await api.patch(
                confirm_path,
                headers={"Idempotency-Key": str(resources.confirm_key)},
                json=confirmation_body,
            )
            confirm_first = _validated_response(
                confirm_first_response,
                expected_status=200,
                schema=PerformanceReportConfirmedResponse,
                stage=current_stage,
            )
            no_store_count += 1
            flag_count, inquiry_count = _verify_confirmation(confirm_first, stage=current_stage)

            confirm_replay_response = await api.patch(
                confirm_path,
                headers={"Idempotency-Key": str(resources.confirm_key)},
                json=confirmation_body,
            )
            confirm_replay = _validated_response(
                confirm_replay_response,
                expected_status=200,
                schema=PerformanceReportConfirmedResponse,
                stage=current_stage,
            )
            no_store_count += 1
            _require_exact_replay(confirm_first, confirm_replay, stage=current_stage)
            stages.append(_passed_stage(current_stage, check_count=7, http_status=200))

            current_stage = "16.5-performance"
            performance_response = await api.get(
                f"/api/v1/contracts/{resources.contract_id}/performance"
            )
            performance = _validated_response(
                performance_response,
                expected_status=200,
                schema=ContractPerformanceResponse,
                stage=current_stage,
            )
            no_store_count += 1
            _verify_aggregation(
                performance,
                report_id=report_id,
                flag_count=flag_count,
                inquiry_count=inquiry_count,
                stage=current_stage,
            )
            stages.append(_passed_stage(current_stage, check_count=6, http_status=200))

        current_stage = "persistence"
        persistence = await _verify_persisted_state(
            admin=admin,
            config=config,
            resources=resources,
        )
        stages.append(_passed_stage(current_stage, check_count=12))

        if no_store_count != 7:
            raise LiveE2EFailure(stage="persistence", error_code="NO_STORE_COUNT_MISMATCH")
        verified_state_count = 6
        verified_audit_event_count = persistence["audit_count"]
        verified_idempotency_record_count = persistence["idempotency_count"]
        storage_verified = persistence["storage_verified"]
        anonymous_read_denied = persistence["anonymous_read_denied"]
        supabase_live_attested = bool(
            storage_verified and verified_idempotency_record_count == len(IDEMPOTENCY_TARGETS)
        )
        upstage_live_attested = verified_metric_count == len(EXPECTED_METRICS)
    except Exception as error:
        failure = _coerce_failure(error, stage=current_stage)
        verified_metric_count = 0
        flag_count = 0
        inquiry_count = 0
        no_store_count = 0
        verified_state_count = 0
        verified_audit_event_count = 0
        verified_idempotency_record_count = 0
        storage_verified = False
        anonymous_read_denied = False
        supabase_live_attested = False
        upstage_live_attested = False
    finally:
        cleanup_target_count = _known_cleanup_target_count(resources)
        if cleanup_created_data:
            try:
                cleanup_target_count, cleanup_verified_count = await _cleanup_created_fixture(
                    admin=admin,
                    config=config,
                    resources=resources,
                )
                stages.append(
                    _passed_stage(
                        "cleanup",
                        check_count=max(cleanup_verified_count, 1),
                    )
                )
            except Exception as cleanup_error:
                if failure is None:
                    failure = _coerce_failure(cleanup_error, stage="cleanup")
        else:
            stages.append(_passed_stage("retention", check_count=1))

    if failure is not None:
        failure.cleanup_requested = cleanup_created_data
        failure.cleanup_completed = bool(
            cleanup_created_data
            and cleanup_target_count == cleanup_verified_count
            and cleanup_target_count > 0
        )
        failure.fixture_retained = resources.retained and not failure.cleanup_completed
        failure.cleanup_target_count = cleanup_target_count
        failure.cleanup_verified_count = cleanup_verified_count
        raise failure

    cleanup_completed = cleanup_created_data and cleanup_target_count == cleanup_verified_count
    return LivePerformanceE2ESummary(
        cleanup_requested=cleanup_created_data,
        cleanup_completed=cleanup_completed,
        fixture_retained=not cleanup_created_data,
        stage_count=len(stages),
        stages=stages,
        tcp_http_verified=True,
        live_modes_verified=supabase_live_attested and upstage_live_attested,
        supabase_live_attested=supabase_live_attested,
        upstage_live_attested=upstage_live_attested,
        auth_token_verified=True,
        private_bucket_verified=True,
        storage_object_verified=storage_verified,
        anonymous_read_denied=anonymous_read_denied,
        parse_evidence_verified=True,
        solar_metrics_verified=verified_metric_count == len(EXPECTED_METRICS),
        replay_verified_count=3,
        request_id_match_count=3,
        no_store_response_count=no_store_count,
        verified_state_count=verified_state_count,
        verified_metric_count=verified_metric_count,
        flag_count=flag_count,
        inquiry_count=inquiry_count,
        verified_audit_event_count=verified_audit_event_count,
        verified_idempotency_record_count=verified_idempotency_record_count,
        cleanup_target_count=cleanup_target_count,
        cleanup_verified_count=cleanup_verified_count,
    )


def _new_resources() -> LiveResources:
    marker = f"dandi-performance-e2e-{uuid4().hex}"
    return LiveResources(
        marker=marker,
        contract_id=uuid4(),
        email=f"{marker}@example.com",
        password=secrets.token_urlsafe(32),
        upload_key=uuid4(),
        extract_key=uuid4(),
        confirm_key=uuid4(),
    )


def _prepare_upload_identity(resources: LiveResources) -> None:
    user_id = _require_user_id(resources, stage="authentication")
    identity = f"{user_id}:{resources.contract_id}:{resources.upload_key}"
    report_id = uuid5(UPLOAD_ID_NAMESPACE, f"{identity}:report")
    document_id = uuid5(UPLOAD_ID_NAMESPACE, f"{identity}:document")
    resources.report_id = report_id
    resources.document_id = document_id
    resources.storage_path = (
        f"{user_id}/{resources.contract_id}/performance-reports/"
        f"{report_id}/{document_id}/source.pdf"
    )


def _new_supabase_client(config: LiveConfig) -> Client:
    options = ClientOptions(
        auto_refresh_token=False,
        persist_session=False,
        postgrest_client_timeout=config.timeout_seconds,
        storage_client_timeout=max(1, min(int(config.timeout_seconds), 300)),
        function_client_timeout=max(1, min(int(config.timeout_seconds), 1800)),
    )
    return create_client(config.supabase_url, config.service_role_key, options=options)


def _new_tcp_api_client(*, config: LiveConfig, access_token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=config.api_base_url,
        timeout=httpx.Timeout(config.timeout_seconds),
        follow_redirects=False,
        headers={"Authorization": f"Bearer {access_token}"},
        transport=httpx.AsyncHTTPTransport(retries=0),
    )


async def _run_read_only_preflight(*, config: LiveConfig, admin: Client) -> int:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.timeout_seconds),
        follow_redirects=False,
        transport=httpx.AsyncHTTPTransport(retries=0),
    ) as client:
        try:
            health = await client.get(f"{config.api_base_url}/api/v1/health")
        except httpx.HTTPError as error:
            raise LiveE2EFailure(stage="preflight", error_code="API_PREFLIGHT_FAILED") from error
        if health.status_code != 200:
            raise LiveE2EFailure(
                stage="preflight",
                error_code="API_PREFLIGHT_FAILED",
                http_status=health.status_code,
            )

        headers = {
            "apikey": config.service_role_key,
            "Authorization": f"Bearer {config.service_role_key}",
            "Accept": "application/openapi+json",
        }
        try:
            catalog_response = await client.get(
                f"{config.supabase_url}/rest/v1/",
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise LiveE2EFailure(
                stage="preflight", error_code="SUPABASE_PREFLIGHT_FAILED"
            ) from error
        if catalog_response.status_code != 200:
            raise LiveE2EFailure(
                stage="preflight",
                error_code="SUPABASE_PREFLIGHT_FAILED",
                http_status=catalog_response.status_code,
            )
        try:
            catalog = catalog_response.json()
            paths = catalog["paths"]
            if not isinstance(paths, dict):
                raise TypeError
        except (KeyError, TypeError, ValueError) as error:
            raise LiveE2EFailure(
                stage="preflight", error_code="SUPABASE_CATALOG_INVALID"
            ) from error

    required_paths = {f"/{table}" for table, _column in PERFORMANCE_TABLE_COLUMNS}
    required_paths.update(f"/rpc/{name}" for name in PERFORMANCE_RPCS)
    if not required_paths.issubset(paths):
        raise LiveE2EFailure(stage="preflight", error_code="PERFORMANCE_SCHEMA_MISSING")

    def select_tables_and_bucket() -> None:
        for table, column in PERFORMANCE_TABLE_COLUMNS:
            admin.table(table).select(column).limit(1).execute()
        bucket = admin.storage.get_bucket(config.storage_bucket)
        if bucket.public:
            raise ValueError("performance report bucket must be private")

    try:
        await asyncio.to_thread(select_tables_and_bucket)
    except Exception as error:
        raise LiveE2EFailure(
            stage="preflight", error_code="PERFORMANCE_TABLE_PREFLIGHT_FAILED"
        ) from error
    return 4 + len(PERFORMANCE_TABLE_COLUMNS) + len(PERFORMANCE_RPCS)


async def _create_synthetic_fixture(*, admin: Client, resources: LiveResources) -> None:
    attributes = {
        "email": resources.email,
        "password": resources.password,
        "email_confirm": True,
        "user_metadata": {"performance_e2e_marker": resources.marker},
    }
    try:
        response = await asyncio.to_thread(admin.auth.admin.create_user, attributes)
        user = response.user
    except Exception as error:
        user = await _find_fixture_user(admin, resources)
        if _fixture_user_id(user, resources) is None:
            raise LiveE2EFailure(stage="fixture", error_code="AUTH_USER_CREATE_FAILED") from error
    user_id = _fixture_user_id(user, resources)
    if user_id is None:
        raise LiveE2EFailure(stage="fixture", error_code="AUTH_USER_IDENTITY_MISMATCH")
    resources.user_id = user_id
    resources.user_created = True

    now = datetime.now(UTC)
    contract_row = {
        "id": str(resources.contract_id),
        "owner_id": str(user_id),
        "title": resources.marker,
        "counterparty_name": "Synthetic Live Verification Agency",
        "status": "SIGNED",
        "signed_date": now.date().isoformat(),
        "start_date": now.date().isoformat(),
        "renewal_type": "NONE",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    try:
        result = await asyncio.to_thread(
            lambda: admin.table("contracts").insert(contract_row).execute()
        )
        rows = result.data or []
    except Exception as error:
        rows = await _contract_rows(admin=admin, resources=resources)
        if not _matches_fixture_contract_rows(rows, resources):
            raise LiveE2EFailure(stage="fixture", error_code="CONTRACT_CREATE_FAILED") from error
    if rows and not _matches_fixture_contract_rows(rows, resources):
        raise LiveE2EFailure(stage="fixture", error_code="CONTRACT_IDENTITY_MISMATCH")
    resources.contract_created = True


async def _sign_in_fixture_user(*, config: LiveConfig, resources: LiveResources) -> str:
    user_id = _require_user_id(resources, stage="authentication")
    auth_client = _new_supabase_client(config)
    try:
        response = await asyncio.to_thread(
            auth_client.auth.sign_in_with_password,
            {"email": resources.email, "password": resources.password},
        )
    except Exception as error:
        raise LiveE2EFailure(
            stage="authentication", error_code="PASSWORD_SIGN_IN_FAILED"
        ) from error
    if (
        response.user is None
        or str(response.user.id) != str(user_id)
        or response.session is None
        or not response.session.access_token
    ):
        raise LiveE2EFailure(stage="authentication", error_code="AUTH_TOKEN_INVALID")
    return response.session.access_token


def _validated_response[ResponseModel: BaseModel](
    response: httpx.Response,
    *,
    expected_status: int,
    schema: type[ResponseModel],
    stage: str,
) -> ResponseModel:
    if response.status_code != expected_status:
        raise LiveE2EFailure(
            stage=stage,
            error_code=_remote_error_code(response),
            http_status=response.status_code,
        )
    cache_directives = {
        item.strip().lower()
        for item in response.headers.get("Cache-Control", "").split(",")
        if item.strip()
    }
    if "no-store" not in cache_directives:
        raise LiveE2EFailure(
            stage=stage,
            error_code="NO_STORE_HEADER_MISSING",
            http_status=response.status_code,
        )
    try:
        parsed = schema.model_validate(response.json())
    except (TypeError, ValueError) as error:
        raise LiveE2EFailure(
            stage=stage,
            error_code="RESPONSE_SCHEMA_INVALID",
            http_status=response.status_code,
        ) from error
    body_request_id = getattr(parsed, "request_id", None)
    if not body_request_id or response.headers.get("X-Request-ID") != body_request_id:
        raise LiveE2EFailure(
            stage=stage,
            error_code="REQUEST_ID_HEADER_MISMATCH",
            http_status=response.status_code,
        )
    return parsed


def _require_exact_replay(first: BaseModel, replay: BaseModel, *, stage: str) -> None:
    if getattr(first, "request_id", None) != getattr(
        replay, "request_id", None
    ) or first.model_dump(mode="json") != replay.model_dump(mode="json"):
        raise LiveE2EFailure(stage=stage, error_code="IDEMPOTENT_REPLAY_MISMATCH")


def _verify_extracted_metrics(
    response: PerformanceReportExtractedResponse,
    *,
    stage: str,
) -> int:
    payload = response.data.extracted_payload
    verified = 0
    for field_name, expected_value in EXPECTED_METRICS.items():
        candidate = getattr(payload, field_name)
        if (
            candidate.value != expected_value
            or candidate.source_page is None
            or not candidate.source_text
            or candidate.verification_status is not PerformanceMetricVerificationStatus.VERIFIED
        ):
            raise LiveE2EFailure(stage=stage, error_code="EXPECTED_METRIC_MISMATCH")
        verified += 1
    return verified


def _confirmation_body() -> dict[str, Any]:
    return {
        "expected_revision": 0,
        "confirmed_payload": {
            **EXPECTED_METRICS,
            "inquiries": 6,
            "reservations": 3,
            "purchases": 2,
        },
        "has_issue": True,
        "issue_note": "합성 live 검증에서 소유자 확인이 필요한 항목입니다.",
        "correction_reason": None,
    }


def _verify_confirmation(
    response: PerformanceReportConfirmedResponse,
    *,
    stage: str,
) -> tuple[int, int]:
    report = response.data
    current = report.current_revision
    if (
        report.status is not PerformanceReportStatus.FLAGGED
        or report.revision_count != 1
        or current.status is not PerformanceReportStatus.FLAGGED
        or current.version != 1
        or current.confirmed_payload.model_dump(mode="json")
        != _confirmation_body()["confirmed_payload"]
    ):
        raise LiveE2EFailure(stage=stage, error_code="INVALID_CONFIRMATION_STATE")
    flag_count = len(current.flags)
    inquiry_count = len(current.inquiry_drafts)
    if flag_count < 1 or inquiry_count < 1 or flag_count != inquiry_count:
        raise LiveE2EFailure(stage=stage, error_code="FLAG_INQUIRY_MISSING")
    return flag_count, inquiry_count


def _verify_aggregation(
    response: ContractPerformanceResponse,
    *,
    report_id: UUID,
    flag_count: int,
    inquiry_count: int,
    stage: str,
) -> None:
    performance = response.data
    if (
        len(performance.reports) != 1
        or performance.reports[0].id != report_id
        or performance.reports[0].status is not PerformanceReportStatus.FLAGGED
        or len(performance.confirmed_series) != 1
        or performance.confirmed_series[0].report_id != report_id
        or len(performance.flags) != flag_count
        or len(performance.inquiry_drafts) != inquiry_count
    ):
        raise LiveE2EFailure(stage=stage, error_code="AGGREGATION_MISMATCH")


async def _verify_persisted_state(
    *,
    admin: Client,
    config: LiveConfig,
    resources: LiveResources,
) -> dict[str, Any]:
    user_id = _require_user_id(resources, stage="persistence")
    report_id = _require_report_id(resources, stage="persistence")
    document_id = resources.document_id
    if document_id is None:
        raise LiveE2EFailure(stage="persistence", error_code="DOCUMENT_ID_MISSING")

    def read_rows() -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
    ]:
        report_rows = (
            admin.table("performance_reports")
            .select("id,status,revision_count,source_document_id")
            .eq("id", str(report_id))
            .eq("contract_id", str(resources.contract_id))
            .execute()
            .data
            or []
        )
        document_rows = (
            admin.table("documents")
            .select("id,type,parse_status,storage_path")
            .eq("id", str(document_id))
            .eq("contract_id", str(resources.contract_id))
            .execute()
            .data
            or []
        )
        audit_rows = (
            admin.table("audit_events")
            .select("event_type")
            .eq("contract_id", str(resources.contract_id))
            .in_("event_type", list(EXPECTED_AUDIT_EVENTS))
            .execute()
            .data
            or []
        )
        idempotency_rows = (
            admin.table("idempotency_records")
            .select("operation,resource_id,idempotency_key,response_status")
            .eq("owner_id", str(user_id))
            .in_("idempotency_key", [str(key) for key in _idempotency_keys(resources)])
            .execute()
            .data
            or []
        )
        return report_rows, document_rows, audit_rows, idempotency_rows

    try:
        report_rows, document_rows, audit_rows, idempotency_rows = await asyncio.to_thread(
            read_rows
        )
    except Exception as error:
        raise LiveE2EFailure(stage="persistence", error_code="PERSISTENCE_READ_FAILED") from error
    if len(report_rows) != 1 or report_rows[0] != {
        "id": str(report_id),
        "status": "FLAGGED",
        "revision_count": 1,
        "source_document_id": str(document_id),
    }:
        raise LiveE2EFailure(stage="persistence", error_code="REPORT_DB_STATE_MISMATCH")
    if (
        len(document_rows) != 1
        or document_rows[0].get("id") != str(document_id)
        or document_rows[0].get("type") != "PERFORMANCE_REPORT"
        or document_rows[0].get("parse_status") != "COMPLETED"
        or not isinstance(document_rows[0].get("storage_path"), str)
    ):
        raise LiveE2EFailure(stage="persistence", error_code="DOCUMENT_DB_STATE_MISMATCH")
    resources.storage_path = document_rows[0]["storage_path"]

    event_counts = Counter(row.get("event_type") for row in audit_rows)
    if event_counts != EXPECTED_AUDIT_EVENTS:
        raise LiveE2EFailure(stage="persistence", error_code="AUDIT_EVENT_MISMATCH")

    expected_idempotency = {
        ("PERFORMANCE_REPORT_UPLOAD", str(resources.contract_id), str(resources.upload_key), 201),
        ("PERFORMANCE_REPORT_EXTRACT", str(report_id), str(resources.extract_key), 200),
        ("PERFORMANCE_REPORT_CONFIRM", str(report_id), str(resources.confirm_key), 200),
    }
    actual_idempotency = {
        (
            row.get("operation"),
            row.get("resource_id"),
            row.get("idempotency_key"),
            row.get("response_status"),
        )
        for row in idempotency_rows
    }
    if actual_idempotency != expected_idempotency:
        raise LiveE2EFailure(stage="persistence", error_code="IDEMPOTENCY_DB_MISMATCH")
    try:
        storage_verified = await asyncio.to_thread(
            admin.storage.from_(config.storage_bucket).exists,
            resources.storage_path,
        )
    except Exception as error:
        raise LiveE2EFailure(stage="persistence", error_code="STORAGE_VERIFY_FAILED") from error
    if not storage_verified:
        raise LiveE2EFailure(stage="persistence", error_code="STORAGE_OBJECT_MISSING")
    anonymous_read_denied = await _verify_anonymous_storage_denial(
        config=config,
        storage_path=resources.storage_path,
    )
    return {
        "audit_count": sum(event_counts.values()),
        "idempotency_count": len(actual_idempotency),
        "storage_verified": True,
        "anonymous_read_denied": anonymous_read_denied,
    }


async def _verify_anonymous_storage_denial(
    *,
    config: LiveConfig,
    storage_path: str,
) -> bool:
    bucket = quote(config.storage_bucket, safe="")
    path = quote(storage_path, safe="/")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout_seconds),
            follow_redirects=False,
            transport=httpx.AsyncHTTPTransport(retries=0),
        ) as client:
            response = await client.get(
                f"{config.supabase_url}/storage/v1/object/public/{bucket}/{path}"
            )
    except httpx.HTTPError as error:
        raise LiveE2EFailure(
            stage="persistence", error_code="ANONYMOUS_STORAGE_CHECK_FAILED"
        ) from error
    if response.status_code not in {400, 401, 403, 404}:
        raise LiveE2EFailure(
            stage="persistence",
            error_code="ANONYMOUS_STORAGE_READ_ALLOWED",
            http_status=response.status_code,
        )
    return True


async def _cleanup_created_fixture(
    *,
    admin: Client,
    config: LiveConfig,
    resources: LiveResources,
) -> tuple[int, int]:
    # Discover only rows underneath the exact random contract. Never use a
    # prefix delete, an owner-wide delete, or an unresolved storage path.
    contract_rows = await _contract_rows(admin=admin, resources=resources)
    if contract_rows and not _matches_fixture_contract_rows(contract_rows, resources):
        raise LiveE2EFailure(stage="cleanup", error_code="CLEANUP_IDENTITY_MISMATCH")

    if resources.user_id is None:
        recovered_user = await _find_fixture_user(admin, resources)
        recovered_id = _fixture_user_id(recovered_user, resources)
        if recovered_id is None:
            return 0, 0
        resources.user_id = recovered_id
    user_id = _require_user_id(resources, stage="cleanup")
    user = await _get_auth_user(admin, user_id)
    if user is not None and not _matches_fixture_user(user, resources):
        raise LiveE2EFailure(stage="cleanup", error_code="CLEANUP_IDENTITY_MISMATCH")

    def read_documents() -> list[dict[str, Any]]:
        return (
            admin.table("documents")
            .select("id,type,storage_path")
            .eq("contract_id", str(resources.contract_id))
            .execute()
            .data
            or []
        )

    try:
        document_rows = await asyncio.to_thread(read_documents)
    except Exception as error:
        raise LiveE2EFailure(stage="cleanup", error_code="CLEANUP_PREFLIGHT_FAILED") from error
    if len(document_rows) > 1:
        raise LiveE2EFailure(stage="cleanup", error_code="CLEANUP_SCOPE_MISMATCH")
    document_paths: list[str] = []
    for row in document_rows:
        path = row.get("storage_path")
        if (
            row.get("type") != "PERFORMANCE_REPORT"
            or not isinstance(path, str)
            or not path.startswith(f"{user_id}/{resources.contract_id}/performance-reports/")
            or ".." in path.split("/")
        ):
            raise LiveE2EFailure(stage="cleanup", error_code="CLEANUP_SCOPE_MISMATCH")
        document_paths.append(path)
    if resources.storage_path is not None and tuple(document_paths) not in {
        (),
        (resources.storage_path,),
    }:
        raise LiveE2EFailure(stage="cleanup", error_code="CLEANUP_SCOPE_MISMATCH")
    storage_paths = (
        [resources.storage_path] if resources.storage_path is not None else document_paths
    )

    targets = _idempotency_cleanup_targets(resources)
    target_count = int(user is not None) + int(bool(contract_rows)) + len(storage_paths)
    target_count += len(targets)
    verified_count = 0

    for operation, resource_id, key in targets:
        try:
            rows = await asyncio.to_thread(
                lambda operation=operation, resource_id=resource_id, key=key: (
                    admin.table("idempotency_records")
                    .select("owner_id,operation,resource_id,idempotency_key")
                    .eq("owner_id", str(user_id))
                    .eq("operation", operation)
                    .eq("resource_id", str(resource_id))
                    .eq("idempotency_key", str(key))
                    .execute()
                    .data
                    or []
                )
            )
            if len(rows) > 1:
                raise LiveE2EFailure(stage="cleanup", error_code="CLEANUP_SCOPE_MISMATCH")
            await asyncio.to_thread(
                lambda operation=operation, resource_id=resource_id, key=key: (
                    admin.table("idempotency_records")
                    .delete()
                    .eq("owner_id", str(user_id))
                    .eq("operation", operation)
                    .eq("resource_id", str(resource_id))
                    .eq("idempotency_key", str(key))
                    .execute()
                )
            )
            remaining = await asyncio.to_thread(
                lambda operation=operation, resource_id=resource_id, key=key: (
                    admin.table("idempotency_records")
                    .select("owner_id")
                    .eq("owner_id", str(user_id))
                    .eq("operation", operation)
                    .eq("resource_id", str(resource_id))
                    .eq("idempotency_key", str(key))
                    .execute()
                    .data
                    or []
                )
            )
        except LiveE2EFailure:
            raise
        except Exception as error:
            raise LiveE2EFailure(
                stage="cleanup", error_code="IDEMPOTENCY_CLEANUP_FAILED"
            ) from error
        if remaining:
            raise LiveE2EFailure(stage="cleanup", error_code="IDEMPOTENCY_CLEANUP_FAILED")
        verified_count += 1

    bucket = admin.storage.from_(config.storage_bucket)
    for path in storage_paths:
        try:
            if await asyncio.to_thread(bucket.exists, path):
                await asyncio.to_thread(bucket.remove, [path])
            if await asyncio.to_thread(bucket.exists, path):
                raise LiveE2EFailure(stage="cleanup", error_code="STORAGE_CLEANUP_FAILED")
        except LiveE2EFailure:
            raise
        except Exception as error:
            raise LiveE2EFailure(stage="cleanup", error_code="STORAGE_CLEANUP_FAILED") from error
        verified_count += 1

    if contract_rows:
        try:
            await asyncio.to_thread(
                lambda: (
                    admin.table("contracts")
                    .delete()
                    .eq("id", str(resources.contract_id))
                    .eq("owner_id", str(user_id))
                    .execute()
                )
            )
        except Exception as error:
            raise LiveE2EFailure(stage="cleanup", error_code="CONTRACT_CLEANUP_FAILED") from error
        if await _contract_rows(admin=admin, resources=resources):
            raise LiveE2EFailure(stage="cleanup", error_code="CONTRACT_CLEANUP_FAILED")
        resources.contract_created = False
        resources.report_id = None
        resources.document_id = None
        resources.storage_path = None
        verified_count += 1

    if user is not None:
        try:
            await asyncio.to_thread(admin.auth.admin.delete_user, str(user_id))
        except Exception as error:
            raise LiveE2EFailure(stage="cleanup", error_code="AUTH_USER_CLEANUP_FAILED") from error
        if await _get_auth_user(admin, user_id) is not None:
            raise LiveE2EFailure(stage="cleanup", error_code="AUTH_USER_CLEANUP_FAILED")
        resources.user_created = False
        verified_count += 1

    return target_count, verified_count


async def _contract_rows(*, admin: Client, resources: LiveResources) -> list[dict[str, Any]]:
    try:
        response = await asyncio.to_thread(
            lambda: (
                admin.table("contracts")
                .select("id,owner_id,title,status")
                .eq("id", str(resources.contract_id))
                .limit(1)
                .execute()
            )
        )
    except Exception as error:
        raise LiveE2EFailure(stage="cleanup", error_code="CONTRACT_VERIFY_FAILED") from error
    return response.data or []


async def _get_auth_user(admin: Client, user_id: UUID) -> Any | None:
    try:
        response = await asyncio.to_thread(admin.auth.admin.get_user_by_id, str(user_id))
    except AuthApiError as error:
        if error.status == 404:
            return None
        raise
    return response.user


async def _find_fixture_user(admin: Client, resources: LiveResources) -> Any | None:
    """Recover only the exact marker/email user if create response delivery failed."""

    matches: list[Any] = []
    per_page = 1000
    for page in range(1, 101):
        users = await asyncio.to_thread(
            admin.auth.admin.list_users,
            page,
            per_page,
        )
        matches.extend(
            user
            for user in users
            if getattr(user, "email", None) == resources.email
            and isinstance(getattr(user, "user_metadata", None), dict)
            and user.user_metadata.get("performance_e2e_marker") == resources.marker
        )
        if len(users) < per_page:
            break
    if len(matches) > 1:
        raise LiveE2EFailure(stage="fixture", error_code="AUTH_USER_IDENTITY_MISMATCH")
    return matches[0] if matches else None


def _fixture_user_id(user: Any | None, resources: LiveResources) -> UUID | None:
    if user is None or getattr(user, "email", None) != resources.email:
        return None
    metadata = getattr(user, "user_metadata", None)
    if not isinstance(metadata, dict) or metadata.get("performance_e2e_marker") != resources.marker:
        return None
    try:
        user_id = UUID(str(getattr(user, "id", "")))
    except ValueError:
        return None
    if resources.user_id is not None and user_id != resources.user_id:
        return None
    return user_id


def _matches_fixture_user(user: Any | None, resources: LiveResources) -> bool:
    return _fixture_user_id(user, resources) is not None


def _matches_fixture_contract_rows(
    rows: Sequence[Mapping[str, Any]], resources: LiveResources
) -> bool:
    if len(rows) != 1:
        return False
    row = rows[0]
    return (
        row.get("id") == str(resources.contract_id)
        and row.get("owner_id") == str(resources.user_id)
        and row.get("title") == resources.marker
        and row.get("status") == "SIGNED"
    )


def _idempotency_keys(resources: LiveResources) -> tuple[UUID, UUID, UUID]:
    return resources.upload_key, resources.extract_key, resources.confirm_key


def _idempotency_cleanup_targets(
    resources: LiveResources,
) -> list[tuple[str, UUID, UUID]]:
    if resources.report_id is None:
        return [("PERFORMANCE_REPORT_UPLOAD", resources.contract_id, resources.upload_key)]
    return [
        ("PERFORMANCE_REPORT_UPLOAD", resources.contract_id, resources.upload_key),
        ("PERFORMANCE_REPORT_EXTRACT", resources.report_id, resources.extract_key),
        ("PERFORMANCE_REPORT_CONFIRM", resources.report_id, resources.confirm_key),
    ]


def _known_cleanup_target_count(resources: LiveResources) -> int:
    return (
        int(resources.user_created)
        + int(resources.contract_created)
        + int(resources.storage_path is not None)
        + len(_idempotency_cleanup_targets(resources))
    )


def _passed_stage(
    stage: str,
    *,
    check_count: int,
    http_status: int | None = None,
) -> LiveStageSummary:
    return LiveStageSummary(
        stage=stage,
        http_status=http_status,
        check_count=check_count,
        passed_count=check_count,
    )


def _require_report_id(resources: LiveResources, *, stage: str) -> UUID:
    if resources.report_id is None:
        raise LiveE2EFailure(stage=stage, error_code="REPORT_ID_MISSING")
    return resources.report_id


def _require_user_id(resources: LiveResources, *, stage: str) -> UUID:
    if resources.user_id is None:
        raise LiveE2EFailure(stage=stage, error_code="AUTH_USER_ID_MISSING")
    return resources.user_id


def _remote_error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
        code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
    except (TypeError, ValueError):
        code = None
    return _safe_error_code(code if isinstance(code, str) else "REMOTE_HTTP_ERROR")


def _safe_error_code(value: str) -> str:
    return value if SAFE_ERROR_CODE.fullmatch(value) else "UNSAFE_REMOTE_ERROR"


def _coerce_failure(error: Exception, *, stage: str) -> LiveE2EFailure:
    if isinstance(error, LiveE2EFailure):
        return error
    return LiveE2EFailure(stage=stage, error_code="UNEXPECTED_ERROR")


def _validate_api_base_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise LiveE2EFailure(stage="preflight", error_code="INVALID_API_BASE_URL") from error
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    is_supported = parsed.scheme in {"http", "https"} and parsed.hostname in local_hosts
    if (
        not is_supported
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise LiveE2EFailure(stage="preflight", error_code="INVALID_API_BASE_URL")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("실제 FastAPI·Supabase·Upstage를 합성 광고효과 리포트 한 건으로 검증합니다.")
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="실제 외부 호출, AI 비용, 합성 데이터 생성을 명시적으로 확인합니다.",
    )
    parser.add_argument(
        "--cleanup-created-data",
        action="store_true",
        help="이번 실행이 만든 정확한 합성 사용자·계약·Storage·멱등 데이터만 정리합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not arguments.confirm_live or not arguments.cleanup_created_data:
        parser.error("실제 호출에는 --confirm-live와 --cleanup-created-data가 모두 필요합니다.")

    try:
        config = load_live_config()
        summary = asyncio.run(
            run_live_performance_e2e(
                config=config,
                cleanup_created_data=arguments.cleanup_created_data,
            )
        )
    except Exception as error:
        print(json.dumps(safe_error_payload(error), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
