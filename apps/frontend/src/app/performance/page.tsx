"use client";

import Link from "next/link";
import { AppScreen } from "@/components/AppScreen";
import { Card, Disclaimer, SectionTitle } from "@/components/Bits";
import { StatTile } from "@/components/StatTile";
import { useSavedReport } from "@/lib/reportDemo";

/* 전체 계약 광고효과 모아보기 — 화면 목업(기능 미구현).
   계약마다 받은 리포트에서 확인한 숫자를 한데 모아, 지금까지 집행한 광고가
   계약에서 약속한 조건대로 진행되는지 보여준다.
   실제 집계는 백엔드(리포트 추출) 연동 후 붙는다.
   데모 전용 데이터라 mock.ts(실 API 응답 모델)와 분리해 이 파일에 둔다.

   7월 리포트는 사장님이 계약별 관리 화면에서 확인·저장해야 여기에 더해진다.
   목업 단계라 그 저장 여부를 reportDemo(sessionStorage)로 공유한다. */

type ContractPerformance = {
  id: string;
  title: string;
  counterparty: string;
  /** 리포트를 아직 못 받은 계약은 null */
  channel: string | null;
  impressions: number;
  reactions: number;
  posts: number;
  reportedAt: string | null;
};

/** 파도담 카페 계약 — 7월 저장 전 기준(6월까지 확인된 값) */
const CAFE_BEFORE_JULY: ContractPerformance = {
  id: "cxn_gwanganli_cafe",
  title: "광고·마케팅 계약 · 파도담 카페",
  counterparty: "주식회사 브릿지웨이브",
  channel: "인스타그램 · 네이버 블로그",
  impressions: 27_600,
  reactions: 1_098,
  posts: 8,
  reportedAt: "2026-06-30",
};

const CONTRACTS: ContractPerformance[] = [
  CAFE_BEFORE_JULY,
  {
    id: "cxn_delivery",
    title: "배달앱 입점 계약",
    counterparty: "바다배달",
    channel: "배달앱 노출",
    impressions: 12_400,
    reactions: 386,
    posts: 0,
    reportedAt: "2026-07-20",
  },
  {
    id: "cxn_signboard",
    title: "간판 제작 계약",
    counterparty: "오늘의간판",
    channel: null,
    impressions: 0,
    reactions: 0,
    posts: 0,
    reportedAt: null,
  },
];

/** 전체 계약 합산 월별 노출 — 7월은 파도담 카페 리포트를 저장하기 전 값 */
const MONTHS = [
  { label: "5월", impressions: 16_200 },
  { label: "6월", impressions: 19_400 },
  { label: "7월", impressions: 4_400 },
];

const FINDINGS = [
  {
    contractId: "cxn_gwanganli_cafe",
    contractTitle: "광고·마케팅 계약 · 파도담 카페",
    title: "약속한 게시물 수보다 적어요",
    body: "계약서 제3조(서비스의 범위)에는 월 4건 게시로 되어 있는데, 7월 리포트에는 2건만 담겨 있어요.",
  },
  {
    contractId: "cxn_gwanganli_cafe",
    contractTitle: "광고·마케팅 계약 · 파도담 카페",
    title: "반응률이 눈에 띄게 떨어졌어요",
    body: "6월 4.0% → 7월 2.9%로 낮아졌어요. 게시물이 줄어든 것과 관련이 있는지 확인해보면 좋아요.",
  },
];

export default function AllPerformancePage() {
  const saved = useSavedReport();

  /* 저장된 7월 리포트가 있으면 해당 계약 행과 합계·월별 추이에 더한다 */
  const contracts = CONTRACTS.map((c) =>
    saved && c.id === saved.contractId
      ? {
          ...c,
          impressions: c.impressions + saved.impressions,
          reactions: c.reactions + saved.reactions,
          posts: c.posts + saved.posts,
          reportedAt: saved.savedAt,
        }
      : c,
  );
  const months = MONTHS.map((m, i) =>
    saved && i === MONTHS.length - 1
      ? { ...m, impressions: m.impressions + saved.impressions }
      : m,
  );

  const reported = contracts.filter((c) => c.reportedAt !== null);
  const totalImpressions = reported.reduce((sum, c) => sum + c.impressions, 0);
  const totalReactions = reported.reduce((sum, c) => sum + c.reactions, 0);
  const avgRate = (totalReactions / totalImpressions) * 100;

  return (
    <AppScreen
      title="광고효과 모아보기"
      size="wide"
      backHref="/dashboard"
      right={
        <span className="rounded bg-brand200 px-1.5 py-0.5 text-[10px] font-bold text-brand800">
          화면 목업 · 개발 예정
        </span>
      }
    >
      <div className="flex flex-col gap-5">
        <p className="text-[13px] leading-relaxed text-neutral700">
          계약마다 받은 리포트에서 확인한 숫자만 모았어요. 지금까지 집행한 광고가
          계약에서 약속한 조건대로 진행되고 있는지 한눈에 볼 수 있어요.
        </p>

        {saved && (
          <div className="rounded-xl border border-brand400 bg-brand50 px-4 py-3">
            <div className="text-[13px] font-bold text-brand800">
              ✓ {saved.period} 리포트가 반영됐어요
            </div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-neutral700">
              노출 {saved.impressions.toLocaleString()} · 반응{" "}
              {saved.reactions.toLocaleString()} · 게시물 {saved.posts}건이 아래
              합계에 더해졌어요.
            </p>
          </div>
        )}

        {/* 누적 지표 */}
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          <StatTile
            size="lg"
            value={totalImpressions.toLocaleString()}
            label="총 노출"
          />
          <StatTile
            size="lg"
            value={totalReactions.toLocaleString()}
            label="총 반응"
          />
          <StatTile size="lg" value={`${avgRate.toFixed(1)}%`} label="평균 반응률" />
          <StatTile
            size="lg"
            value={`${reported.length}/${contracts.length}건`}
            label="리포트 받은 계약"
          />
        </div>

        <section className="flex flex-col gap-2">
          <SectionTitle>월별 노출 추이 — 전체 계약 합계</SectionTitle>
          <Card>
            <MonthlyChart months={months} />
          </Card>
        </section>

        <section className="flex flex-col gap-2">
          <SectionTitle>계약별 성과</SectionTitle>
          <div className="flex flex-col gap-2">
            {contracts.map((contract) => (
              <ContractRow
                key={contract.id}
                contract={contract}
                justUpdated={contract.id === saved?.contractId}
              />
            ))}
          </div>
        </section>

        {/* 7월 리포트를 확인·저장해야 드러나는 문제들 */}
        {saved && (
          <section className="flex flex-col gap-2">
            <SectionTitle>짚어볼 점</SectionTitle>
            <div className="flex flex-col gap-2">
              {FINDINGS.map((f) => (
                <Link
                  key={f.title}
                  href={`/contracts/${f.contractId}/performance`}
                  className="rounded-lg border border-brand400 bg-brand50 px-3.5 py-2.5 transition hover:bg-brand100"
                >
                  <div className="text-[10px] font-bold text-neutral500">
                    {f.contractTitle}
                  </div>
                  <div className="mt-0.5 text-[13px] font-bold text-brand800">
                    ! {f.title}
                  </div>
                  <p className="mt-1 text-[12px] leading-relaxed text-neutral700">
                    {f.body}
                  </p>
                </Link>
              ))}
            </div>
          </section>
        )}

        <Disclaimer>
          지금은 화면 구성을 보여주는 목업이에요. 리포트에서 숫자를 읽어오는 기능은
          준비 중이며, 사장님이 확인한 숫자만 여기에 쌓입니다.
        </Disclaimer>
      </div>
    </AppScreen>
  );
}

/** 계약 한 건의 성과 요약 — 리포트를 못 받은 계약은 이동하지 않는다 */
function ContractRow({
  contract,
  justUpdated,
}: {
  contract: ContractPerformance;
  justUpdated: boolean;
}) {
  if (contract.reportedAt === null) {
    return (
      <div className="rounded-xl border border-dashed border-neutral300 px-4 py-3.5">
        <div className="text-[13px] font-bold text-neutral700">{contract.title}</div>
        <div className="mt-0.5 text-[11px] text-neutral500">
          {contract.counterparty} · 아직 받은 리포트가 없어요
        </div>
      </div>
    );
  }

  const rate = (contract.reactions / contract.impressions) * 100;

  return (
    <Link
      href={`/contracts/${contract.id}/performance`}
      className="flex flex-col gap-3 rounded-xl border border-neutral200 bg-white px-4 py-3.5 transition hover:border-brand400 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[13px] font-bold text-ink">
            {contract.title}
          </span>
          {justUpdated && (
            <span className="flex-none rounded bg-brand200 px-1.5 py-0.5 text-[10px] font-bold text-brand800">
              방금 반영됨
            </span>
          )}
        </div>
        <div className="mt-0.5 text-[11px] text-neutral500">
          {contract.counterparty} · {contract.channel} · {contract.reportedAt} 기준
        </div>
      </div>
      <div className="flex flex-none items-center gap-4 text-right">
        <div>
          <div className="text-[13px] font-bold text-ink">
            {contract.impressions.toLocaleString()}
          </div>
          <div className="text-[10px] text-neutral500">노출</div>
        </div>
        <div>
          <div className="text-[13px] font-bold text-ink">
            {contract.reactions.toLocaleString()}
          </div>
          <div className="text-[10px] text-neutral500">반응</div>
        </div>
        <div>
          <div className="text-[13px] font-bold text-brand700">
            {rate.toFixed(1)}%
          </div>
          <div className="text-[10px] text-neutral500">반응률</div>
        </div>
        <span className="text-neutral400">→</span>
      </div>
    </Link>
  );
}

/** 월별 노출 막대 — 라이브러리 없이 비율 막대로 표시 */
function MonthlyChart({ months }: { months: typeof MONTHS }) {
  const max = Math.max(...months.map((m) => m.impressions));
  return (
    <div className="flex items-end gap-4">
      {months.map((m, i) => {
        const last = i === months.length - 1;
        return (
          <div key={m.label} className="flex flex-1 flex-col items-center gap-1.5">
            <span className="text-[11px] font-bold text-ink">
              {m.impressions.toLocaleString()}
            </span>
            <div className="flex h-28 w-full items-end">
              <div
                className={`w-full rounded-t-lg ${last ? "bg-brand400" : "bg-neutral200"}`}
                style={{ height: `${(m.impressions / max) * 100}%` }}
              />
            </div>
            <span className="text-[11px] font-medium text-neutral700">{m.label}</span>
          </div>
        );
      })}
    </div>
  );
}
