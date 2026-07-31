"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { AppScreen } from "@/components/AppScreen";
import { ConfirmModal } from "@/components/ConfirmModal";
import { LayerBlock } from "@/components/LayerBlock";
import { useAsync } from "@/lib/hooks";
import { adapter, isUsingMock, type ClauseExplanation } from "@/lib/adapter";
import { SIGNAL_META } from "@/lib/status";
import {
  loadUnderstood,
  summarizeUnderstood,
  type UnderstoodKey,
} from "@/lib/understood";
import {
  loadRequestDraft,
  saveRequestDraft,
  type ClauseDraft,
  type RequestDraft,
} from "@/lib/requestDraft";
import { politen } from "@/lib/tone";
import type {
  ClauseCard as ClauseData,
  ClauseRisk,
  ContractDetail,
  DocClause,
  SuggestionChoice,
  UnderstoodTerm,
} from "@/lib/types";

/* ④ 계약서 원문(좌) ↔ 분석·조정요청 작성(우) 뷰어 — 참고 이미지 레이아웃 기준(A안).
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

/** hex 색 두 개를 t(0~1)만큼 선형 보간 — 하단 트레이의 빨강 진하기(미확인 수 비례) 계산용 */
function lerpColor(from: string, to: string, t: number): string {
  const clamp = Math.min(1, Math.max(0, t));
  const a = parseInt(from.slice(1), 16);
  const b = parseInt(to.slice(1), 16);
  const mix = (shift: number) => {
    const x = (a >> shift) & 255;
    const y = (b >> shift) & 255;
    return Math.round(x + (y - x) * clamp)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${mix(16)}${mix(8)}${mix(0)}`;
}

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

/** 확인 필요 조항을 "확인"할 때 채우는 기본 초안 — 목업의 userChoice + 해당 문구 */
function defaultAutoDraft(c: ClauseData): ClauseDraft {
  const choice = c.userChoice ?? "REQUEST";
  const sug = c.suggestions.find((s) => s.choice === choice) ?? c.suggestions[0];
  return { choice, text: sug.text, origin: "auto" };
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
  const state = useAsync(() => adapter.getContract(id), [id]);

  return (
    <AppScreen size="wide" backHref="/dashboard">
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}
      {state.status === "ready" && (isUsingMock ? <ViewerBody data={state.data} contractId={id} /> : <LiveViewer contractId={id} />)}
    </AppScreen>
  );
}

function LiveViewer({ contractId }: { contractId: string }) {
  const state = useAsync(() => adapter.getLiveContractReview(contractId), [contractId]);
  const [choices, setChoices] = useState<Record<string, SuggestionChoice>>({});
  const [savingId, setSavingId] = useState<string | null>(null);

  if (state.status === "loading") return <p className="py-10 text-center text-sm text-gray500">분석 결과를 불러오는 중…</p>;
  if (state.status === "error") return <p className="py-10 text-center text-sm text-amber800">⚠ {state.error}</p>;
  const data = { ...state.data, items: state.data.items.map((item) => ({ ...item, userChoice: choices[item.id] ?? item.userChoice })) };

  const select = async (itemId: string, choice: SuggestionChoice) => {
    setSavingId(itemId);
    try {
      await adapter.selectReviewItem(contractId, itemId, choice);
      setChoices((current) => ({ ...current, [itemId]: choice }));
    } finally {
      setSavingId(null);
    }
  };

  return <div className="mx-auto flex max-w-3xl flex-col gap-5">
    <header className="rounded-2xl bg-ink px-6 py-5 text-white"><h1 className="text-xl font-black">{data.title}</h1><p className="mt-1 text-sm text-white/70">{data.counterpartyName} · 원문 근거와 함께 확인해요</p></header>
    {data.understood && <LayerBlock layer="understood" label="내가 이해한 조건"><div className="grid gap-1 text-sm"><span>기간 · {data.understood.durationText}</span><span>월 금액 · {data.understood.monthlyAmount?.toLocaleString() ?? "기억 안 남"}원</span><span>총액 · {data.understood.totalAmount?.toLocaleString() ?? "기억 안 남"}원</span></div></LayerBlock>}
    {data.items.length === 0 ? <p className="rounded-xl bg-white p-6 text-center text-sm text-gray500">현재 표시할 확인 항목이 없어요.</p> : data.items.map((item) => <article key={item.id} className="rounded-2xl bg-white p-5 ring-1 ring-gray200"><div className="mb-3 flex items-center justify-between"><b className="text-sm text-ink">{SIGNAL_META[item.type]}</b>{item.sourceConfidence != null && <span className="text-xs text-gray500">근거 확신도 {Math.round(item.sourceConfidence * 100)}%</span>}</div><LayerBlock layer="original" label={item.sourcePage ? `계약서 원문 · ${item.sourcePage}쪽` : "원문 근거를 찾지 못함"}>{item.sourceText ?? "원문 근거가 없어 확인이 필요합니다."}</LayerBlock><div className="mt-3"><LayerBlock layer="ai" label="AI가 본 차이 · 추정">{item.plainExplanation}</LayerBlock></div><div className="mt-3"><LayerBlock layer="official" label="확인 기준">{item.basisText}</LayerBlock></div><div className="mt-3 grid gap-2">{([['ACCEPT','원안 수용',item.suggestionAccept],['COMPROMISE','절충안',item.suggestionCompromise],['REQUEST','요청안',item.suggestionRequest]] as const).map(([choice,label,text]) => <button key={choice} type="button" disabled={savingId === item.id} onClick={() => void select(item.id, choice)} className={`rounded-lg border p-3 text-left text-sm ${item.userChoice === choice ? 'border-amber700 bg-amber100 font-bold' : 'border-gray300 bg-white'}`}><span className="text-xs text-gray500">{label}</span><br />{text}</button>)}</div></article>)}</div>;
}

function ViewerBody({ data, contractId }: { data: ContractDetail; contractId: string }) {
  const router = useRouter();
  const { document: doc } = data;
  const [selected, setSelected] = useState<string | null>(null);
  const [activeReq, setActiveReq] = useState<string | null>(null);
  const [fontScale, setFontScale] = useState(1);

  // 설문 응답(localStorage) → 요약. 없으면 목업 understood로 폴백.
  const [answers, setAnswers] = useState<Partial<Record<UnderstoodKey, string>> | null>(null);
  useEffect(() => {
    // localStorage는 클라이언트 전용이라 마운트 후 1회 읽는다(설문 없으면 목업 폴백)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAnswers(loadUnderstood(contractId) ?? termToAnswers(data.understood));
  }, [contractId, data.understood]);
  const summary = useMemo(() => summarizeUnderstood(answers), [answers]);

  // 조정 요청 초안 — 확인 필요 조항은 "!"로 확인하기 전엔 비어있다. 저장된 초안이 있으면 복원.
  const [drafts, setDrafts] = useState<RequestDraft>({});
  useEffect(() => {
    const saved = loadRequestDraft(contractId);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved) setDrafts((prev) => ({ ...prev, ...saved }));
  }, [contractId]);

  const counts = useMemo(() => {
    const c = { high: 0, mid: 0, low: 0 };
    doc.clauses.forEach((cl) => (c[cl.risk] += 1));
    return c;
  }, [doc.clauses]);

  // 원문 조항 id → 대응하는 신호 조항 카드들 (한 원문 조항에 확인 필요 카드가 여러 개일 수 있음)
  const signalsByDoc = useMemo(() => {
    const m: Record<string, ClauseData[]> = {};
    data.clauses.forEach((c) => {
      if (!c.docClauseId) return;
      (m[c.docClauseId] ??= []).push(c);
    });
    return m;
  }, [data.clauses]);

  const requestCount = useMemo(
    () =>
      Object.values(drafts).filter((d) =>
        d.origin === "manual" ? d.text.trim() !== "" : d.choice !== "ACCEPT",
      ).length,
    [drafts],
  );

  // 아직 "!"로 확인하지 않은 확인 필요 조항 수 — 하단 바 색(빨강 진하기)을 결정
  const pendingConfirm = useMemo(
    () => data.clauses.filter((c) => !drafts[c.id]).length,
    [data.clauses, drafts],
  );

  // 하단 바 색 — 미확인 조항이 남아있으면 그 비율만큼 진한 빨강(다 확인할수록 옅어짐), 다 확인하면 초록
  const barColor = useMemo(() => {
    if (pendingConfirm === 0) return RISK.low.tileFg;
    const ratio = pendingConfirm / Math.max(data.clauses.length, 1);
    return lerpColor("#f87171", RISK.high.badgeFg, ratio);
  }, [pendingConfirm, data.clauses.length]);

  const [confirmSendWithPending, setConfirmSendWithPending] = useState(false);

  const confirmAutoClause = (c: ClauseData) =>
    setDrafts((prev) => ({ ...prev, [c.id]: defaultAutoDraft(c) }));
  const addManualClause = (dc: DocClause) => {
    setDrafts((prev) => ({
      ...prev,
      [dc.id]: { choice: "REQUEST", text: "", origin: "manual", title: dc.title, docClauseId: dc.id },
    }));
  };
  // 확인 필요(auto) 조항이든 직접 추가(manual) 조항이든 초안에서 완전히 제거
  const removeDraft = (clauseId: string) =>
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[clauseId];
      return next;
    });

  // 좌측 원문의 해당 조항으로 스크롤
  const goToClause = (cid: string) => {
    setSelected(cid);
    window.document.getElementById(`clause-${cid}`)?.scrollIntoView({ block: "center" });
  };

  // 우측 조정요청 카드로 스크롤 — 방금 확인/추가한 카드는 다음 렌더에서야 DOM에
  // 나타나므로, 같은 이벤트 핸들러의 setState가 커밋된 뒤(rAF)로 미뤄서 스크롤한다.
  const scrollToRequestCard = (clauseId: string) => {
    setActiveReq(clauseId);
    requestAnimationFrame(() => {
      window.document.getElementById(`req-${clauseId}`)?.scrollIntoView({ block: "center" });
    });
  };

  // 원문 조항 클릭 — 확인 필요(미확인) 카드가 있으면 전부 "!" 확인 처리, 일반 조항이면
  // 요청서에 담겨 있지 않을 때만 담고, 어느 경우든 해당 요청 카드로 스크롤
  const handleClauseAction = (cl: DocClause) => {
    const related = signalsByDoc[cl.id];
    if (related && related.length > 0) {
      related.forEach((c) => { if (!drafts[c.id]) confirmAutoClause(c); });
      scrollToRequestCard(related[0].id);
      return;
    }
    if (drafts[cl.id]?.origin !== "manual") addManualClause(cl);
    scrollToRequestCard(cl.id);
  };

  const setChoice = (clauseId: string, choice: SuggestionChoice) => {
    const clause = data.clauses.find((c) => c.id === clauseId)!;
    const sug = clause.suggestions.find((s) => s.choice === choice)!;
    setDrafts((prev) => ({ ...prev, [clauseId]: { ...prev[clauseId], choice, text: sug.text } }));
  };
  const setText = (clauseId: string, text: string) =>
    setDrafts((prev) => ({ ...prev, [clauseId]: { ...prev[clauseId], text } }));

  const createRequest = () => {
    saveRequestDraft(contractId, drafts);
    router.push(`/contracts/${contractId}/request`);
  };
  // 확인 필요 조항이 남아있으면 한 번 더 확인받고, 없으면 바로 진행
  const handleSendClick = () => {
    if (pendingConfirm > 0) setConfirmSendWithPending(true);
    else createRequest();
  };

  return (
    <div className="flex flex-col gap-5 bg-paper">
      {/* 다크 배너 헤더 */}
      <div className="flex items-center gap-3 rounded-2xl bg-ink px-6 py-5 text-white">
        <span className="flex h-11 w-11 flex-none items-center justify-center rounded-xl bg-white/15 text-xl">
          📄
        </span>
        <div>
          <h1 className="text-xl font-black">계약서 내용 뷰어</h1>
          <p className="text-[13px] text-white/70">
            원문을 읽으며 조항별 분석 확인 · 조정 요청 작성
          </p>
        </div>
      </div>

      {/* 내가 이해한 조건 요약 + 통계 — 원문/조정요청 비교 위, 전체 폭 가로 배치 */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
        <div className="lg:w-72 lg:flex-none">
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
        </div>
        <div className="grid flex-1 grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="총 조항 수" value={doc.clauses.length} bg="#eef1fb" fg="#3b4aa0" />
          <StatCard label="고위험 조항" value={counts.high} bg={RISK.high.tileBg} fg={RISK.high.tileFg} />
          <StatCard label="중위험 조항" value={counts.mid} bg={RISK.mid.tileBg} fg={RISK.mid.tileFg} />
          <StatCard label="저위험 조항" value={counts.low} bg={RISK.low.tileBg} fg={RISK.low.tileFg} />
        </div>
      </div>

      {/* 문서 정보 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-lg font-black text-ink">{doc.title}</span>
        <span className="rounded-md bg-gray200 px-2 py-1 text-xs font-medium text-gray700">
          {doc.parties}
        </span>
      </div>

      {/* 좌: 원문 / 우: 분석·작성 */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* ── 좌: 계약서 원문 ── */}
        <section className="flex flex-col rounded-2xl bg-white ring-1 ring-gray200">
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

          <div className="px-5 py-5" style={{ fontSize: `${fontScale}rem` }}>
            <div className="mb-5 text-center">
              <div className="text-lg font-black text-ink">{doc.title}</div>
              <div className="mt-1 text-[0.72em] text-gray500">{doc.parties}</div>
            </div>

            <div className="flex flex-col gap-4">
              {doc.clauses.map((cl) => {
                const related = signalsByDoc[cl.id];
                const status: "unconfirmed" | "confirmed" | "none" =
                  !related || related.length === 0
                    ? "none"
                    : related.every((c) => drafts[c.id])
                      ? "confirmed"
                      : "unconfirmed";
                return (
                  <ClauseOriginal
                    key={cl.id}
                    clause={cl}
                    active={selected === cl.id}
                    status={status}
                    onAction={() => handleClauseAction(cl)}
                    contractId={contractId}
                  />
                );
              })}
            </div>
          </div>
        </section>

        {/* ── 우: 분석 결과 + 조정요청 작성 ── */}
        <section className="flex flex-col gap-4">
          {/* 조정 요청 작성 — 확인이 필요한 조항별 문구 선택·수정 */}
          <div className="rounded-2xl bg-white ring-1 ring-gray200">
            <div className="border-b border-gray200 px-5 py-3">
              <h2 className="text-sm font-black text-ink">조정 요청 작성</h2>
            </div>
            <div className="flex flex-col gap-3 p-3">
              {Object.keys(drafts).length === 0 && (
                <div
                  className="mx-1 my-3 rounded-xl border-2 border-dashed px-5 py-8 text-center"
                  style={{ borderColor: RISK.high.badgeFg, backgroundColor: RISK.high.tileBg }}
                >
                  <div className="text-3xl">👈</div>
                  <p className="mt-2 text-[15px] font-black" style={{ color: RISK.high.badgeFg }}>
                    왼쪽 원문에서 조항을 확인해주세요
                  </p>
                  <p className="mt-2 text-[12px] leading-relaxed text-gray700">
                    조항 제목 옆의{" "}
                    <span
                      className="mx-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full border align-middle text-[10px] font-black"
                      style={{
                        backgroundColor: RISK.high.tileBg,
                        color: RISK.high.badgeFg,
                        borderColor: RISK.high.badgeFg,
                      }}
                    >
                      !
                    </span>{" "}
                    버튼을 <b>눌러야</b> 확인돼요. 확인한 조항이 이곳에 요청서 카드로 나타나요.
                  </p>
                </div>
              )}

              {data.clauses
                .filter((c) => drafts[c.id])
                .map((c) => (
                  <RequestCard
                    key={c.id}
                    clause={c}
                    choice={drafts[c.id].choice}
                    text={drafts[c.id].text}
                    active={activeReq === c.id}
                    onChoice={(ch) => setChoice(c.id, ch)}
                    onText={(t) => setText(c.id, t)}
                    onViewOriginal={c.docClauseId ? () => goToClause(c.docClauseId!) : undefined}
                    onDelete={() => removeDraft(c.id)}
                  />
                ))}

              {Object.entries(drafts)
                .filter(([, d]) => d.origin === "manual")
                .map(([cid, d]) => (
                  <ManualRequestCard
                    key={cid}
                    draftId={cid}
                    draft={d}
                    sourceBody={doc.clauses.find((dc) => dc.id === d.docClauseId)?.body ?? ""}
                    onText={(t) => setText(cid, t)}
                    onRemove={() => removeDraft(cid)}
                    onViewOriginal={d.docClauseId ? () => goToClause(d.docClauseId!) : undefined}
                  />
                ))}
            </div>
          </div>

          <p className="text-[11px] leading-relaxed text-gray500">
            위험도는 소상공인 입장에서 &lsquo;확인이 필요한 정도&rsquo;를 표시한 것으로, 위법성이나
            계약의 효력을 판정하지 않아요. 원안 수용을 고른 조항은 요청서에서 제외돼요.
          </p>
        </section>
      </div>

      {/* 하단 트레이 — 미확인 조항 수에 비례해 빨강이 옅어지고, 다 확인하면 초록.
          담긴 요청이 하나라도 있으면 버튼은 항상 눌러짐(미확인 남아있으면 한 번 더 확인). */}
      <div className="sticky bottom-3 z-20">
        <div
          className="flex items-center justify-between gap-3 rounded-2xl px-5 py-3.5 text-white shadow-lg transition-colors"
          style={{ backgroundColor: barColor }}
        >
          <div className="text-[13px]">
            {pendingConfirm > 0 ? (
              <>
                <b className="text-base font-black">{pendingConfirm}</b>건의 확인 필요 조항이 있어요
              </>
            ) : (
              <>
                <b className="text-base font-black">{requestCount}</b>건의 조정 요청이 담겼어요
                {requestCount === 0 && (
                  <span className="ml-1 text-white/70">· 절충안·요청안을 고르면 담겨요</span>
                )}
              </>
            )}
          </div>
          <button
            onClick={handleSendClick}
            disabled={requestCount === 0}
            className="flex-none rounded-lg bg-white px-4 py-2 text-[13px] font-bold transition hover:bg-white/90 disabled:opacity-40"
            style={{ color: barColor }}
          >
            요청서 만들기 →
          </button>
        </div>
      </div>

      <ConfirmModal
        open={confirmSendWithPending}
        eyebrow="발송 전 확인"
        title="확인 필요 조항이 아직 남아있어요"
        body={
          <>
            아직 확인하지 않은 조항이 <b>{pendingConfirm}</b>건 있어요. 이 상태로 요청서를 만들까요?
          </>
        }
        confirmLabel="그래도 만들게요"
        cancelLabel="더 확인할게요"
        onCancel={() => setConfirmSendWithPending(false)}
        onConfirm={() => {
          setConfirmSendWithPending(false);
          createRequest();
        }}
      />
    </div>
  );
}

/** 상태별 트리거 버튼 색 — 축소된 버튼에서도 미확인(빨강)/확인됨(초록)이 한눈에 보이게 유지 */
const CLAUSE_MENU_STYLE: Record<
  "unconfirmed" | "confirmed" | "none",
  { bg: string; fg: string; icon: string; label: string; actionLabel: string }
> = {
  unconfirmed: {
    bg: RISK.high.tileBg,
    fg: RISK.high.badgeFg,
    icon: "!",
    label: "확인 필요",
    actionLabel: "! 확인하고 요청서에 담기",
  },
  confirmed: {
    bg: RISK.low.tileBg,
    fg: RISK.low.tileFg,
    icon: "✓",
    label: "확인 완료",
    actionLabel: "✓ 요청서에서 보기",
  },
  none: {
    bg: "#fdf3e0",
    fg: "#a9752a",
    icon: "⋯",
    label: "일반 조항",
    actionLabel: "✎ 조정 요청 작성",
  },
};

function ClauseOriginal({
  clause,
  active,
  status,
  onAction,
  contractId,
}: {
  clause: DocClause;
  active: boolean;
  status: "unconfirmed" | "confirmed" | "none";
  onAction: () => void;
  contractId: string;
}) {
  // "단디 설명"은 버튼을 눌러야만 불러온다. 한 번 불러오면 재요청하지 않고 캐싱.
  const [detail, setDetail] = useState<ClauseExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const handleExplain = async () => {
    if (detail || loading) return;
    setLoading(true);
    try {
      setDetail(await adapter.explainClause(contractId, clause.id));
    } finally {
      setLoading(false);
    }
  };

  const menu = CLAUSE_MENU_STYLE[status];

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
        <div className="relative flex flex-none items-center gap-1.5">
          <RiskBadge risk={clause.risk} />
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="조항 메뉴 열기"
            className="flex h-6 w-6 flex-none items-center justify-center rounded-full border text-[12px] font-black shadow-sm transition hover:opacity-75 hover:shadow active:scale-95"
            style={{ backgroundColor: menu.bg, color: menu.fg, borderColor: menu.fg }}
          >
            {menu.icon}
          </button>

          {menuOpen && (
            <>
              {/* z-40: 사이트 헤더(z-30)보다 위에 있어야 헤더 위 클릭도 바깥클릭으로 닫힘 */}
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div
                className="absolute right-0 bottom-full z-50 mb-1.5 w-72 overflow-hidden rounded-xl border border-gray200 bg-white text-left shadow-lg"
                onClick={(e) => e.stopPropagation()}
              >
                {/* 헤더 — 상태 라벨 + 닫기 */}
                <div
                  className="flex items-center justify-between gap-2 px-3 py-2"
                  style={{ backgroundColor: menu.bg }}
                >
                  <span className="text-[11px] font-bold" style={{ color: menu.fg }}>
                    {menu.icon} {menu.label}
                  </span>
                  <button
                    type="button"
                    onClick={() => setMenuOpen(false)}
                    aria-label="닫기"
                    className="flex h-5 w-5 flex-none items-center justify-center rounded-full text-[12px] transition hover:bg-black/10"
                    style={{ color: menu.fg }}
                  >
                    ✕
                  </button>
                </div>

                <div className="flex flex-col gap-2.5 p-3">
                  {!detail ? (
                    <button
                      type="button"
                      onClick={handleExplain}
                      disabled={loading}
                      className="flex w-full items-center gap-1.5 rounded-lg border border-amber300 bg-amber50 px-2.5 py-2 text-[12px] font-bold text-amber800 transition hover:bg-amber100 disabled:opacity-70"
                    >
                      {loading ? (
                        <span className="animate-pulse">🤖 단디가 조항을 분석하고 있어요…</span>
                      ) : (
                        "🤖 단디 설명 더 보기"
                      )}
                    </button>
                  ) : (
                    <div className="rounded-lg bg-amber50 px-2.5 py-2 text-[12px] leading-relaxed text-amber800">
                      <p>{detail.summary}</p>
                      {detail.officialBasis && (
                        <p className="mt-1.5 text-[0.9em] text-amber700">근거 · {detail.officialBasis}</p>
                      )}
                      {detail.confidence != null && (
                        <p className="mt-1 text-[0.85em] text-amber700/80">
                          확신도 {Math.round(detail.confidence * 100)}%
                        </p>
                      )}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() => {
                      onAction();
                      setMenuOpen(false);
                    }}
                    className="w-full rounded-lg px-2.5 py-2 text-[12px] font-bold text-white transition hover:brightness-95"
                    style={{ backgroundColor: menu.fg }}
                  >
                    {menu.actionLabel}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
      <p className="whitespace-pre-line text-[0.85em] leading-relaxed text-gray700">
        {clause.body}
      </p>
    </div>
  );
}

const CHOICE_HINT: Record<SuggestionChoice, string> = {
  ACCEPT: "요청서에서 제외돼요",
  COMPROMISE: "요청서에 담겨요 · 빼려면 원안 수용을 선택하세요",
  REQUEST: "요청서에 담겨요 · 빼려면 원안 수용을 선택하세요",
};

function RequestCard({
  clause,
  choice,
  text,
  active,
  onChoice,
  onText,
  onViewOriginal,
  onDelete,
}: {
  clause: ClauseData;
  choice: SuggestionChoice;
  text: string;
  active: boolean;
  onChoice: (choice: SuggestionChoice) => void;
  onText: (text: string) => void;
  onViewOriginal?: () => void;
  onDelete: () => void;
}) {
  // 톤 완충: 다듬은 변환문 미리보기(적용 전). null이면 미표시.
  const [polished, setPolished] = useState<string | null>(null);
  const changeText = (v: string) => {
    onText(v);
    setPolished(null); // 편집하면 이전 변환 미리보기는 무효화
  };
  // 확인 필요 조항 삭제 — 되돌아가면 원문에서 다시 확인해야 하므로 한 번 더 확인받는다
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div
      id={`req-${clause.id}`}
      className={`scroll-mt-4 rounded-xl border px-4 py-3.5 transition ${
        active ? "border-amber700 bg-amber50" : "border-gray200 bg-white"
      }`}
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-sm font-black text-ink">{clause.title}</h3>
        <div className="flex flex-none items-center gap-2">
          <span className="rounded-full bg-amber100 px-2 py-0.5 text-[11px] font-bold text-amber700">
            {SIGNAL_META[clause.signal]}
          </span>
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="text-[11px] font-bold text-gray500 hover:text-amber700"
          >
            ✕ 삭제
          </button>
        </div>
      </div>

      <p className="mb-2.5 text-[12px] leading-relaxed text-gray700">{clause.aiExplanation}</p>

      {onViewOriginal && (
        <button
          onClick={onViewOriginal}
          className="mb-2.5 text-[11px] font-bold text-amber700 underline underline-offset-2"
        >
          ↖ 원문에서 보기
        </button>
      )}

      {/* 문구 3종 선택 */}
      <div className="flex flex-col gap-1.5">
        {clause.suggestions.map((s) => {
          const sel = choice === s.choice;
          return (
            <button
              key={s.choice}
              type="button"
              onClick={() => onChoice(s.choice)}
              className={`rounded-lg border px-3 py-2 text-left text-[12px] transition ${
                sel
                  ? "border-2 border-amber700 bg-amber50 font-bold"
                  : "border-gray300 bg-white hover:border-amber400"
              }`}
            >
              <span className="text-gray500">{s.label}</span> — {s.text}
              {sel && <span className="ml-1 text-amber700">✓</span>}
            </button>
          );
        })}
      </div>

      {/* 직접 수정 (원안 수용이 아닐 때만) */}
      {choice === "ACCEPT" ? (
        <p className="mt-2.5 text-[11px] text-gray500">원안을 그대로 수용해요 · 요청서에서 제외</p>
      ) : (
        <div className="mt-2.5">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[10px] font-bold text-gray700">보낼 문구 (직접 수정 가능)</span>
            <span className="text-[10px] font-bold text-amber700">{CHOICE_HINT[choice]}</span>
          </div>
          <textarea
            value={text}
            onChange={(e) => changeText(e.target.value)}
            rows={2}
            placeholder="내 말로 막 써도 돼요. 예) 5년은 너무 길어요 ㅠㅠ"
            className="w-full resize-y rounded-lg border border-gray300 px-3 py-2 text-[12px] leading-relaxed text-ink outline-none focus:border-ink placeholder:text-gray400"
          />

          {/* 톤 완충 — 지금 문구를 정중하게 다듬기 */}
          <button
            type="button"
            onClick={() => setPolished(politen(text))}
            disabled={!text.trim()}
            className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-amber400 bg-amber50 px-2.5 py-1 text-[11px] font-bold text-amber700 transition hover:bg-amber100 disabled:opacity-40"
          >
            ✨ 정중하게 다듬기
          </button>

          {polished !== null && (
            <div className="mt-2 rounded-lg border border-amber600 bg-amber50 px-3 py-2.5">
              <div className="mb-1 text-[10px] font-bold text-amber800">
                이렇게 바꿔봤어요
              </div>
              <p className="text-[12px] leading-relaxed text-ink">“{polished}”</p>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    onText(polished);
                    setPolished(null);
                  }}
                  className="flex-1 rounded-md bg-ink px-3 py-1.5 text-[11px] font-bold text-white"
                >
                  이 문구로 적용
                </button>
                <button
                  type="button"
                  onClick={() => setPolished(null)}
                  className="flex-1 rounded-md border border-gray300 bg-white px-3 py-1.5 text-[11px] font-bold text-gray700"
                >
                  취소
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <ConfirmModal
        open={confirmDelete}
        eyebrow="삭제 확인"
        title="확인 필요 조항을 삭제할까요?"
        body="AI가 확인이 필요하다고 표시한 조항이에요. 삭제하면 요청서에서 빠지고, 원문에서 다시 확인해야 나타나요."
        confirmLabel="삭제할게요"
        cancelLabel="취소"
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false);
          onDelete();
        }}
      />
    </div>
  );
}

/** 사용자가 직접 담은 조항 카드 — AI 제안 3종이 없어 자유입력 문구만 받는다 */
function ManualRequestCard({
  draftId,
  draft,
  sourceBody,
  onText,
  onRemove,
  onViewOriginal,
}: {
  draftId: string;
  draft: ClauseDraft;
  sourceBody: string;
  onText: (text: string) => void;
  onRemove: () => void;
  onViewOriginal?: () => void;
}) {
  const [polished, setPolished] = useState<string | null>(null);
  const changeText = (v: string) => {
    onText(v);
    setPolished(null);
  };

  return (
    <div
      id={`req-${draftId}`}
      className="scroll-mt-4 rounded-xl border border-gray200 bg-white px-4 py-3.5"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-sm font-black text-ink">{draft.title}</h3>
        <div className="flex flex-none items-center gap-2">
          <span className="rounded-full bg-amber100 px-2 py-0.5 text-[11px] font-bold text-amber700">
            직접 추가
          </span>
          <button
            type="button"
            onClick={onRemove}
            className="text-[11px] font-bold text-gray500 hover:text-amber700"
          >
            ✕ 삭제
          </button>
        </div>
      </div>

      {sourceBody && (
        <p className="mb-2.5 whitespace-pre-line text-[12px] leading-relaxed text-gray700">
          {sourceBody}
        </p>
      )}

      {onViewOriginal && (
        <button
          onClick={onViewOriginal}
          className="mb-2.5 text-[11px] font-bold text-amber700 underline underline-offset-2"
        >
          ↖ 원문에서 보기
        </button>
      )}

      <div className="mt-1">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-[10px] font-bold text-gray700">보낼 문구 (직접 작성)</span>
          <span className="text-[10px] font-bold text-amber700">요청서에 담겨요</span>
        </div>
        <textarea
          value={draft.text}
          onChange={(e) => changeText(e.target.value)}
          rows={2}
          placeholder="추가하고 싶은 요청을 자유롭게 써주세요."
          className="w-full resize-y rounded-lg border border-gray300 px-3 py-2 text-[12px] leading-relaxed text-ink outline-none focus:border-ink placeholder:text-gray400"
        />

        <button
          type="button"
          onClick={() => setPolished(politen(draft.text))}
          disabled={!draft.text.trim()}
          className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-amber400 bg-amber50 px-2.5 py-1 text-[11px] font-bold text-amber700 transition hover:bg-amber100 disabled:opacity-40"
        >
          ✨ 정중하게 다듬기
        </button>

        {polished !== null && (
          <div className="mt-2 rounded-lg border border-amber600 bg-amber50 px-3 py-2.5">
            <div className="mb-1 text-[10px] font-bold text-amber800">이렇게 바꿔봤어요</div>
            <p className="text-[12px] leading-relaxed text-ink">“{polished}”</p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  onText(polished);
                  setPolished(null);
                }}
                className="flex-1 rounded-md bg-ink px-3 py-1.5 text-[11px] font-bold text-white"
              >
                이 문구로 적용
              </button>
              <button
                type="button"
                onClick={() => setPolished(null)}
                className="flex-1 rounded-md border border-gray300 bg-white px-3 py-1.5 text-[11px] font-bold text-gray700"
              >
                취소
              </button>
            </div>
          </div>
        )}
      </div>
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
