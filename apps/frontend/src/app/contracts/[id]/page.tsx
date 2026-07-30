"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { LayerBlock } from "@/components/LayerBlock";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import {
  loadUnderstood,
  summarizeUnderstood,
  type UnderstoodKey,
} from "@/lib/understood";
import type { ClauseRisk, ContractDetail, DocClause, UnderstoodTerm } from "@/lib/types";

/* ④ 계약서 원문(좌) ↔ 분석 결과(우) 뷰어 — 참고 이미지 레이아웃 기준.
   위험도(고/중/저)는 소상공인 관점의 '확인이 필요한 정도'를 표시하며 위법성 판정이 아니다. */

/** 위험도 색 — 테마엔 red/green이 없어 명시 hex로 고정(참고 이미지의 빨강/노랑/초록). */
const RISK: Record<
  ClauseRisk,
  { label: string; badgeBg: string; badgeFg: string; tileBg: string; tileFg: string }
> = {
  high: { label: "고위험", badgeBg: "#fbe3e3", badgeFg: "#c0392b", tileBg: "#fdeceb", tileFg: "#c0392b" },
  mid: { label: "중위험", badgeBg: "#faeed0", badgeFg: "#a9752a", tileBg: "#fdf7e8", tileFg: "#b8842a" },
  low: { label: "저위험", badgeBg: "#e2f1e8", badgeFg: "#2e7d52", tileBg: "#eaf6ee", tileFg: "#2e7d52" },
};

/** localStorage 설문이 없을 때 목업 understood를 설문 응답 형태로 변환(폴백) */
function termToAnswers(t: UnderstoodTerm): Partial<Record<UnderstoodKey, string>> {
  return {
    durationText: t.durationText,
    monthlyAmount: t.monthlyAmount,
    totalAmount: t.totalAmount,
    refundText: t.refundText,
    terminationText: t.terminationText,
  };
}

function RiskBadge({ risk }: { risk: ClauseRisk }) {
  const r = RISK[risk];
  return (
    <span
      className="inline-flex flex-none items-center rounded-full px-2 py-0.5 text-[11px] font-bold"
      style={{ backgroundColor: r.badgeBg, color: r.badgeFg }}
    >
      {r.label}
    </span>
  );
}

export default function AnalysisViewerPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(id), [id]);

  return (
    <AppScreen
      size="wide"
      backHref="/dashboard"
      footer={
        state.status === "ready" ? (
          <CTAButton href={`/contracts/${id}/request`}>조정 요청서 만들기</CTAButton>
        ) : undefined
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}
      {state.status === "ready" && (
        <ViewerBody data={state.data} contractId={id} onOpenClause={(cid) => router.push(`/contracts/${id}/clauses/${cid}`)} />
      )}
    </AppScreen>
  );
}

function ViewerBody({
  data,
  contractId,
  onOpenClause,
}: {
  data: ContractDetail;
  contractId: string;
  onOpenClause: (clauseId: string) => void;
}) {
  const { document: doc } = data;
  const [selected, setSelected] = useState<string | null>(null);
  const [fontScale, setFontScale] = useState(1);
  const origRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // 설문 응답(localStorage) → 요약. 없으면 목업 understood로 폴백.
  const [answers, setAnswers] = useState<Partial<Record<UnderstoodKey, string>> | null>(null);
  useEffect(() => {
    // localStorage는 클라이언트 전용이라 마운트 후 1회 읽는다(설문 없으면 목업 폴백)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAnswers(loadUnderstood(contractId) ?? termToAnswers(data.understood));
  }, [contractId, data.understood]);
  const summary = useMemo(() => summarizeUnderstood(answers), [answers]);

  const counts = useMemo(() => {
    const c = { high: 0, mid: 0, low: 0 };
    doc.clauses.forEach((cl) => (c[cl.risk] += 1));
    return c;
  }, [doc.clauses]);

  const goToClause = (cid: string) => {
    setSelected(cid);
    const container = origRef.current;
    const el = container?.querySelector(`#clause-${cid}`) as HTMLElement | null;
    if (!container || !el) return;
    // 좌측 원문 패널(스크롤 컨테이너)을 해당 조항 상단으로 스크롤
    const top =
      el.getBoundingClientRect().top -
      container.getBoundingClientRect().top +
      container.scrollTop -
      8;
    // behavior:"smooth"는 reduced-motion 환경에서 무시될 수 있어 직접 지정
    container.scrollTop = Math.max(0, top);
  };

  const toggleFullscreen = () => {
    const el = rootRef.current;
    if (!el) return;
    if (typeof window !== "undefined" && window.document.fullscreenElement) {
      window.document.exitFullscreen?.();
    } else {
      el.requestFullscreen?.();
    }
  };

  return (
    <div ref={rootRef} className="flex flex-col gap-5 bg-paper">
      {/* 다크 배너 헤더 */}
      <div className="flex items-center gap-3 rounded-2xl bg-ink px-6 py-5 text-white">
        <span className="flex h-11 w-11 flex-none items-center justify-center rounded-xl bg-white/15 text-xl">
          📄
        </span>
        <div>
          <h1 className="text-xl font-black">계약서 내용 뷰어</h1>
          <p className="text-[13px] text-white/70">원문 보기 및 조항별 분석 결과 확인</p>
        </div>
      </div>

      {/* 문서 정보 + 액션 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-lg font-black text-ink">{doc.title}</span>
          <span className="rounded-md bg-gray200 px-2 py-1 text-xs font-medium text-gray700">
            {doc.parties}
          </span>
          <span className="rounded-md bg-amber100 px-2 py-1 text-xs font-bold text-amber800">
            {doc.pageCount}페이지
          </span>
        </div>
        <div className="flex items-center gap-2">
          <a
            href={doc.pdfUrl}
            download
            className="inline-flex items-center gap-1 rounded-lg border border-gray300 bg-white px-3 py-2 text-[13px] font-bold text-ink hover:bg-paper"
          >
            ↓ 다운로드
          </a>
          <button
            onClick={() => window.print()}
            className="inline-flex items-center gap-1 rounded-lg border border-gray300 bg-white px-3 py-2 text-[13px] font-bold text-ink hover:bg-paper"
          >
            🖨 인쇄
          </button>
          <button
            onClick={toggleFullscreen}
            className="inline-flex items-center gap-1 rounded-lg bg-ink px-3 py-2 text-[13px] font-bold text-white hover:bg-ink/90"
          >
            ⛶ 전체화면
          </button>
        </div>
      </div>

      {/* 좌: 원문 / 우: 분석 */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* ── 좌: 계약서 원문 ── */}
        <section className="flex min-h-0 flex-col rounded-2xl bg-white ring-1 ring-gray200">
          <header className="flex items-center justify-between border-b border-gray200 px-5 py-3">
            <h2 className="text-sm font-black text-ink">계약서 원문</h2>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setFontScale((s) => Math.max(0.85, +(s - 0.1).toFixed(2)))}
                className="flex h-7 w-7 items-center justify-center rounded-md border border-gray300 text-gray500 hover:bg-paper"
                aria-label="글자 작게"
              >
                −
              </button>
              <button
                onClick={() => setFontScale((s) => Math.min(1.4, +(s + 0.1).toFixed(2)))}
                className="flex h-7 w-7 items-center justify-center rounded-md border border-gray300 text-gray500 hover:bg-paper"
                aria-label="글자 크게"
              >
                +
              </button>
            </div>
          </header>

          <div
            ref={origRef}
            className="max-h-[70vh] overflow-y-auto px-5 py-5"
            style={{ fontSize: `${fontScale}rem` }}
          >
            <div className="mb-5 text-center">
              <div className="text-lg font-black text-ink">{doc.title}</div>
              <div className="mt-1 text-[0.72em] text-gray500">{doc.parties}</div>
            </div>

            <div className="flex flex-col gap-4">
              {doc.clauses.map((cl) => (
                <ClauseOriginal
                  key={cl.id}
                  clause={cl}
                  active={selected === cl.id}
                />
              ))}
            </div>
          </div>
        </section>

        {/* ── 우: 분석 결과 ── */}
        <section className="flex flex-col gap-4">
          {/* 내가 이해한 조건 요약 (설문 반영) */}
          <LayerBlock layer="understood" label="내가 이해한 조건 요약">
            {summary.allUnknown ? (
              "잘 모르겠다고 응답하셨어요"
            ) : summary.items.length === 0 ? (
              "아직 입력한 조건이 없어요"
            ) : (
              <div className="flex flex-col gap-1">
                {summary.items.map((it) => (
                  <div key={it.key}>
                    <span className="text-gray500">{it.label}</span>{" "}
                    <span className="font-bold">{it.value}</span>
                  </div>
                ))}
              </div>
            )}
          </LayerBlock>

          {/* 통계 타일 2×2 */}
          <div className="grid grid-cols-2 gap-3">
            <StatCard label="총 조항 수" value={doc.clauses.length} bg="#eef1fb" fg="#3b4aa0" />
            <StatCard label="고위험 조항" value={counts.high} bg={RISK.high.tileBg} fg={RISK.high.tileFg} />
            <StatCard label="중위험 조항" value={counts.mid} bg={RISK.mid.tileBg} fg={RISK.mid.tileFg} />
            <StatCard label="저위험 조항" value={counts.low} bg={RISK.low.tileBg} fg={RISK.low.tileFg} />
          </div>

          {/* 조항별 바로가기 */}
          <div className="rounded-2xl bg-white ring-1 ring-gray200">
            <div className="border-b border-gray200 px-5 py-3 text-sm font-black text-ink">
              조항별 바로가기
            </div>
            <div className="max-h-[46vh] overflow-y-auto p-2">
              {doc.clauses.map((cl) => (
                <button
                  key={cl.id}
                  onClick={() => goToClause(cl.id)}
                  className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left transition ${
                    selected === cl.id ? "bg-amber50" : "hover:bg-paper"
                  }`}
                >
                  <span className="min-w-0 truncate text-sm text-ink">
                    <b className="font-bold">{cl.no}</b> ({cl.title})
                  </span>
                  <RiskBadge risk={cl.risk} />
                </button>
              ))}
            </div>
          </div>

          <p className="text-[11px] leading-relaxed text-gray500">
            위험도는 소상공인 입장에서 &lsquo;확인이 필요한 정도&rsquo;를 표시한 것으로, 위법성이나
            계약의 효력을 판정하지 않아요. 확인이 필요한 조항은{" "}
            <button
              onClick={() => onOpenClause(data.clauses[0]?.id ?? "")}
              className="font-bold text-amber700 underline underline-offset-2"
            >
              조정 요청서
            </button>
            에서 문구를 함께 만들 수 있어요.
          </p>
        </section>
      </div>
    </div>
  );
}

function ClauseOriginal({ clause, active }: { clause: DocClause; active: boolean }) {
  return (
    <div
      id={`clause-${clause.id}`}
      className={`scroll-mt-4 rounded-xl border px-4 py-3.5 transition ${
        active ? "border-amber400 bg-amber50" : "border-gray200 bg-white"
      }`}
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h3 className="text-[0.95em] font-black text-ink">
          {clause.no} ({clause.title})
        </h3>
        <RiskBadge risk={clause.risk} />
      </div>
      <p className="whitespace-pre-line text-[0.85em] leading-relaxed text-gray700">
        {clause.body}
      </p>
      {clause.note && (
        <p
          className="mt-2.5 rounded-lg px-3 py-2 text-[0.8em] leading-relaxed"
          style={{ backgroundColor: "#fdf7e8", color: "#8a6a1f" }}
        >
          💡 {clause.note}
        </p>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  bg,
  fg,
}: {
  label: string;
  value: number;
  bg: string;
  fg: string;
}) {
  return (
    <div className="rounded-2xl px-4 py-3.5" style={{ backgroundColor: bg }}>
      <div className="text-[12px] font-bold" style={{ color: fg }}>
        {label}
      </div>
      <div className="mt-1 text-3xl font-black" style={{ color: fg }}>
        {value}
      </div>
    </div>
  );
}
