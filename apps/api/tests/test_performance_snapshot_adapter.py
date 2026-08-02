from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.adapters.supabase import SupabaseAdapter
from app.core.enums import (
    ContractStatus,
    PerformanceMetricVerificationStatus,
    PerformanceReportStatus,
)
from app.core.exceptions import ExternalStorageFailure
from app.repositories.contracts import ContractRecord
from app.repositories.performance import PerformanceReportAccess
from app.schemas.performance import (
    PerformanceConfirmedPayload,
    PerformanceExtractedPayload,
    PerformanceNonNegativeMetricCandidate,
    PerformanceReportRevision,
    PerformanceSignedMetricCandidate,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000501")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000502")
BEARER_TOKEN = "performance-snapshot-owner-token"
NOW = datetime(2026, 8, 8, 9, tzinfo=UTC)


def make_adapter(*, mode: str = "mock") -> SupabaseAdapter:
    return SupabaseAdapter(
        mode=mode,
        url="https://project.supabase.co" if mode == "live" else "",
        service_role_key="test-service-role-key" if mode == "live" else "",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )


def extracted_payload() -> PerformanceExtractedPayload:
    def non_negative(value: int | None) -> PerformanceNonNegativeMetricCandidate:
        return PerformanceNonNegativeMetricCandidate(
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

    return PerformanceExtractedPayload(
        impressions=non_negative(10_000),
        likes=non_negative(300),
        comments=non_negative(20),
        reach=non_negative(None),
        saves=non_negative(None),
        shares=non_negative(None),
        follower_net_change=PerformanceSignedMetricCandidate(
            value=None,
            source_page=None,
            source_text=None,
            confidence=0.9,
            verification_status=PerformanceMetricVerificationStatus.NOT_FOUND,
        ),
        published_content_count=non_negative(None),
    )


def confirmed_payload() -> PerformanceConfirmedPayload:
    return PerformanceConfirmedPayload(
        impressions=10_000,
        likes=300,
        comments=20,
        reach=None,
        saves=None,
        shares=None,
        follower_net_change=None,
        published_content_count=None,
        inquiries=None,
        reservations=None,
        purchases=None,
        metric_items=[
            {"key": "ad_spend", "label": "광고비", "value": 10_001, "unit": "KRW"},
            {
                "key": "impressions",
                "label": "노출",
                "value": 10_000,
                "unit": "COUNT",
            },
            {"key": "clicks", "label": "클릭", "value": 300, "unit": "COUNT"},
            {"key": "ctr", "label": "클릭률", "value": None, "unit": "PERCENT"},
            {"key": "cpc", "label": "클릭당 비용", "value": None, "unit": "KRW"},
        ],
    )


def revision(*, report_id: UUID, version: int = 1, previous_id: UUID | None = None):
    payload = confirmed_payload()
    return PerformanceReportRevision(
        id=uuid4(),
        report_id=report_id,
        version=version,
        status=PerformanceReportStatus.CONFIRMED,
        confirmed_payload=payload,
        engagement_rate=payload.calculate_engagement_rate(),
        corrected_from_revision_id=previous_id,
        correction_reason="정정" if version > 1 else None,
        confirmed_at=NOW,
        flags=[],
        inquiry_drafts=[],
    )


def raw_snapshot(
    *,
    contract_id: UUID,
    report_id: UUID,
    source_document_id: UUID,
    stored_revision: PerformanceReportRevision,
) -> dict:
    return {
        "report": {
            "id": str(report_id),
            "contract_id": str(contract_id),
            "period": "2026-08",
            "source_document_id": str(source_document_id),
            "status": stored_revision.status.value,
            "extracted_payload": extracted_payload().model_dump(mode="json"),
            "current_revision_id": str(stored_revision.id),
            "revision_count": stored_revision.version,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        },
        "revisions": [
            {
                "id": str(stored_revision.id),
                "report_id": str(report_id),
                "version": stored_revision.version,
                "status": stored_revision.status.value,
                "confirmed_payload": stored_revision.confirmed_payload.model_dump(mode="json"),
                "engagement_rate": str(stored_revision.engagement_rate),
                "corrected_from_revision_id": None,
                "correction_reason": None,
                "confirmed_at": NOW.isoformat(),
            }
        ],
        "flags": [],
        "basis_terms": [],
        "inquiry_drafts": [],
    }


class FakeResponse:
    def __init__(self, data: dict) -> None:
        self.data = data


class FakeRpc:
    def __init__(self, data: dict) -> None:
        self._data = data

    def execute(self) -> FakeResponse:
        return FakeResponse(self._data)


class RpcOnlyClient:
    def __init__(self, responses: dict[str, dict]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, params: dict) -> FakeRpc:
        self.calls.append((name, params))
        return FakeRpc(self._responses[name])

    def table(self, _name: str):
        raise AssertionError("atomic performance snapshot must not issue a table query")


@pytest.mark.asyncio
async def test_live_confirm_returns_the_rpc_snapshot_without_followup_reads(monkeypatch) -> None:
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = make_adapter(mode="live")
    contract_id = uuid4()
    report_id = uuid4()
    source_document_id = uuid4()
    stored_revision = revision(report_id=report_id)
    client = RpcOnlyClient(
        {
            "confirm_performance_report_with_audit": {
                "outcome": "CONFIRMED",
                "report_snapshot": raw_snapshot(
                    contract_id=contract_id,
                    report_id=report_id,
                    source_document_id=source_document_id,
                    stored_revision=stored_revision,
                ),
            }
        }
    )
    adapter._client = client  # type: ignore[assignment]

    result = await adapter.confirm_performance_report_with_audit(
        owner_id=OWNER_ID,
        contract_id=contract_id,
        report_id=report_id,
        expected_revision=0,
        expected_comparison_revision_id=None,
        revision=stored_revision,
    )

    assert result.outcome == "CONFIRMED"
    assert result.report is not None
    assert result.report.current_revision == stored_revision
    assert len(client.calls) == 1
    rpc_items = {
        item["key"]: item
        for item in client.calls[0][1]["p_confirmed_payload"]["metric_items"]
    }
    assert rpc_items["ctr"]["value"] == 3
    assert rpc_items["cpc"]["value"] == 33


@pytest.mark.asyncio
async def test_live_contract_snapshot_uses_one_owner_scoped_rpc(monkeypatch) -> None:
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = make_adapter(mode="live")
    contract_id = uuid4()
    report_id = uuid4()
    stored_revision = revision(report_id=report_id)
    client = RpcOnlyClient(
        {
            "get_owned_contract_performance_snapshot": {
                "outcome": "FOUND",
                "report_snapshots": [
                    raw_snapshot(
                        contract_id=contract_id,
                        report_id=report_id,
                        source_document_id=uuid4(),
                        stored_revision=stored_revision,
                    )
                ],
            }
        }
    )
    adapter._client = client  # type: ignore[assignment]

    reports = await adapter.get_owned_contract_performance_reports(
        owner_id=OWNER_ID,
        contract_id=contract_id,
    )

    assert reports is not None and [report.id for report in reports] == [report_id]
    assert client.calls == [
        (
            "get_owned_contract_performance_snapshot",
            {"p_owner_id": str(OWNER_ID), "p_contract_id": str(contract_id)},
        )
    ]


@pytest.mark.asyncio
async def test_live_snapshot_rejects_a_projection_that_disagrees_with_nested_history(
    monkeypatch,
) -> None:
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = make_adapter(mode="live")
    contract_id = uuid4()
    report_id = uuid4()
    stored_revision = revision(report_id=report_id)
    snapshot = raw_snapshot(
        contract_id=contract_id,
        report_id=report_id,
        source_document_id=uuid4(),
        stored_revision=stored_revision,
    )
    snapshot["report"]["current_revision_id"] = str(uuid4())
    adapter._client = RpcOnlyClient(  # type: ignore[assignment]
        {
            "get_owned_contract_performance_snapshot": {
                "outcome": "FOUND",
                "report_snapshots": [snapshot],
            }
        }
    )

    with pytest.raises(ExternalStorageFailure):
        await adapter.get_owned_contract_performance_reports(
            owner_id=OWNER_ID,
            contract_id=contract_id,
        )


def seed_contract(adapter: SupabaseAdapter, *, contract_id: UUID) -> None:
    adapter._mock_owned_contracts.add((OWNER_ID, contract_id))
    adapter._mock_contracts[contract_id] = ContractRecord(
        id=contract_id,
        owner_id=OWNER_ID,
        title="원자 snapshot 테스트 계약",
        counterparty_name="부산홍보대행",
        status=ContractStatus.IN_PROGRESS,
        signed_date=None,
        start_date=None,
        end_date=None,
        termination_notice_date=None,
        renewal_type=None,
        total_amount=None,
        understood_term=None,
        renewal_decision=None,
        modusign_document_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def seed_report(
    adapter: SupabaseAdapter,
    *,
    contract_id: UUID,
    period: str,
    status: PerformanceReportStatus,
) -> tuple[PerformanceReportAccess, PerformanceReportRevision | None]:
    report_id = uuid4()
    stored_revision = (
        revision(report_id=report_id) if status != PerformanceReportStatus.EXTRACTED else None
    )
    access = PerformanceReportAccess(
        id=report_id,
        contract_id=contract_id,
        period=period,
        source_document_id=uuid4(),
        status=status,
        extracted_payload=extracted_payload(),
        current_revision_id=stored_revision.id if stored_revision is not None else None,
        revision_count=1 if stored_revision is not None else 0,
        created_at=NOW,
        updated_at=NOW,
    )
    adapter._mock_performance_reports[report_id] = access
    if stored_revision is not None:
        adapter._mock_performance_report_revisions[report_id] = [stored_revision]
    return access, stored_revision


@pytest.mark.asyncio
async def test_mock_confirmation_exposes_comparison_and_period_order_conflicts() -> None:
    adapter = make_adapter()
    contract_id = uuid4()
    seed_contract(adapter, contract_id=contract_id)
    _previous, previous_revision = seed_report(
        adapter,
        contract_id=contract_id,
        period="2026-07",
        status=PerformanceReportStatus.CONFIRMED,
    )
    current, _ = seed_report(
        adapter,
        contract_id=contract_id,
        period="2026-08",
        status=PerformanceReportStatus.EXTRACTED,
    )
    requested_revision = revision(report_id=current.id)
    assert previous_revision is not None

    comparison_conflict = await adapter.confirm_performance_report_with_audit(
        owner_id=OWNER_ID,
        contract_id=contract_id,
        report_id=current.id,
        expected_revision=0,
        expected_comparison_revision_id=None,
        revision=requested_revision,
    )
    confirmed = await adapter.confirm_performance_report_with_audit(
        owner_id=OWNER_ID,
        contract_id=contract_id,
        report_id=current.id,
        expected_revision=0,
        expected_comparison_revision_id=previous_revision.id,
        revision=requested_revision,
    )

    assert comparison_conflict.outcome == "COMPARISON_REVISION_CONFLICT"
    assert confirmed.outcome == "CONFIRMED"

    older, _ = seed_report(
        adapter,
        contract_id=contract_id,
        period="2026-06",
        status=PerformanceReportStatus.EXTRACTED,
    )
    period_conflict = await adapter.confirm_performance_report_with_audit(
        owner_id=OWNER_ID,
        contract_id=contract_id,
        report_id=older.id,
        expected_revision=0,
        expected_comparison_revision_id=None,
        revision=revision(report_id=older.id),
    )

    assert period_conflict.outcome == "PERIOD_ORDER_CONFLICT"
