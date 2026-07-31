"use client";

import Link from "next/link";
import { AppScreen } from "@/components/AppScreen";
import { StatTile } from "@/components/StatTile";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import type { BadgeTone } from "@/lib/status";
import type { ContractSummary } from "@/lib/types";

export default function DashboardPage() {
  const state = useAsync(() => adapter.getDashboard(), []);
  const hasContracts = state.status === "ready" && state.data.contracts.length > 0;

  return (
    <AppScreen wide>
      {/* 히어로 — 새 계약 추가가 첫 화면의 유일한 진입점이다 */}
      <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[13px] font-bold text-brand700">
            계약을 읽고, 말하기 어려운 조건을 대신 정리해드려요
          </p>
          <h1 className="mt-1.5 text-3xl font-black tracking-tight text-ink lg:text-4xl">
            안녕하세요, 사장님
          </h1>
          <p className="mt-2 text-[15px] text-neutral500">
            계약서의 조건을 함께 확인하고, 필요한 조정 요청을 문서로 남길 수 있어요.
          </p>
        </div>
        {/* 계약이 없을 때는 빈 상태 카드의 버튼이 진입점 역할을 한다 */}
        {hasContracts && (
          <Link
            href="/contracts/new"
            className="flex h-12 flex-none items-center justify-center rounded-lg bg-ink px-6 text-[15px] font-bold text-white hover:bg-ink/90"
          >
            + 새 계약서 올리기
          </Link>
        )}
      </header>

      {state.status === "loading" && (
        <p className="py-16 text-center text-sm text-neutral500">불러오는 중…</p>
      )}

      {state.status === "ready" && state.data.contracts.length === 0 && (
        <div className="mx-auto max-w-md rounded-2xl bg-white p-8 ring-1 ring-neutral200">
          <EmptyState
            title="아직 등록한 계약이 없어요"
            code="첫 계약서 PDF를 올려보세요"
            body="내가 이해한 조건과 계약서를 대조해서, 다른 부분만 짚어드려요."
            actions={
              <Link
                href="/contracts/new"
                className="flex h-12 items-center justify-center rounded-lg bg-ink font-bold text-white"
              >
                계약서 업로드하기
              </Link>
            }
          />
        </div>
      )}

      {state.status === "ready" && state.data.contracts.length > 0 && (
        <div className="flex flex-col gap-6">
          {/* 집계 타일 — 모바일 2×2, 데스크탑 4칸 */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile size="lg" value={state.data.stats.signing} label="서명 중" />
            <StatTile size="lg" value={state.data.stats.inProgress} label="진행 중" />
            <StatTile size="lg" value={state.data.stats.completed} label="완료" />
            <StatTile
              size="lg"
              value={state.data.stats.expiringSoon}
              label="만료 임박"
              emphasis
            />
          </div>

          {/* 내 계약 목록 */}
          <section>
            <div className="mb-1 border-b border-neutral200 pb-3">
              <h2 className="text-lg font-black text-ink">내 계약</h2>
            </div>
            <div>
              {[...state.data.contracts]
                .sort((a, b) => listOrder(a) - listOrder(b))
                .map((c) => (
                  <ContractRow key={c.id} contract={c} />
                ))}
            </div>
          </section>

          {/* 광고효과 모아보기 진입 */}
          <Link
            href="/performance"
            className="flex items-center justify-between gap-4 rounded-2xl border border-neutral200 bg-white px-5 py-4 transition hover:border-brand400"
          >
            <div className="min-w-0">
              <div className="text-[15px] font-bold text-ink">광고효과 모아보기</div>
              <p className="mt-0.5 text-[12px] text-neutral500">
                계약마다 받은 리포트를 한데 모아, 약속한 조건대로 진행되는지 확인해요.
              </p>
            </div>
            <span className="flex-none text-neutral400">→</span>
          </Link>
        </div>
      )}
    </AppScreen>
  );
}

/** 만료 임박 → 진행 중 → 완료 순. 내가 볼 차례인 계약이 위로 온다. */
function listOrder(c: ContractSummary): number {
  if (c.status === "RENEWAL_DUE") return 0;
  if (c.status === "COMPLETED") return 2;
  return 1;
}

function statusBadge(c: ContractSummary): { label: string; tone: BadgeTone } {
  // 만료 임박은 내가 볼 차례 → 목록에서 유일하게 채워진 배지
  if (c.status === "RENEWAL_DUE")
    return { label: c.hint ?? `만료 D-${c.dDay}`, tone: "active" };
  // 응답 대기는 공이 상대에게 → 윤곽
  if (c.status === "NEGOTIATING")
    return { label: c.hint ?? "응답 대기", tone: "waiting" };
  return { label: c.hint ?? "진행 중", tone: "neutral" };
}

function ContractRow({ contract }: { contract: ContractSummary }) {
  const href = contractHref(contract);
  const badge = statusBadge(contract);

  return (
    <Link
      href={href}
      className="grid grid-cols-[minmax(0,1.4fr)_1fr_auto_auto] items-center gap-4 border-b border-neutral200 px-2 py-5 transition hover:bg-white/60"
    >
      <div className="min-w-0">
        <div className="truncate text-[15px] font-bold text-ink">
          {contract.title}
        </div>
        <div className="mt-0.5 text-[12px] text-neutral500">
          {contract.counterpartyName}
          {contract.date && ` · ${contract.date}`}
        </div>
      </div>
      <div className="text-sm text-neutral700">{contract.stage ?? ""}</div>
      <Badge label={badge.label} tone={badge.tone} size="sm" />
      <span className="text-neutral400">→</span>
    </Link>
  );
}

function contractHref(contract: ContractSummary): string {
  if (contract.status === "DRAFT" || contract.status === "ANALYZING") {
    return `/contracts/${contract.id}/analysis`;
  }
  if (contract.status === "NEGOTIATING") {
    return `/contracts/${contract.id}/responses`;
  }
  if (contract.status === "READY_TO_SIGN" || contract.status === "SIGNING") {
    return `/contracts/${contract.id}/signature`;
  }
  if (contract.status === "SIGNED" || contract.status === "IN_PROGRESS") {
    return `/contracts/${contract.id}/obligations`;
  }
  if (contract.status === "COMPLETED" || contract.status === "RENEWAL_DUE") {
    return `/contracts/${contract.id}/renewal`;
  }
  return `/contracts/${contract.id}`;
}
