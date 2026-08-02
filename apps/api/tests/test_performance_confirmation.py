"""P2-C-3: PATCH /contracts/{contract_id}/performance-reports/{report_id}."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import SupabaseAdapter, _previous_performance_period
from app.api.dependencies import get_performance_confirmation_service, get_supabase_adapter
from app.core.enums import (
    ContractStatus,
    ExtractedField,
    ExtractedSourceType,
    ExtractedValueType,
    IdempotencyOperation,
    PerformanceMetricVerificationStatus,
    PerformanceReportStatus,
    VerificationStatus,
)
from app.core.exceptions import ExternalStorageFailure
from app.main import app
from app.repositories.analysis import AnalysisTaskRecord
from app.repositories.contracts import ContractRecord
from app.repositories.documents import DocumentRecord
from app.repositories.performance import PerformanceReportAccess
from app.schemas.analysis import Analysis, ExtractedTerm
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.performance import (
    PerformanceExtractedPayload,
    PerformanceNonNegativeMetricCandidate,
    PerformanceSignedMetricCandidate,
)
from app.services.idempotency import IdempotencyService
from app.services.performance_confirmation import (
    PerformanceConfirmationService,
    _confirmation_request_id,
    _confirmation_revision_id,
    _immediately_preceding_month,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000201")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000202")
BEARER_TOKEN = "performance-confirm-owner-token"
NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)


def test_first_ad_month_has_no_representable_previous_period() -> None:
    assert _immediately_preceding_month("0001-01") is None
    assert _previous_performance_period("0001-01") is None
    assert _immediately_preceding_month("0001-02") == "0001-01"
    assert _previous_performance_period("0001-02") == "0001-01"


@pytest.fixture
async def performance_context():
    current_time = [NOW]

    def clock() -> datetime:
        return current_time[0]

    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
        clock=clock,
    )

    async def override_adapter():
        return adapter

    async def override_confirmation_service():
        return PerformanceConfirmationService(
            access_repository=adapter,
            confirmation_repository=adapter,
            analysis_repository=adapter,
            idempotency=IdempotencyService(
                adapter,
                pending_replay_attempts=1,
                pending_replay_delay_seconds=0,
            ),
            now=clock,
        )

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_performance_confirmation_service] = override_confirmation_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, adapter, current_time
    finally:
        app.dependency_overrides.clear()


def auth_headers(*, idempotency_key: UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)
    return headers


def _candidate(value, *, signed: bool = False):
    candidate_type = (
        PerformanceSignedMetricCandidate if signed else PerformanceNonNegativeMetricCandidate
    )
    return candidate_type(
        value=value,
        source_page=1 if value is not None else None,
        source_text="리포트 원문" if value is not None else None,
        confidence=0.9,
        verification_status=(
            PerformanceMetricVerificationStatus.VERIFIED
            if value is not None
            else PerformanceMetricVerificationStatus.NOT_FOUND
        ),
    )


def seed_contract(adapter: SupabaseAdapter, *, contract_id: UUID) -> None:
    adapter._mock_owned_contracts.add((OWNER_ID, contract_id))
    adapter._mock_contracts[contract_id] = ContractRecord(
        id=contract_id,
        owner_id=OWNER_ID,
        title="광고효과 확정 테스트 계약",
        counterparty_name="부산홍보대행",
        status=ContractStatus.IN_PROGRESS,
        signed_date=date(2026, 6, 1),
        start_date=date(2026, 6, 1),
        end_date=date(2027, 5, 31),
        termination_notice_date=None,
        renewal_type=None,
        total_amount=6_000_000,
        understood_term=None,
        renewal_decision=None,
        modusign_document_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def seed_extracted_report(
    adapter: SupabaseAdapter,
    *,
    contract_id: UUID,
    period: str,
    report_id: UUID | None = None,
) -> UUID:
    report_id = report_id or uuid4()
    document_id = uuid4()
    adapter._mock_documents[document_id] = DocumentRecord(
        id=document_id,
        contract_id=contract_id,
        type=DocumentType.PERFORMANCE_REPORT,
        parse_status=DocumentParseStatus.COMPLETED,
        storage_path=f"{contract_id}/performance-reports/{report_id}/source.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        page_count=1,
        created_at=NOW,
    )
    extracted_payload = PerformanceExtractedPayload(
        impressions=_candidate(10_000),
        likes=_candidate(300),
        comments=_candidate(20),
        reach=_candidate(None),
        saves=_candidate(None),
        shares=_candidate(None),
        follower_net_change=_candidate(None, signed=True),
        published_content_count=_candidate(None),
    )
    adapter._mock_performance_reports[report_id] = PerformanceReportAccess(
        id=report_id,
        contract_id=contract_id,
        period=period,
        source_document_id=document_id,
        status=PerformanceReportStatus.EXTRACTED,
        extracted_payload=extracted_payload,
        current_revision_id=None,
        revision_count=0,
        extraction_attempt_id=None,
        extraction_started_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    return report_id


def seed_shortfall_contract_terms(
    adapter: SupabaseAdapter, *, contract_id: UUID, expected_count: int = 4
) -> None:
    document_id = uuid4()
    quantity_term = ExtractedTerm(
        id=uuid4(),
        contract_id=contract_id,
        document_id=document_id,
        source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
        field=ExtractedField.CONTENT_QUANTITY,
        value_type=ExtractedValueType.INTEGER,
        value=expected_count,
        source_page=2,
        source_text="월 4건의 콘텐츠를 게시한다.",
        confidence=0.95,
        verification_status=VerificationStatus.VERIFIED,
    )
    frequency_term = ExtractedTerm(
        id=uuid4(),
        contract_id=contract_id,
        document_id=document_id,
        source_type=ExtractedSourceType.CONTRACT_DOCUMENT,
        field=ExtractedField.POSTING_FREQUENCY,
        value_type=ExtractedValueType.TEXT,
        value="매월",
        source_page=2,
        source_text="매월 정기 게시한다.",
        confidence=0.93,
        verification_status=VerificationStatus.VERIFIED,
    )
    task_id = uuid4()
    adapter._mock_analysis_tasks[task_id] = AnalysisTaskRecord(
        id=task_id,
        contract_id=contract_id,
        document_id=document_id,
        supporting_document_ids=(),
        status="COMPLETED",
        attempt_count=1,
        error_code=None,
        result=Analysis(
            contract_id=contract_id,
            extracted_terms=[quantity_term, frequency_term],
            review_items=[],
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def confirmation_payload(**overrides) -> dict:
    payload = {
        "expected_revision": 0,
        "confirmed_payload": {
            "impressions": 10_000,
            "likes": 300,
            "comments": 20,
            "reach": None,
            "saves": None,
            "shares": None,
            "follower_net_change": None,
            "published_content_count": None,
            "inquiries": None,
            "reservations": None,
            "purchases": None,
        },
        "has_issue": False,
        "issue_note": None,
        "correction_reason": None,
    }
    payload.update(overrides)
    return payload


def editable_metric_items(
    *, custom_label: str | None = "맞춤 지표", custom_value: float = 1.25
) -> list[dict]:
    items = [
        {"key": "ad_spend", "label": "광고비", "value": 10_001, "unit": "KRW"},
        {"key": "impressions", "label": "노출", "value": 10_000, "unit": "COUNT"},
        {"key": "clicks", "label": "클릭", "value": 300, "unit": "COUNT"},
        {"key": "ctr", "label": "클릭률", "value": None, "unit": "PERCENT"},
        {"key": "cpc", "label": "클릭당 비용", "value": None, "unit": "KRW"},
        {
            "key": "published_content_count",
            "label": "게시물 수",
            "value": None,
            "unit": "COUNT",
        },
    ]
    if custom_label is not None:
        items.append(
            {
                "key": "custom_metric",
                "label": custom_label,
                "value": custom_value,
                "unit": "NUMBER",
            }
        )
    return items


async def confirm(
    client: AsyncClient,
    *,
    contract_id: UUID,
    report_id: UUID,
    body: dict,
    idempotency_key: UUID | None = None,
):
    return await client.patch(
        f"/api/v1/contracts/{contract_id}/performance-reports/{report_id}",
        headers=auth_headers(idempotency_key=idempotency_key or uuid4()),
        json=body,
    )


def confirmation_idempotency_records(adapter: SupabaseAdapter):
    return [
        record
        for record in adapter.mock_idempotency_records
        if record.operation is IdempotencyOperation.PERFORMANCE_REPORT_CONFIRM
    ]


async def test_first_confirmation_creates_version_one(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")

    response = await confirm(
        client, contract_id=contract_id, report_id=report_id, body=confirmation_payload()
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "CONFIRMED"
    assert data["revision_count"] == 1
    assert data["current_revision"]["version"] == 1
    assert isinstance(data["current_revision"]["engagement_rate"], int | float)
    assert data["current_revision"]["flags"] == []


async def test_metric_items_are_derived_and_preserved_across_edit_and_delete_revisions(
    performance_context,
) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")

    first_payload = confirmation_payload()["confirmed_payload"]
    first_payload["metric_items"] = editable_metric_items()
    first = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(confirmed_payload=first_payload),
    )
    assert first.status_code == 200
    first_response_items = first.json()["data"]["current_revision"]["confirmed_payload"][
        "metric_items"
    ]
    first_items = {
        item["key"]: item
        for item in first_response_items
    }
    assert first_items["ctr"]["value"] == 3
    assert first_items["cpc"]["value"] == 33
    assert first_items["custom_metric"]["label"] == "맞춤 지표"

    edited_payload = confirmation_payload()["confirmed_payload"]
    edited_payload["metric_items"] = editable_metric_items(
        custom_label="수정한 지표", custom_value=2.5
    )
    edited = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(
            expected_revision=1,
            correction_reason="맞춤 지표 수정",
            confirmed_payload=edited_payload,
        ),
    )
    assert edited.status_code == 200

    deleted_payload = confirmation_payload()["confirmed_payload"]
    deleted_payload["metric_items"] = editable_metric_items(custom_label=None)
    deleted = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(
            expected_revision=2,
            correction_reason="맞춤 지표 삭제",
            confirmed_payload=deleted_payload,
        ),
    )

    assert deleted.status_code == 200
    revisions = deleted.json()["data"]["revisions"]
    assert [revision["version"] for revision in revisions] == [1, 2, 3]
    first_history = {
        item["key"]: item for item in revisions[0]["confirmed_payload"]["metric_items"]
    }
    edited_history = {
        item["key"]: item for item in revisions[1]["confirmed_payload"]["metric_items"]
    }
    current_items = {
        item["key"]: item for item in revisions[2]["confirmed_payload"]["metric_items"]
    }
    assert first_history["custom_metric"] == {
        "key": "custom_metric",
        "label": "맞춤 지표",
        "value": 1.25,
        "unit": "NUMBER",
    }
    assert edited_history["custom_metric"]["label"] == "수정한 지표"
    assert edited_history["custom_metric"]["value"] == 2.5
    assert "custom_metric" not in current_items


async def test_first_confirmation_flags_deliverable_shortfall(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    seed_shortfall_contract_terms(adapter, contract_id=contract_id, expected_count=4)

    response = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(
            confirmed_payload={
                **confirmation_payload()["confirmed_payload"],
                "published_content_count": 3,
            }
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "FLAGGED"
    flags = data["current_revision"]["flags"]
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "DELIVERABLE_COUNT_SHORTFALL"
    assert flags[0]["expected_content_count"] == 4
    assert flags[0]["actual_content_count"] == 3
    drafts = data["current_revision"]["inquiry_drafts"]
    assert len(drafts) == 1
    assert drafts[0]["flag_id"] == flags[0]["id"]
    assert "4건" in drafts[0]["text"]


async def test_first_confirmation_flags_owner_reported_issue(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")

    response = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(has_issue=True, issue_note="숫자가 이상해 보여요"),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "FLAGGED"
    flags = data["current_revision"]["flags"]
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "OWNER_REPORTED_ISSUE"
    assert flags[0]["issue_note"] == "숫자가 이상해 보여요"


async def test_correction_appends_new_version_and_keeps_history(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")

    first = await confirm(
        client, contract_id=contract_id, report_id=report_id, body=confirmation_payload()
    )
    assert first.status_code == 200

    corrected = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(
            expected_revision=1,
            correction_reason="노출 수 오타 수정",
            confirmed_payload={
                **confirmation_payload()["confirmed_payload"],
                "impressions": 12_500,
            },
        ),
    )

    assert corrected.status_code == 200
    data = corrected.json()["data"]
    assert data["revision_count"] == 2
    assert [r["version"] for r in data["revisions"]] == [1, 2]
    assert data["revisions"][0]["confirmed_payload"]["impressions"] == 10_000
    assert data["current_revision"]["confirmed_payload"]["impressions"] == 12_500
    assert data["current_revision"]["corrected_from_revision_id"] == data["revisions"][0]["id"]


async def test_correction_with_stale_expected_revision_is_rejected(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    first = await confirm(
        client, contract_id=contract_id, report_id=report_id, body=confirmation_payload()
    )
    assert first.status_code == 200

    stale = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(expected_revision=0),
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REPORT_REVISION_CONFLICT"


async def test_correction_blocked_when_a_later_month_is_already_confirmed(
    performance_context,
) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    july_report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    august_report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-08")

    july_confirmed = await confirm(
        client, contract_id=contract_id, report_id=july_report_id, body=confirmation_payload()
    )
    assert july_confirmed.status_code == 200
    august_confirmed = await confirm(
        client, contract_id=contract_id, report_id=august_report_id, body=confirmation_payload()
    )
    assert august_confirmed.status_code == 200

    blocked = await confirm(
        client,
        contract_id=contract_id,
        report_id=july_report_id,
        body=confirmation_payload(expected_revision=1, correction_reason="7월 정정 시도"),
    )

    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "REPORT_CORRECTION_DEPENDENCY_EXISTS"


async def test_confirmation_rejected_before_extraction(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    existing = adapter._mock_performance_reports[report_id]
    key = uuid4()
    adapter._mock_performance_reports[report_id] = PerformanceReportAccess(
        id=report_id,
        contract_id=contract_id,
        period="2026-07",
        source_document_id=existing.source_document_id,
        status=PerformanceReportStatus.UPLOADED,
        extracted_payload=None,
        current_revision_id=None,
        revision_count=0,
        extraction_attempt_id=None,
        extraction_started_at=None,
        created_at=NOW,
        updated_at=NOW,
    )

    response = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert "지표를 추출하기 전" in response.json()["error"]["message"]
    assert confirmation_idempotency_records(adapter) == []

    adapter._mock_performance_reports[report_id] = existing
    retried = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )

    assert retried.status_code == 200
    assert confirmation_idempotency_records(adapter)[0].response_status == 200


async def test_engagement_rate_drop_detected_across_two_months(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    july_report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    august_report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-08")

    # July: engagement rate 4% (40/1000).
    july = await confirm(
        client,
        contract_id=contract_id,
        report_id=july_report_id,
        body=confirmation_payload(
            confirmed_payload={
                "impressions": 1_000,
                "likes": 40,
                "comments": 0,
                "reach": None,
                "saves": None,
                "shares": None,
                "follower_net_change": None,
                "published_content_count": None,
                "inquiries": None,
                "reservations": None,
                "purchases": None,
            }
        ),
    )
    assert july.status_code == 200
    assert july.json()["data"]["status"] == "CONFIRMED"

    # August: engagement rate 3% (30/1000) — 1.0pp absolute, 25% relative drop.
    august = await confirm(
        client,
        contract_id=contract_id,
        report_id=august_report_id,
        body=confirmation_payload(
            confirmed_payload={
                "impressions": 1_000,
                "likes": 30,
                "comments": 0,
                "reach": None,
                "saves": None,
                "shares": None,
                "follower_net_change": None,
                "published_content_count": None,
                "inquiries": None,
                "reservations": None,
                "purchases": None,
            }
        ),
    )

    assert august.status_code == 200
    data = august.json()["data"]
    assert data["status"] == "FLAGGED"
    flags = data["current_revision"]["flags"]
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "ENGAGEMENT_RATE_DROP"
    assert isinstance(flags[0]["previous_engagement_rate"], int | float)
    assert isinstance(flags[0]["current_engagement_rate"], int | float)
    drafts = data["current_revision"]["inquiry_drafts"]
    assert "2026-07" in drafts[0]["text"]
    assert "2026-08" in drafts[0]["text"]


async def test_idempotent_replay_returns_identical_response_without_new_revision(
    performance_context,
) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    key = uuid4()

    first = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )
    replay = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert first.headers["X-Request-ID"] == replay.headers["X-Request-ID"]
    assert first.headers["X-Request-ID"] == first.json()["requestId"]
    assert len(adapter.mock_performance_report_revisions[report_id]) == 1


async def test_commit_unknown_recovers_exact_revision_and_logical_first_response(
    performance_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    key = uuid4()
    original = adapter.confirm_performance_report_with_audit
    calls = 0

    async def commit_then_lose_response(**kwargs):
        nonlocal calls
        calls += 1
        await original(**kwargs)
        raise ExternalStorageFailure("private confirmation rpc response lost")

    monkeypatch.setattr(
        adapter,
        "confirm_performance_report_with_audit",
        commit_then_lose_response,
    )

    first = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "private confirmation" not in first.text
    assert calls == 1
    assert len(adapter.mock_performance_report_revisions[report_id]) == 1
    pending = confirmation_idempotency_records(adapter)
    assert len(pending) == 1
    assert pending[0].response_status is None

    recovered = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )

    expected_request_id = _confirmation_request_id(
        owner_id=OWNER_ID,
        contract_id=contract_id,
        report_id=report_id,
        idempotency_key=key,
    )
    expected_revision_id = _confirmation_revision_id(
        owner_id=OWNER_ID,
        contract_id=contract_id,
        report_id=report_id,
        idempotency_key=key,
    )
    assert recovered.status_code == 200
    assert recovered.json()["requestId"] == expected_request_id
    assert recovered.headers["X-Request-ID"] == expected_request_id
    assert UUID(recovered.json()["data"]["current_revision"]["id"]) == expected_revision_id
    assert calls == 1
    assert len(adapter.mock_performance_report_revisions[report_id]) == 1
    assert len(adapter.mock_audit_events) == 1
    completed = confirmation_idempotency_records(adapter)
    assert len(completed) == 1
    assert completed[0].response_status == 200
    assert completed[0].response_payload == {
        "report": recovered.json()["data"],
        "requestId": expected_request_id,
    }


async def test_pre_commit_infrastructure_failure_abandons_key_and_can_retry(
    performance_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    key = uuid4()
    original = adapter.get_latest_analysis_task
    calls = 0

    async def fail_once_before_confirmation(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ExternalStorageFailure("private analysis lookup unavailable")
        return await original(**kwargs)

    monkeypatch.setattr(
        adapter,
        "get_latest_analysis_task",
        fail_once_before_confirmation,
    )

    failed = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "private analysis" not in failed.text
    assert confirmation_idempotency_records(adapter) == []
    assert adapter.mock_performance_report_revisions.get(report_id) is None

    retried = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )

    assert retried.status_code == 200
    assert len(adapter.mock_performance_report_revisions[report_id]) == 1
    assert confirmation_idempotency_records(adapter)[0].response_status == 200


async def test_pending_commit_is_not_recovered_after_another_revision_becomes_current(
    performance_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    pending_key = uuid4()
    later_key = uuid4()
    original = adapter.confirm_performance_report_with_audit
    calls = 0

    async def lose_only_first_response(**kwargs):
        nonlocal calls
        calls += 1
        result = await original(**kwargs)
        if calls == 1:
            raise ExternalStorageFailure("first confirmation response lost")
        return result

    monkeypatch.setattr(
        adapter,
        "confirm_performance_report_with_audit",
        lose_only_first_response,
    )

    first = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=pending_key,
    )
    assert first.status_code == 503

    later = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(
            expected_revision=1,
            correction_reason="다른 요청이 먼저 정정함",
            confirmed_payload={
                **confirmation_payload()["confirmed_payload"],
                "impressions": 12_500,
            },
        ),
        idempotency_key=later_key,
    )
    assert later.status_code == 200
    assert later.json()["data"]["revision_count"] == 2

    stale_recovery = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=pending_key,
    )

    assert stale_recovery.status_code == 409
    assert stale_recovery.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert calls == 2
    assert len(adapter.mock_performance_report_revisions[report_id]) == 2
    records = confirmation_idempotency_records(adapter)
    pending_record = next(record for record in records if record.key == pending_key)
    later_record = next(record for record in records if record.key == later_key)
    assert pending_record.response_status is None
    assert later_record.response_status == 200


async def test_different_body_with_same_idempotency_key_conflicts(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    key = uuid4()

    first = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(),
        idempotency_key=key,
    )
    assert first.status_code == 200

    conflicting = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(has_issue=True, issue_note="다른 요청"),
        idempotency_key=key,
    )

    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_requires_authentication_and_idempotency_key(performance_context) -> None:
    client, adapter, _now = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")

    no_auth = await client.patch(
        f"/api/v1/contracts/{contract_id}/performance-reports/{report_id}",
        headers={"Idempotency-Key": str(uuid4())},
        json=confirmation_payload(),
    )
    no_key = await client.patch(
        f"/api/v1/contracts/{contract_id}/performance-reports/{report_id}",
        headers=auth_headers(),
        json=confirmation_payload(),
    )
    not_found = await confirm(
        client, contract_id=contract_id, report_id=uuid4(), body=confirmation_payload()
    )

    assert no_auth.status_code == 401
    assert no_key.status_code == 422
    assert not_found.status_code == 404


async def test_live_adapter_calls_confirm_rpc_with_expected_params(monkeypatch) -> None:
    from app.schemas.performance import PerformanceConfirmedPayload, PerformanceReportRevision

    class FakeResponse:
        data = {"outcome": "NOT_FOUND"}

    class FakeRpc:
        def execute(self):
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def rpc(self, name, params):
            self.calls.append((name, params))
            return FakeRpc()

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    fake_client = FakeClient()
    monkeypatch.setattr("app.adapters.supabase.create_client", lambda *_args: fake_client)
    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = SupabaseAdapter(
        mode="live",
        url="https://project.supabase.co",
        service_role_key="test-service-role-key",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    owner_id = uuid4()
    contract_id = uuid4()
    report_id = uuid4()
    revision_id = uuid4()
    payload = PerformanceConfirmedPayload(
        impressions=1_000,
        likes=40,
        comments=0,
        reach=None,
        saves=None,
        shares=None,
        follower_net_change=None,
        published_content_count=None,
        inquiries=None,
        reservations=None,
        purchases=None,
    )
    revision = PerformanceReportRevision(
        id=revision_id,
        report_id=report_id,
        version=1,
        status="CONFIRMED",
        confirmed_payload=payload,
        engagement_rate=payload.calculate_engagement_rate(),
        corrected_from_revision_id=None,
        correction_reason=None,
        confirmed_at=NOW,
        flags=[],
        inquiry_drafts=[],
    )

    result = await adapter.confirm_performance_report_with_audit(
        owner_id=owner_id,
        contract_id=contract_id,
        report_id=report_id,
        expected_revision=0,
        expected_comparison_revision_id=None,
        revision=revision,
    )

    assert result.outcome == "NOT_FOUND"
    assert fake_client.calls == [
        (
            "confirm_performance_report_with_audit",
            {
                "p_owner_id": str(owner_id),
                "p_contract_id": str(contract_id),
                "p_report_id": str(report_id),
                "p_expected_revision": 0,
                "p_expected_comparison_revision_id": None,
                "p_revision_id": str(revision_id),
                "p_status": "CONFIRMED",
                "p_confirmed_payload": payload.model_dump(mode="json"),
                "p_engagement_rate": str(payload.calculate_engagement_rate()),
                "p_corrected_from_revision_id": None,
                "p_correction_reason": None,
                "p_confirmed_at": NOW.isoformat(),
                "p_flags": [],
                "p_inquiry_drafts": [],
            },
        )
    ]
