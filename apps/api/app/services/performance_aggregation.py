"""P2-C-4: GET .../performance — month-by-month record and contract cross-check.

Pure read: no AI, no state change, no audit event. Reuses P2-C-3's
`PerformanceReportRepository.get_report` to assemble each report's full
append-only history, then projects the confirmed months into
`ContractPerformance`. That schema's own validator (app/schemas/performance.py)
already enforces the "only the latest confirmed revision per month, in the
same order, feeds confirmed_series/flags/inquiry_drafts" invariant — so a
logic bug here surfaces as a `ValidationError`, not a silently wrong response.
"""

from uuid import UUID

from app.core.enums import PerformanceReportStatus
from app.core.exceptions import ResourceNotFound
from app.repositories.performance import PerformanceAccessRepository, PerformanceReportRepository
from app.schemas.performance import ContractPerformance, PerformanceConfirmedSeriesPoint
from app.services.performance import PerformanceAccessGuard

_CONFIRMED_STATUSES = frozenset(
    {PerformanceReportStatus.CONFIRMED, PerformanceReportStatus.FLAGGED}
)


class PerformanceAggregationService:
    def __init__(
        self,
        *,
        access_repository: PerformanceAccessRepository,
        report_repository: PerformanceReportRepository,
    ) -> None:
        self._access_repository = access_repository
        self._report_repository = report_repository
        self._guard = PerformanceAccessGuard(access_repository)

    async def get_contract_performance(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
    ) -> ContractPerformance:
        await self._guard.require_contract(owner_id=owner_id, contract_id=contract_id)

        access_rows = await self._access_repository.list_owned_performance_reports(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if access_rows is None:
            # The guard above already proved ownership; a None here only
            # means the contract vanished between the two reads.
            raise ResourceNotFound()

        ordered_access = sorted(access_rows, key=lambda row: row.period)
        reports = []
        for row in ordered_access:
            report = await self._report_repository.get_report(report_id=row.id)
            if report is None:
                # Same race as above: the report existed a moment ago.
                raise ResourceNotFound()
            reports.append(report)

        confirmed_reports = [report for report in reports if report.status in _CONFIRMED_STATUSES]
        confirmed_series = [
            PerformanceConfirmedSeriesPoint(
                report_id=report.id,
                report_revision_id=report.current_revision.id,
                period=report.period,
                version=report.current_revision.version,
                status=report.current_revision.status,
                confirmed_payload=report.current_revision.confirmed_payload,
                engagement_rate=report.current_revision.engagement_rate,
                confirmed_at=report.current_revision.confirmed_at,
            )
            for report in confirmed_reports
            if report.current_revision is not None
        ]
        flags = [
            flag
            for report in confirmed_reports
            if report.current_revision is not None
            for flag in report.current_revision.flags
        ]
        inquiry_drafts = [
            draft
            for report in confirmed_reports
            if report.current_revision is not None
            for draft in report.current_revision.inquiry_drafts
        ]

        return ContractPerformance(
            contract_id=contract_id,
            reports=reports,
            confirmed_series=confirmed_series,
            flags=flags,
            inquiry_drafts=inquiry_drafts,
        )
