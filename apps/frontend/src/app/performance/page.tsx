"use client";

import Link from "next/link";
import { AppScreen } from "@/components/AppScreen";
import { Card, Disclaimer, SectionTitle } from "@/components/Bits";
import { StatTile } from "@/components/StatTile";
import {
  adapter,
  isUsingMock,
  type ContractPerformance,
  type PerformanceFlag,
} from "@/lib/adapter";
import { useAsync } from "@/lib/hooks";

type ContractPerformanceRow = {
  id: string;
  title: string;
  counterparty: string;
  performance: ContractPerformance;
};

export default function AllPerformancePage() {
  const state = useAsync(async () => {
    const dashboard = await adapter.getDashboard();
    return Promise.all(
      dashboard.contracts.map(async (contract): Promise<ContractPerformanceRow> => ({
        id: contract.id,
        title: contract.title,
        counterparty: contract.counterpartyName,
        performance: await adapter.getContractPerformance(contract.id),
      })),
    );
  }, []);

  const rows = state.status === "ready" ? state.data : [];
  const points = rows.flatMap((row) => row.performance.confirmedSeries);
  const totalImpressions = points.reduce(
    (sum, point) => sum + point.confirmedPayload.impressions,
    0,
  );
  const totalReactions = points.reduce(
    (sum, point) => sum
      + point.confirmedPayload.likes
      + point.confirmedPayload.comments
      + (point.confirmedPayload.saves ?? 0)
      + (point.confirmedPayload.shares ?? 0),
    0,
  );
  const rate = totalImpressions === 0 ? null : totalReactions / totalImpressions;
  const reportedContracts = rows.filter((row) => row.performance.confirmedSeries.length > 0);
  const months = Array.from(
    points.reduce((totals, point) => {
      totals.set(point.period, (totals.get(point.period) ?? 0) + point.confirmedPayload.impressions);
      return totals;
    }, new Map<string, number>()),
    ([period, impressions]) => ({
      period,
      label: `${Number(period.slice(5, 7))}월`,
      impressions,
    }),
  ).sort((left, right) => left.period.localeCompare(right.period));
  const findings = rows.flatMap((row) =>
    row.performance.flags.map((flag) => ({ row, flag })),
  );

  return (
    <AppScreen
      title="광고효과 모아보기"
      size="wide"
      backHref="/dashboard"
      right={
        <span className="rounded bg-brand100 px-2 py-1 text-[10px] font-bold text-brand800">
          {isUsingMock ? "데모 데이터 모드" : "실 API 연결"}
        </span>
      }
    >
      <div className="flex flex-col gap-5">
        <p className="text-[13px] leading-relaxed text-neutral700">
          계약마다 받은 리포트에서 사장님이 확인한 숫자만 모았어요. 지금까지 집행한
          광고가 계약에서 약속한 조건대로 진행되고 있는지 한눈에 볼 수 있어요.
        </p>

        {state.status === "loading" && (
          <p className="py-12 text-center text-sm text-neutral500">광고효과 기록을 불러오는 중…</p>
        )}
        {state.status === "error" && (
          <p role="alert" className="rounded-lg border border-brand300 bg-brand50 px-4 py-3 text-[12px] font-bold text-brand800">
            {state.error}
          </p>
        )}

        {state.status === "ready" && (
          <>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              <StatTile size="lg" value={totalImpressions.toLocaleString()} label="총 노출" />
              <StatTile size="lg" value={totalReactions.toLocaleString()} label="총 반응" />
              <StatTile
                size="lg"
                value={rate === null ? "—" : `${(rate * 100).toFixed(2)}%`}
                label="전체 반응률"
              />
              <StatTile
                size="lg"
                value={`${reportedContracts.length}/${rows.length}건`}
                label="리포트 확인 계약"
              />
            </div>

            <section className="flex flex-col gap-2">
              <SectionTitle>월별 노출 추이 — 전체 계약 합계</SectionTitle>
              <Card>
                {months.length === 0 ? (
                  <p className="py-8 text-center text-[12px] text-neutral500">
                    아직 확인해 저장한 월별 리포트가 없어요.
                  </p>
                ) : (
                  <MonthlyChart months={months} />
                )}
              </Card>
            </section>

            <section className="flex flex-col gap-2">
              <SectionTitle>계약별 성과</SectionTitle>
              {rows.length === 0 ? (
                <Card>
                  <p className="text-center text-[12px] text-neutral500">등록된 계약이 없어요.</p>
                </Card>
              ) : (
                <div className="flex flex-col gap-2">
                  {rows.map((row) => <ContractRow key={row.id} row={row} />)}
                </div>
              )}
            </section>

            <section className="flex flex-col gap-2">
              <SectionTitle>짚어볼 점</SectionTitle>
              {findings.length === 0 ? (
                <Card>
                  <p className="text-center text-[12px] text-neutral500">
                    현재 확정된 광고효과 기록에서 별도 확인 신호가 없어요.
                  </p>
                </Card>
              ) : (
                <div className="grid gap-2 lg:grid-cols-2">
                  {findings.map(({ row, flag }) => (
                    <Link
                      key={`${row.id}-${flag.id}`}
                      href={`/contracts/${row.id}/performance`}
                      className="rounded-lg border border-brand300 bg-brand50 px-4 py-3 transition hover:bg-brand100"
                    >
                      <div className="text-[10px] font-bold text-neutral500">{row.title}</div>
                      <div className="mt-1 text-[13px] font-bold text-brand800">{flagTitle(flag)}</div>
                      <p className="mt-1 text-[12px] leading-relaxed text-neutral700">
                        {flagDescription(flag)}
                      </p>
                    </Link>
                  ))}
                </div>
              )}
            </section>
          </>
        )}

        <Disclaimer>
          확인 신호는 광고 성과 보장이나 법률 판단이 아닙니다. 문의 문안은 자동 발송되지
          않으며 사장님이 확인한 뒤 직접 전달합니다.
        </Disclaimer>
      </div>
    </AppScreen>
  );
}

function ContractRow({ row }: { row: ContractPerformanceRow }) {
  const latest = row.performance.confirmedSeries.at(-1) ?? null;
  if (!latest) {
    return (
      <Link
        href={`/contracts/${row.id}/performance`}
        className="rounded-xl border border-dashed border-neutral300 px-4 py-3.5 transition hover:border-brand400"
      >
        <div className="text-[13px] font-bold text-neutral700">{row.title}</div>
        <div className="mt-0.5 text-[11px] text-neutral500">
          {row.counterparty} · 아직 확인해 저장한 리포트가 없어요
        </div>
      </Link>
    );
  }

  const reactions = latest.confirmedPayload.likes
    + latest.confirmedPayload.comments
    + (latest.confirmedPayload.saves ?? 0)
    + (latest.confirmedPayload.shares ?? 0);

  return (
    <Link
      href={`/contracts/${row.id}/performance`}
      className="flex flex-col gap-3 rounded-xl border border-neutral200 bg-white px-4 py-3.5 transition hover:border-brand400 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
    >
      <div className="min-w-0">
        <div className="truncate text-[13px] font-bold text-ink">{row.title}</div>
        <div className="mt-0.5 text-[11px] text-neutral500">
          {row.counterparty} · {latest.period} · 버전 {latest.version}
        </div>
      </div>
      <div className="flex flex-none items-center gap-4 text-right">
        <Metric value={latest.confirmedPayload.impressions.toLocaleString()} label="노출" />
        <Metric value={reactions.toLocaleString()} label="반응" />
        <Metric
          value={latest.engagementRate === null ? "—" : `${(latest.engagementRate * 100).toFixed(2)}%`}
          label="반응률"
          emphasis
        />
        <span className="text-neutral400">→</span>
      </div>
    </Link>
  );
}

function Metric({ value, label, emphasis = false }: { value: string; label: string; emphasis?: boolean }) {
  return (
    <div>
      <div className={`text-[13px] font-bold ${emphasis ? "text-brand700" : "text-ink"}`}>{value}</div>
      <div className="text-[10px] text-neutral500">{label}</div>
    </div>
  );
}

function MonthlyChart({
  months,
}: {
  months: { period: string; label: string; impressions: number }[];
}) {
  const max = Math.max(...months.map((month) => month.impressions), 1);
  return (
    <div className="flex items-end gap-4 overflow-x-auto">
      {months.map((month, index) => {
        const last = index === months.length - 1;
        return (
          <div key={month.period} className="flex min-w-20 flex-1 flex-col items-center gap-1.5">
            <span className="text-[11px] font-bold text-ink">
              {month.impressions.toLocaleString()}
            </span>
            <div className="flex h-28 w-full items-end">
              <div
                className={`w-full rounded-t-lg ${last ? "bg-brand400" : "bg-neutral200"}`}
                style={{ height: `${Math.max((month.impressions / max) * 100, 2)}%` }}
              />
            </div>
            <span className="text-[11px] font-medium text-neutral700">{month.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function flagTitle(flag: PerformanceFlag): string {
  if (flag.flagType === "DELIVERABLE_COUNT_SHORTFALL") return "계약보다 게시물 수가 적어요";
  if (flag.flagType === "ENGAGEMENT_RATE_DROP") return "전월보다 반응률이 낮아졌어요";
  return "사장님이 확인이 필요하다고 기록했어요";
}

function flagDescription(flag: PerformanceFlag): string {
  if (flag.flagType === "DELIVERABLE_COUNT_SHORTFALL") {
    return `계약에서 확인한 월 ${flag.expectedContentCount}건과 리포트의 ${flag.actualContentCount}건이 다릅니다.`;
  }
  if (flag.flagType === "ENGAGEMENT_RATE_DROP") {
    return `반응률이 ${((flag.previousEngagementRate ?? 0) * 100).toFixed(2)}%에서 ${((flag.currentEngagementRate ?? 0) * 100).toFixed(2)}%로 낮아졌습니다.`;
  }
  return flag.issueNote ?? "확인할 내용이 기록되어 있습니다.";
}
