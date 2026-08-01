"use client";

import Link from "next/link";
import { AppScreen } from "@/components/AppScreen";
import { StatTile, StatRow } from "@/components/StatTile";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import { won } from "@/lib/format";
import type { BadgeTone } from "@/lib/status";
import type { ContractSummary } from "@/lib/types";

export default function DashboardPage() {
  const state = useAsync(() => adapter.getDashboard(), []);
  const attentionContract = state.status === "ready"
    ? state.data.contracts.find((contract) => contract.status === "REVIEW_REQUIRED")
      ?? state.data.contracts[0]
    : null;

  return (
    <AppScreen wide>
      {/* 히어로 */}
      <header className="mb-8">
        <p className="text-[13px] font-bold text-brand700">
          계약을 읽고, 말하기 어려운 조건을 대신 정리해드려요
        </p>
        <h1 className="mt-1.5 text-3xl font-black tracking-tight text-ink lg:text-4xl">
          안녕하세요, 사장님
        </h1>
        <p className="mt-2 text-[15px] text-neutral500">
          계약서의 조건을 함께 확인하고, 필요한 조정 요청을 문서로 남길 수 있어요.
        </p>
      </header>

      {state.status === "loading" && (
        <p className="py-16 text-center text-sm text-neutral500">불러오는 중…</p>
      )}

      {state.status === "error" && (
        <div className="mx-auto max-w-md rounded-2xl border border-neutral200 p-6 text-center">
          <p className="text-sm font-bold text-neutral700">대시보드를 불러오지 못했습니다.</p>
          <p className="mt-2 text-sm text-neutral500">{state.error}</p>
          <Link
            href="/login"
            className="mt-5 inline-flex rounded-lg bg-brand800 px-4 py-2.5 text-sm font-bold text-white"
          >
            로그인 다시 하기
          </Link>
        </div>
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
          {/* 집계 타일 6개 가로배치 */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatTile size="lg" value={state.data.stats.total} label="전체 계약" />
            <StatTile size="lg" value={state.data.stats.signing} label="서명 중" />
            <StatTile size="lg" value={state.data.stats.inProgress} label="진행 중" />
            <StatTile size="lg" value={state.data.stats.completed} label="완료" />
            <StatTile
              size="lg"
              value={state.data.stats.expiringSoon}
              label="만료 임박"
              emphasis
            />
            <StatTile
              size="lg"
              value={state.data.stats.unresolvedSignals}
              label="미해결 확인 신호"
            />
          </div>

          {/* 3분할 지표 */}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <StatRow
              label="이행 대기 / 제출 / 확인 완료"
              value={`${state.data.stats.obligationPending} / ${state.data.stats.obligationSubmitted} / ${state.data.stats.obligationApproved}`}
            />
            <StatRow label="총 약정액" value={won(state.data.stats.totalCommitted)} />
            <StatRow
              label="지급 조건 충족액"
              value={won(state.data.stats.paymentConditionMet)}
            />
          </div>

          {/* 내 계약 목록 */}
          <section>
            <div className="mb-1 flex items-center justify-between border-b border-neutral200 pb-3">
              <h2 className="text-lg font-black text-ink">내 계약</h2>
              <Link
                href="/contracts/new"
                className="text-[13px] font-bold text-brand700 hover:underline"
              >
                + 새 계약서 올리기
              </Link>
            </div>
            <div>
              {state.data.contracts.map((c) => (
                <ContractRow key={c.id} contract={c} />
              ))}
            </div>
          </section>

          {/* 확인이 필요한 내용 */}
          <section>
            <h2 className="mb-3 text-lg font-black text-ink">확인이 필요한 내용</h2>
            {attentionContract && (
              <Link
                href={contractHref(attentionContract)}
                className="flex items-center justify-center rounded-2xl border border-dashed border-neutral300 bg-white/50 px-6 py-10 text-center text-sm text-neutral500 transition hover:border-brand400 hover:bg-white"
              >
                계약서의 기간과 금액을 함께 확인하고, 필요하면 조정 요청 문구를 선택할
                수 있어요.
              </Link>
            )}
          </section>

          <Link
            href="/contracts/new"
            className="flex h-12 w-fit items-center justify-center rounded-lg bg-ink px-6 text-[15px] font-bold text-white hover:bg-ink/90"
          >
            새 계약서 올리기
          </Link>
        </div>
      )}
    </AppScreen>
  );
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
