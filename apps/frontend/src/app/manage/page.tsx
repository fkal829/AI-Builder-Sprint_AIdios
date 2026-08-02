"use client";

import Link from "next/link";
import { AppScreen } from "@/components/AppScreen";
import { Card } from "@/components/Bits";
import { adapter, type ContractPerformance } from "@/lib/adapter";
import { useAsync } from "@/lib/hooks";
import type { ContractStatus, ContractSummary } from "@/lib/types";

type ManageableContract = {
  contract: ContractSummary;
  performance: ContractPerformance;
};

const PERFORMANCE_WRITE_STATUSES = new Set<ContractStatus>([
  "SIGNED",
  "IN_PROGRESS",
  "RENEWAL_DUE",
  "COMPLETED",
]);

export default function ManagePage() {
  const state = useAsync(async () => {
    const dashboard = await adapter.getDashboard();
    const manageable = dashboard.contracts.filter((contract) =>
      PERFORMANCE_WRITE_STATUSES.has(contract.status),
    );
    const rows = await Promise.all(
      manageable.map(async (contract): Promise<ManageableContract> => ({
        contract,
        performance: await adapter.getContractPerformance(contract.id),
      })),
    );
    return {
      rows,
      unavailable: dashboard.contracts.filter(
        (contract) => !PERFORMANCE_WRITE_STATUSES.has(contract.status),
      ),
    };
  }, []);

  return (
    <AppScreen title="이행 관리" size="wide" backHref="/dashboard">
      <div className="flex flex-col gap-6">
        <div>
          <p className="text-[13px] leading-relaxed text-neutral700">
            리포트를 등록할 계약을 먼저 선택해주세요. 선택한 계약의 월별 광고효과와
            산출물 증빙을 한곳에서 이어서 관리할 수 있어요.
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-neutral500">
            월간 리포트는 오래된 월부터 확인해야 전월 비교가 빠지지 않아요.
          </p>
        </div>

        {state.status === "loading" && (
          <p className="py-14 text-center text-sm text-neutral500">계약을 불러오는 중…</p>
        )}

        {state.status === "error" && (
          <p
            role="alert"
            className="rounded-xl border border-brand300 bg-brand50 px-4 py-3 text-[12px] font-bold text-brand800"
          >
            {state.error}
          </p>
        )}

        {state.status === "ready" && (
          <>
            <section>
              <div className="mb-3 border-b border-neutral200 pb-3">
                <h2 className="text-lg font-black text-ink">리포트를 등록할 계약</h2>
                <p className="mt-1 text-[11px] text-neutral500">
                  서명이 끝난 계약과 진행·완료된 계약에서 등록할 수 있어요.
                </p>
              </div>

              {state.data.rows.length === 0 ? (
                <Card>
                  <p className="py-6 text-center text-[12px] text-neutral500">
                    지금 리포트를 등록할 수 있는 계약이 없어요.
                  </p>
                </Card>
              ) : (
                <div className="grid gap-3 lg:grid-cols-2">
                  {state.data.rows.map(({ contract, performance }) => (
                    <ManageContractCard
                      key={contract.id}
                      contract={contract}
                      performance={performance}
                    />
                  ))}
                </div>
              )}
            </section>

            {state.data.unavailable.length > 0 && (
              <section>
                <h2 className="mb-2 text-[12px] font-bold text-neutral500">
                  아직 리포트를 등록할 수 없는 계약
                </h2>
                <div className="divide-y divide-neutral100 rounded-xl border border-neutral200 px-4">
                  {state.data.unavailable.map((contract) => (
                    <div
                      key={contract.id}
                      className="flex items-center justify-between gap-4 py-3"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-[12px] font-bold text-neutral700">
                          {contract.title}
                        </div>
                        <div className="mt-0.5 text-[10px] text-neutral500">
                          {contract.counterpartyName}
                        </div>
                      </div>
                      <span className="flex-none rounded bg-neutral100 px-2 py-1 text-[10px] font-bold text-neutral500">
                        서명 완료 후 가능
                      </span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </AppScreen>
  );
}

function ManageContractCard({
  contract,
  performance,
}: {
  contract: ContractSummary;
  performance: ContractPerformance;
}) {
  const pending = [...performance.reports]
    .filter((report) => report.status === "UPLOADED" || report.status === "EXTRACTED")
    .sort((left, right) => left.period.localeCompare(right.period))[0] ?? null;
  const latest = [...performance.confirmedSeries]
    .sort((left, right) => left.period.localeCompare(right.period))
    .at(-1) ?? null;

  return (
    <Link
      href={`/contracts/${contract.id}/performance`}
      className="group flex min-h-36 flex-col justify-between rounded-2xl border border-neutral200 bg-white p-5 transition hover:border-brand400 hover:shadow-sm"
    >
      <div>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="truncate text-[15px] font-black text-ink">{contract.title}</h3>
            <p className="mt-0.5 truncate text-[11px] text-neutral500">
              {contract.counterpartyName}
              {contract.date && ` · ${contract.date}`}
            </p>
          </div>
          <span className="flex-none rounded bg-brand50 px-2 py-1 text-[10px] font-bold text-brand800">
            {contract.stage ?? "이행 관리"}
          </span>
        </div>

        <p className="mt-4 text-[12px] font-bold text-neutral700">
          {pending
            ? `${formatPeriod(pending.period)} 리포트 확인이 남아 있어요.`
            : latest
              ? `최근 확정 ${formatPeriod(latest.period)} · 다음 권장 ${formatPeriod(nextPeriod(latest.period))}`
              : "아직 확정한 월간 리포트가 없어요."}
        </p>
      </div>

      <div className="mt-4 flex items-center justify-between text-[12px] font-bold text-brand800">
        <span>{pending ? "리포트 확인 계속하기" : "리포트 등록하기"}</span>
        <span className="transition group-hover:translate-x-0.5">→</span>
      </div>
    </Link>
  );
}

function formatPeriod(period: string): string {
  const [year, month] = period.split("-").map(Number);
  return `${year}년 ${month}월`;
}

function nextPeriod(period: string): string {
  const [year, month] = period.split("-").map(Number);
  return month === 12
    ? `${String(year + 1).padStart(4, "0")}-01`
    : `${String(year).padStart(4, "0")}-${String(month + 1).padStart(2, "0")}`;
}
