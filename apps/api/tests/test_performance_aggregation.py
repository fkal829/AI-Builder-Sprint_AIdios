"""P2-C-4: GET /contracts/{contract_id}/performance."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_performance_confirmation_service, get_supabase_adapter
from app.core.enums import (
    ContractStatus,
    PerformanceMetricVerificationStatus,
    PerformanceReportStatus,
)
from app.main import app
from app.repositories.contracts import ContractRecord
from app.repositories.documents import DocumentRecord
from app.repositories.performance import PerformanceReportAccess
from app.schemas.documents import DocumentParseStatus, DocumentType
from app.schemas.performance import (
    PerformanceExtractedPayload,
    PerformanceNonNegativeMetricCandidate,
    PerformanceSignedMetricCandidate,
)
from app.services.idempotency import IdempotencyService
from app.services.performance_confirmation import PerformanceConfirmationService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000301")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000302")
BEARER_TOKEN = "performance-aggregation-owner-token"
NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)


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
            idempotency=IdempotencyService(adapter),
            now=clock,
        )

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_performance_confirmation_service] = (
        override_confirmation_service
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, adapter
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
        title="광고효과 집계 테스트 계약",
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
    status: PerformanceReportStatus = PerformanceReportStatus.EXTRACTED,
) -> UUID:
    report_id = uuid4()
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
    extracted_payload = (
        PerformanceExtractedPayload(
            impressions=_candidate(10_000),
            likes=_candidate(300),
            comments=_candidate(20),
            reach=_candidate(None),
            saves=_candidate(None),
            shares=_candidate(None),
            follower_net_change=_candidate(None, signed=True),
            published_content_count=_candidate(None),
        )
        if status != PerformanceReportStatus.UPLOADED
        else None
    )
    adapter._mock_performance_reports[report_id] = PerformanceReportAccess(
        id=report_id,
        contract_id=contract_id,
        period=period,
        source_document_id=document_id,
        status=status,
        extracted_payload=extracted_payload,
        current_revision_id=None,
        revision_count=0,
        extraction_attempt_id=None,
        extraction_started_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    return report_id


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


async def confirm(client: AsyncClient, *, contract_id: UUID, report_id: UUID, body: dict):
    return await client.patch(
        f"/api/v1/contracts/{contract_id}/performance-reports/{report_id}",
        headers=auth_headers(idempotency_key=uuid4()),
        json=body,
    )


async def get_performance(client: AsyncClient, *, contract_id: UUID):
    return await client.get(
        f"/api/v1/contracts/{contract_id}/performance",
        headers=auth_headers(),
    )


async def test_contract_with_no_reports_returns_empty_aggregation(performance_context) -> None:
    client, adapter = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)

    response = await get_performance(client, contract_id=contract_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "contract_id": str(contract_id),
        "reports": [],
        "confirmed_series": [],
        "flags": [],
        "inquiry_drafts": [],
    }


async def test_uploaded_report_is_listed_but_excluded_from_confirmed_series(
    performance_context,
) -> None:
    client, adapter = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    seed_extracted_report(
        adapter,
        contract_id=contract_id,
        period="2026-07",
        status=PerformanceReportStatus.UPLOADED,
    )

    response = await get_performance(client, contract_id=contract_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["reports"]) == 1
    assert data["reports"][0]["status"] == "UPLOADED"
    assert data["confirmed_series"] == []
    assert data["flags"] == []


async def test_confirmed_report_appears_in_series_without_flags(performance_context) -> None:
    client, adapter = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    confirmed = await confirm(
        client, contract_id=contract_id, report_id=report_id, body=confirmation_payload()
    )
    assert confirmed.status_code == 200

    response = await get_performance(client, contract_id=contract_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["reports"]) == 1
    assert len(data["confirmed_series"]) == 1
    assert data["confirmed_series"][0]["period"] == "2026-07"
    assert data["confirmed_series"][0]["status"] == "CONFIRMED"
    assert data["flags"] == []
    assert data["inquiry_drafts"] == []


async def test_flagged_report_surfaces_flags_and_inquiry_drafts(performance_context) -> None:
    client, adapter = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    confirmed = await confirm(
        client,
        contract_id=contract_id,
        report_id=report_id,
        body=confirmation_payload(has_issue=True, issue_note="숫자가 이상해 보여요"),
    )
    assert confirmed.status_code == 200

    response = await get_performance(client, contract_id=contract_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["confirmed_series"][0]["status"] == "FLAGGED"
    assert len(data["flags"]) == 1
    assert data["flags"][0]["flag_type"] == "OWNER_REPORTED_ISSUE"
    assert len(data["inquiry_drafts"]) == 1
    assert data["inquiry_drafts"][0]["flag_id"] == data["flags"][0]["id"]


async def test_correction_history_kept_but_series_reflects_only_current_revision(
    performance_context,
) -> None:
    client, adapter = performance_context
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

    response = await get_performance(client, contract_id=contract_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["reports"]) == 1
    assert len(data["reports"][0]["revisions"]) == 2
    assert len(data["confirmed_series"]) == 1
    assert data["confirmed_series"][0]["version"] == 2
    assert data["confirmed_series"][0]["confirmed_payload"]["impressions"] == 12_500


async def test_multiple_months_are_sorted_and_only_confirmed_ones_aggregate(
    performance_context,
) -> None:
    client, adapter = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    august_report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-08")
    july_report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    seed_extracted_report(
        adapter,
        contract_id=contract_id,
        period="2026-09",
        status=PerformanceReportStatus.UPLOADED,
    )
    july_confirmed = await confirm(
        client, contract_id=contract_id, report_id=july_report_id, body=confirmation_payload()
    )
    august_confirmed = await confirm(
        client, contract_id=contract_id, report_id=august_report_id, body=confirmation_payload()
    )
    assert july_confirmed.status_code == 200
    assert august_confirmed.status_code == 200

    response = await get_performance(client, contract_id=contract_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert [report["period"] for report in data["reports"]] == ["2026-07", "2026-08", "2026-09"]
    assert [point["period"] for point in data["confirmed_series"]] == ["2026-07", "2026-08"]


async def test_get_performance_does_not_write_any_audit_event(performance_context) -> None:
    client, adapter = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    report_id = seed_extracted_report(adapter, contract_id=contract_id, period="2026-07")
    confirmed = await confirm(
        client, contract_id=contract_id, report_id=report_id, body=confirmation_payload()
    )
    assert confirmed.status_code == 200
    events_before = len(adapter.mock_audit_events)

    for _ in range(3):
        response = await get_performance(client, contract_id=contract_id)
        assert response.status_code == 200

    assert len(adapter.mock_audit_events) == events_before


async def test_requires_authentication_and_ownership(performance_context) -> None:
    client, adapter = performance_context
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)

    no_auth = await client.get(f"/api/v1/contracts/{contract_id}/performance")
    not_found = await get_performance(client, contract_id=uuid4())

    assert no_auth.status_code == 401
    assert not_found.status_code == 404
