"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { AppScreen } from "@/components/AppScreen";
import { ConfirmModal } from "@/components/ConfirmModal";
import { LayerBlock } from "@/components/LayerBlock";
import { useAsync } from "@/lib/hooks";
import { adapter, isUsingMock } from "@/lib/adapter";
import {
  liveReviewToDashboard,
  type ReviewDashboardData,
} from "@/lib/reviewViewModel";
import { SIGNAL_META } from "@/lib/status";
import {
  loadUnderstood,
  summarizeUnderstood,
  UNDERSTOOD_LABELS,
  UNKNOWN_ANSWER,
  type UnderstoodKey,
} from "@/lib/understood";
import {
  loadRequestDraft,
  saveRequestDraft,
  type ClauseDraft,
  type RequestDraft,
} from "@/lib/requestDraft";
import type {
  ClauseCard as ClauseData,
  ClauseRisk,
  DocClause,
  SuggestionChoice,
  UnderstoodTerm,
} from "@/lib/types";

/* ④ 계약서 원문(좌) ↔ 분석·조정요청 작성(우) 뷰어 — 참고 이미지 레이아웃 기준(A안).
   위험도(고/중/저)는 소상공인 관점의 '확인이 필요한 정도'를 표시하며 위법성 판정이 아니다. */

/* 하단 확인 바 색 — 미확인이 많을수록 진하고, 확인해 나갈수록 옅어지고, 다 확인하면 하늘색.
   이 값들은 바 배경(흰 글자)이자 흰 버튼 위 글자색으로 함께 쓰이므로
   구간 전체가 흰색 대비 4.5:1 이상이어야 한다. 아래 셋은 4.75 / 7.75 / 7.16. */
const BAR_LIGHT = "#ca453a"; // 거의 다 확인함
const BAR_STRONG = "#a01f1f"; // 전부 미확인
const BAR_DONE = "#3e89cf"; // 0건 남음

/** hex 색 두 개를 t(0~1)만큼 선형 보간 — 하단 바의 빨강 농도(미확인 비율) 계산용 */
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

/** 위험도 색 — 빨강/노랑/초록 대신 테마의 무게 사다리를 쓴다.
    확인이 급할수록 채움이 진해진다. 위험도 판정에는 빨강을 쓰지 않는다. */
const RISK: Record<ClauseRisk, { label: string; badge: string; tile: string; num: string }> = {
  // 가장 확인이 필요 — 유일한 진한 채움
  high: {
    label: "고위험",
    badge: "bg-brand800 text-white",
    tile: "bg-brand800",
    num: "text-white",
  },
  // 확인 권장 — 옅은 하늘 채움
  mid: {
    label: "중위험",
    badge: "bg-brand100 text-brand800",
    tile: "bg-brand50 ring-1 ring-brand200",
    num: "text-brand800",
  },
  // 조용함 — 중립
  low: {
    label: "추가 신호 없음",
    badge: "bg-neutral100 text-neutral700",
    tile: "bg-white ring-1 ring-neutral200",
    num: "text-neutral700",
  },
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
      className={`inline-flex flex-none items-center rounded-full px-2 py-0.5 text-[11px] font-bold ${r.badge}`}
    >
      {r.label}
    </span>
  );
}

export default function AnalysisViewerPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <AppScreen size="xl" backHref="/dashboard">
      {isUsingMock ? <MockViewer contractId={id} /> : <LiveViewer contractId={id} />}
    </AppScreen>
  );
}

function MockViewer({ contractId }: { contractId: string }) {
  const state = useAsync(() => adapter.getContract(contractId), [contractId]);
  if (state.status === "loading") {
    return <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>;
  }
  if (state.status === "error") {
    return <p className="py-10 text-center text-sm text-brand800">⚠ {state.error}</p>;
  }
  return <ViewerBody data={state.data} contractId={contractId} />;
}

function LiveViewer({ contractId }: { contractId: string }) {
  const state = useAsync(() => adapter.getLiveContractReview(contractId), [contractId]);
  const [selectionError, setSelectionError] = useState<string | null>(null);

  if (state.status === "loading") {
    return <p className="py-10 text-center text-sm text-neutral500">분석 결과를 불러오는 중…</p>;
  }
  if (state.status === "error") {
    return <p className="py-10 text-center text-sm text-brand800">⚠ {state.error}</p>;
  }

  const select = async (itemId: string, choice: SuggestionChoice) => {
    setSelectionError(null);
    try {
      await adapter.selectReviewItem(contractId, itemId, choice);
    } catch (cause) {
      setSelectionError(
        cause instanceof Error ? cause.message : "조정안 선택을 저장하지 못했습니다.",
      );
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {selectionError && (
        <p className="rounded-lg bg-brand50 px-4 py-3 text-xs font-bold text-brand800">
          ⚠ {selectionError}
        </p>
      )}
      <ViewerBody
        data={liveReviewToDashboard(state.data)}
        contractId={contractId}
        onSelectReviewItem={select}
      />
    </div>
  );
}

function ViewerBody({
  data,
  contractId,
  onSelectReviewItem,
}: {
  data: ReviewDashboardData;
  contractId: string;
  onSelectReviewItem?: (
    itemId: string,
    choice: SuggestionChoice,
  ) => void | Promise<void>;
}) {
  const router = useRouter();
  const { document: doc } = data;
  const [selected, setSelected] = useState<string | null>(null);
  const [activeReq, setActiveReq] = useState<string | null>(null);
  const [fontScale, setFontScale] = useState(1);
  const [reqFontScale, setReqFontScale] = useState(1);

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

  // 하단 바 색 — 미확인이 많을수록 진한 빨강, 확인해 나갈수록 옅어지고, 다 확인하면 하늘색.
  const barColor = useMemo(() => {
    if (pendingConfirm === 0) return BAR_DONE;
    const ratio = pendingConfirm / Math.max(data.clauses.length, 1);
    return lerpColor(BAR_LIGHT, BAR_STRONG, ratio);
  }, [pendingConfirm, data.clauses.length]);

  const [confirmSendWithPending, setConfirmSendWithPending] = useState(false);
  const selectionQueue = useRef<Promise<void>>(Promise.resolve());

  const persistReviewSelection = (itemId: string, choice: SuggestionChoice) => {
    if (!onSelectReviewItem) return;
    selectionQueue.current = selectionQueue.current.then(async () => {
      await onSelectReviewItem(itemId, choice);
    });
  };

  const confirmAutoClause = (c: ClauseData) => {
    const draft = defaultAutoDraft(c);
    setDrafts((prev) => ({ ...prev, [c.id]: draft }));
    persistReviewSelection(c.id, draft.choice);
  };
  const addManualClause = (dc: DocClause) => {
    setDrafts((prev) => ({
      ...prev,
      [dc.id]: { choice: "REQUEST", text: "", origin: "manual", title: dc.title, docClauseId: dc.id },
    }));
  };
  // 확인 필요(auto) 조항이든 직접 추가(manual) 조항이든 초안에서 완전히 제거
  const removeDraft = (clauseId: string) => {
    if (data.clauses.some((clause) => clause.id === clauseId)) {
      persistReviewSelection(clauseId, "ACCEPT");
    }
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[clauseId];
      return next;
    });
  };

  // 오른쪽 요청 카드에서 왼쪽 원문 조항으로 이동
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
    persistReviewSelection(clauseId, choice);
  };
  const setText = (clauseId: string, text: string) =>
    setDrafts((prev) => ({ ...prev, [clauseId]: { ...prev[clauseId], text } }));

  const createRequest = async () => {
    saveRequestDraft(contractId, drafts);
    await selectionQueue.current;
    router.push(`/contracts/${contractId}/request`);
  };
  // 확인 필요 조항이 남아있으면 한 번 더 확인받고, 없으면 바로 진행
  const handleSendClick = () => {
    if (pendingConfirm > 0) setConfirmSendWithPending(true);
    else void createRequest();
  };

  return (
    <div className="flex flex-col gap-5">
      {/* 페이지 헤더 — 다른 화면과 같은 흰 바탕 제목 형식 */}
      <div>
        <h1 className="text-2xl font-black tracking-tight text-ink">
          계약서 내용 뷰어
        </h1>
        <p className="mt-1 text-[13px] text-neutral500">
          원문을 읽으며 조항별 분석 확인 · 조정 요청 작성
        </p>
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
                    <span className="text-neutral500">{it.label}</span>{" "}
                    <span className="font-bold">{it.value}</span>
                  </div>
                ))}
              </div>
            )}
          </LayerBlock>
        </div>
        <div className="grid flex-1 grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="총 조항 수"
            value={doc.clauses.length}
            tile="bg-white ring-1 ring-neutral200"
            num="text-ink"
          />
          <StatCard label="고위험 조항" value={counts.high} tile={RISK.high.tile} num={RISK.high.num} />
          <StatCard label="중위험 조항" value={counts.mid} tile={RISK.mid.tile} num={RISK.mid.num} />
          <StatCard label="추가 신호 없음" value={counts.low} tile={RISK.low.tile} num={RISK.low.num} />
        </div>
      </div>

      {/* 문서 정보 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-lg font-black text-ink">{doc.title}</span>
        <span className="rounded-md bg-neutral200 px-2 py-1 text-xs font-medium text-neutral700">
          {doc.parties}
        </span>
        {doc.pdfUrl && (
          <a
            href={doc.pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-brand300 bg-white px-2.5 py-1 text-xs font-bold text-brand800 transition hover:bg-brand50"
          >
            PDF 원본 보기 <span aria-hidden="true">↗</span>
          </a>
        )}
      </div>

      {/* develop 기준: 좌측 전체 원문 조항 → 우측에 선택한 수정 요청 카드 추가 */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* ── 좌: 파싱한 계약서 전체 조항 ── */}
        <section className="flex flex-col rounded-2xl bg-white ring-1 ring-neutral200">
          <header className="flex items-center justify-between border-b border-neutral200 px-5 py-3">
            <h2 className="text-sm font-black text-ink">계약서 원문</h2>
            <FontScaleButtons onChange={setFontScale} label="계약서 원문" />
          </header>

          <div className="px-5 py-5" style={{ fontSize: `${fontScale}rem` }}>
            <div className="mb-5 text-center">
              <div className="text-lg font-black text-ink">{doc.title}</div>
              <div className="mt-1 text-[0.72em] text-neutral500">{doc.parties}</div>
            </div>

            {data.hasCompleteDocumentClauses === false && (
              <div className="mb-4 rounded-xl border border-brand300 bg-brand50 px-4 py-3 text-[0.75em] leading-relaxed text-brand800">
                이 계약은 전체 조항 저장 기능을 넣기 전에 분석된 결과예요. 현재는 AI 근거와
                연결된 조항만 표시되며, 새로 분석한 계약부터 원문의 모든 조항이 표시됩니다.
              </div>
            )}

            <div className="flex flex-col gap-4">
              {doc.clauses.map((cl) => {
                const related = signalsByDoc[cl.id] ?? [];
                const status: "unconfirmed" | "confirmed" | "none" = related.length === 0
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
                    relatedSignals={related}
                    understoodAnswers={answers}
                    onAction={() => handleClauseAction(cl)}
                  />
                );
              })}

              {data.clauses.filter((clause) => !clause.docClauseId).map((clause) => (
                <UnlinkedClauseSourceCard
                  key={clause.id}
                  clause={clause}
                  confirmed={Boolean(drafts[clause.id])}
                  onAction={() => {
                    if (!drafts[clause.id]) confirmAutoClause(clause);
                    scrollToRequestCard(clause.id);
                  }}
                />
              ))}
            </div>
          </div>
        </section>

        {/* ── 우: 선택한 조항의 수정 요청 카드 ── */}
        <section className="flex flex-col gap-4">
          <div className="rounded-2xl bg-white ring-1 ring-neutral200">
            <header className="flex items-center justify-between border-b border-neutral200 px-5 py-3">
              <h2 className="text-sm font-black text-ink">조정 요청 작성</h2>
              <FontScaleButtons onChange={setReqFontScale} label="조정 요청" />
            </header>
            <div
              className="flex flex-col gap-3 p-3"
              style={{ fontSize: `${reqFontScale}rem` }}
            >
              {Object.keys(drafts).length === 0 && (
                <div className="mx-1 my-3 rounded-xl border border-dashed border-brand300 bg-brand50 px-5 py-8 text-center">
                  <div className="text-[1.875em]">👈</div>
                  <p className="mt-2 text-[0.9375em] font-black text-brand800">
                    왼쪽 원문에서 조항을 선택해주세요
                  </p>
                  <p className="mt-2 text-[0.75em] leading-relaxed text-neutral700">
                    조항 오른쪽의 상태 버튼을 눌러 확인하거나 수정 요청에 추가하면 이곳에
                    요청 카드가 나타나요.
                  </p>
                </div>
              )}

              {data.clauses.filter((clause) => drafts[clause.id]).map((clause) => (
                <RequestCard
                  key={clause.id}
                  contractId={contractId}
                  clause={clause}
                  choice={drafts[clause.id].choice}
                  text={drafts[clause.id].text}
                  active={activeReq === clause.id}
                  onChoice={(choice) => setChoice(clause.id, choice)}
                  onText={(text) => setText(clause.id, text)}
                  onViewOriginal={clause.docClauseId
                    ? () => goToClause(clause.docClauseId!)
                    : undefined}
                  onDelete={() => removeDraft(clause.id)}
                />
              ))}

              {Object.entries(drafts)
                .filter(([, draft]) => draft.origin === "manual")
                .map(([clauseId, draft]) => (
                  <ManualRequestCard
                    key={clauseId}
                    contractId={contractId}
                    draftId={clauseId}
                    draft={draft}
                    sourceBody={doc.clauses.find((clause) => clause.id === draft.docClauseId)?.body ?? ""}
                    onText={(text) => setText(clauseId, text)}
                    onRemove={() => removeDraft(clauseId)}
                    onViewOriginal={draft.docClauseId
                      ? () => goToClause(draft.docClauseId!)
                      : undefined}
                  />
                ))}
            </div>
          </div>

          <p className="text-[11px] leading-relaxed text-neutral500">
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
          void createRequest();
        }}
      />
    </div>
  );
}

/** 원문 칸·조정 요청 작성 칸 공용 글자 확대·축소.
    같은 마크업을 공유해야 좌우 헤더 높이와 조작감이 어긋나지 않는다. */
function FontScaleButtons({
  onChange,
  label,
}: {
  onChange: (update: (scale: number) => number) => void;
  /** 스크린리더용 구분 라벨 — 한 화면에 확대/축소 쌍이 둘이라 필요 */
  label: string;
}) {
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => onChange((s) => Math.max(0.85, +(s - 0.1).toFixed(2)))}
        className="flex h-7 w-7 items-center justify-center rounded-md border border-neutral300 text-neutral500 hover:bg-subtle"
        aria-label={`${label} 글자 작게`}
      >
        −
      </button>
      <button
        onClick={() => onChange((s) => Math.min(1.4, +(s + 0.1).toFixed(2)))}
        className="flex h-7 w-7 items-center justify-center rounded-md border border-neutral300 text-neutral500 hover:bg-subtle"
        aria-label={`${label} 글자 크게`}
      >
        +
      </button>
    </div>
  );
}

/** 통합 조항 카드의 검토·작성 상태 색 */
const CLAUSE_MENU_STYLE: Record<
  "unconfirmed" | "confirmed" | "none",
  { bg: string; fg: string; icon: string; label: string; actionLabel: string }
> = {
  unconfirmed: {
    bg: "#fdeceb", // 옅은 빨강 배경
    fg: "#c0392b", // 빨강. 흰 글자 대비 5.44:1 (AA)
    icon: "!",
    label: "확인 필요",
    actionLabel: "! 확인하고 요청서에 담기",
  },
  confirmed: {
    bg: "#e3f0fb",
    fg: "#10365a",
    icon: "✓",
    label: "확인 완료",
    actionLabel: "✓ 요청서에서 보기",
  },
  none: {
    bg: "#f1f3f5",
    fg: "#434b56",
    icon: "⋯",
    label: "일반 조항",
    actionLabel: "✎ 조정 요청 작성",
  },
};

function ClauseOriginal({
  clause,
  active,
  status,
  relatedSignals,
  understoodAnswers,
  onAction,
}: {
  clause: DocClause;
  active: boolean;
  status: "unconfirmed" | "confirmed" | "none";
  relatedSignals: ClauseData[];
  understoodAnswers: Partial<Record<UnderstoodKey, string>> | null;
  onAction: () => void;
}) {
  const [showExplanation, setShowExplanation] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menu = CLAUSE_MENU_STYLE[status];
  const meaning = explainClauseMeaning(clause);

  return (
    <article
      id={`clause-${clause.id}`}
      className={`scroll-mt-4 rounded-xl border px-4 py-3.5 transition ${
        active ? "border-brand400 bg-brand50" : "border-neutral200 bg-white"
      }`}
    >
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <div>
          <h3 className="text-[0.95em] font-black text-ink">
            {clause.no} {clause.title !== "계약 조항" && `(${clause.title})`}
          </h3>
          {clause.sourcePage && (
            <span className="mt-0.5 block text-[0.68em] text-neutral500">
              원본 {clause.sourcePage}쪽부터
            </span>
          )}
        </div>
        <div className="relative flex flex-none items-center gap-1.5">
          <RiskBadge risk={clause.risk} />
          <button
            type="button"
            onClick={() => setMenuOpen((current) => !current)}
            aria-label="조항 메뉴 열기"
            aria-expanded={menuOpen}
            className="flex h-6 w-6 flex-none items-center justify-center rounded-full border text-[12px] font-black shadow-sm transition hover:opacity-75 hover:shadow active:scale-95"
            style={{ backgroundColor: menu.bg, color: menu.fg, borderColor: menu.fg }}
          >
            {menu.icon}
          </button>

          {menuOpen && (
            <>
              <div
                className="fixed inset-0 z-40"
                aria-hidden="true"
                onClick={() => setMenuOpen(false)}
              />
              <div
                className="absolute right-0 bottom-full z-50 mb-1.5 w-[calc(100vw-5rem)] overflow-hidden rounded-xl border border-neutral200 bg-white text-left shadow-lg sm:w-[380px]"
                onClick={(event) => event.stopPropagation()}
              >
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

                <div className="flex max-h-[70vh] flex-col gap-2.5 overflow-y-auto p-3">
                  {!showExplanation ? (
                    <button
                      type="button"
                      onClick={() => setShowExplanation(true)}
                      className="flex w-full items-center gap-1.5 rounded-lg border border-brand300 bg-brand50 px-2.5 py-2 text-[12px] font-bold text-brand800 transition hover:bg-brand100"
                    >
                      🤖 단디 설명 더 보기
                    </button>
                  ) : (
                    <div className="flex flex-col gap-2 text-[12px] leading-relaxed">
                      <section className="rounded-lg bg-brand50 px-2.5 py-2 text-brand800">
                        <p className="font-black">이 조항의 의미</p>
                        <p className="mt-1 text-neutral700">{meaning}</p>
                      </section>

                      {relatedSignals.length > 0 ? (
                        relatedSignals.map((signal) => {
                          const comparison = understoodComparisonFor(signal, understoodAnswers);
                          return (
                            <section
                              key={signal.id}
                              className="rounded-lg border border-brand200 bg-white px-2.5 py-2"
                            >
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="rounded-full bg-brand100 px-2 py-0.5 text-[10px] font-bold text-brand800">
                                  {SIGNAL_META[signal.signal]}
                                </span>
                                <span className="text-[10px] font-bold text-neutral500">
                                  확인 수준 · {RISK[clause.risk].label}
                                </span>
                                {signal.confidence > 0 && (
                                  <span className="text-[10px] text-neutral500">
                                    근거 확신도 {Math.round(signal.confidence * 100)}%
                                  </span>
                                )}
                              </div>

                              <p className="mt-2 font-black text-ink">
                                {comparison
                                  ? "내가 알고 있던 내용과 무엇이 다른가"
                                  : "왜 확인이 필요한가"}
                              </p>

                              {comparison && (
                                <div className="mt-1.5 grid gap-1.5">
                                  <div className="rounded-md bg-neutral100 px-2 py-1.5 text-neutral700">
                                    <b>내가 답한 {comparison.label}</b>
                                    <span className="mt-0.5 block">{comparison.value}</span>
                                  </div>
                                  <div className="rounded-md bg-brand50 px-2 py-1.5 text-neutral700">
                                    <b className="text-brand800">계약서 원문</b>
                                    <span className="mt-0.5 block">{signal.original.text}</span>
                                  </div>
                                </div>
                              )}

                              <p className="mt-1.5 text-neutral700">{signal.aiExplanation}</p>
                              {signal.officialBasis && (
                                <p className="mt-1.5 border-t border-neutral200 pt-1.5 text-[10px] text-neutral500">
                                  확인 기준 · {signal.officialBasis}
                                </p>
                              )}
                            </section>
                          );
                        })
                      ) : (
                        <section className="rounded-lg bg-neutral100 px-2.5 py-2 text-neutral700">
                          <p className="font-black text-ink">추가 확인 신호 없음</p>
                          <p className="mt-1">
                            현재 분석에서는 이 조항에 별도의 위험·차이 신호가 연결되지 않았어요.
                            다만 계약의 적법성이나 유효성을 확정했다는 뜻은 아니에요.
                          </p>
                        </section>
                      )}

                      <button
                        type="button"
                        onClick={() => setShowExplanation(false)}
                        className="mt-1.5 text-[11px] font-bold text-brand700 underline underline-offset-2"
                      >
                        설명 접기
                      </button>
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
      <p className="whitespace-pre-line text-[0.85em] leading-relaxed text-neutral700">
        {clause.body}
      </p>
    </article>
  );
}

type UnderstoodComparison = { label: string; value: string };

/** 5문항 답변 중 해당 조항·확인 신호와 직접 관련된 답만 원문과 나란히 보여준다. */
function understoodComparisonFor(
  signal: ClauseData,
  answers: Partial<Record<UnderstoodKey, string>> | null,
): UnderstoodComparison | null {
  if (signal.understoodKey && answers) {
    const answer = answers[signal.understoodKey];
    if (answer !== undefined) {
      const value = answer.trim();
      if (!value || value === UNKNOWN_ANSWER) return null;
      return { label: UNDERSTOOD_LABELS[signal.understoodKey], value };
    }
  }

  if (signal.understood?.trim()) {
    return { label: "내용", value: signal.understood.trim() };
  }
  return null;
}

/** 검토 결과와 섞지 않고, 원문 조항 자체를 읽는 관점을 쉬운 말로 안내한다. */
function explainClauseMeaning(clause: DocClause): string {
  const text = `${clause.title} ${clause.body}`;
  const explanations: Array<[RegExp, string]> = [
    [
      /자동.{0,3}(갱신|연장)|갱신|연장/,
      "이 조항은 계약 기간이 끝날 때 자동으로 이어지는지와, 연장을 원하지 않을 때 언제까지 알려야 하는지를 정한 내용이에요. 통보 방법과 마감일을 확인하면 돼요.",
    ],
    [
      /계약.{0,4}(기간|유효)|시작일|종료일/,
      "이 조항은 계약이 언제 시작되고 끝나는지, 정해진 기간 뒤에도 효력이 이어지는지를 정한 내용이에요. 시작일·종료일과 기간이 늘어나는 조건을 함께 확인하면 돼요.",
    ],
    [
      /대금|금액|보수|수수료|지급|납부|비용/,
      "이 조항은 누가 얼마를, 언제, 어떤 방식으로 지급하는지를 정한 내용이에요. 금액에 세금이나 추가 비용이 포함되는지와 지급 기한을 함께 확인하면 돼요.",
    ],
    [
      /해지|해제|종료|중도.{0,3}해약/,
      "이 조항은 계약을 중간에 끝낼 수 있는 경우와 그때 거쳐야 할 절차를 정한 내용이에요. 해지 사유, 사전 통보 기간, 이미 낸 돈의 처리를 확인하면 돼요.",
    ],
    [
      /환불|반환|환급/,
      "이 조항은 계약이 취소되거나 끝났을 때 이미 지급한 돈을 돌려받을 수 있는 조건과 범위를 정한 내용이에요. 환불이 가능한 경우, 공제되는 비용, 반환 시점을 확인하면 돼요.",
    ],
    [
      /위약|손해.{0,2}배상|배상|책임/,
      "이 조항은 약속을 지키지 않거나 손해가 생겼을 때 누가 어느 범위까지 책임지는지를 정한 내용이에요. 책임이 생기는 조건과 금액·범위의 제한을 확인하면 돼요.",
    ],
    [
      /업무|서비스|용역|과업|수행|의무/,
      "이 조항은 계약 당사자가 맡은 일과 지켜야 할 의무를 정한 내용이에요. 누가 무엇을 언제까지 해야 하는지, 결과물의 기준과 예외가 무엇인지 확인하면 돼요.",
    ],
    [
      /승인|검수|수정|시안|결과물/,
      "이 조항은 작업 결과를 확인하고 승인하거나 수정을 요청하는 절차를 정한 내용이에요. 답변 기한, 수정 가능한 횟수, 답변하지 않았을 때의 처리를 확인하면 돼요.",
    ],
    [
      /저작권|지식.{0,2}재산|소유권|사용권/,
      "이 조항은 만든 결과물을 누가 소유하고 어디까지 사용할 수 있는지를 정한 내용이에요. 권리가 넘어가는 시점과 사용 가능한 매체·기간·범위를 확인하면 돼요.",
    ],
    [
      /비밀|기밀|개인정보|보안/,
      "이 조항은 계약 과정에서 알게 된 정보나 개인정보를 어떻게 보호하고 사용할지를 정한 내용이에요. 보호 대상, 이용 가능한 목적, 보관·폐기 기간을 확인하면 돼요.",
    ],
    [
      /분쟁|관할|소송|준거/,
      "이 조항은 다툼이 생겼을 때 어떤 절차와 기준으로 해결하고 어느 법원에서 다룰지를 정한 내용이에요. 협의 절차와 관할 법원을 확인하면 돼요.",
    ],
  ];
  const matched = explanations.find(([pattern]) => pattern.test(text));
  if (matched) return matched[1];

  const subject = clause.title && clause.title !== "계약 조항"
    ? `‘${clause.title}’에 관한`
    : "계약 당사자가 따라야 할";
  return `이 조항은 ${subject} 기준과 조건을 정한 내용이에요. 누가 무엇을 해야 하는지, 적용되는 시점과 예외가 있는지를 중심으로 읽으면 이해하기 쉬워요.`;
}

const CHOICE_HINT: Record<SuggestionChoice, string> = {
  ACCEPT: "요청서에서 제외돼요",
  COMPROMISE: "요청서에 담겨요 · 빼려면 원안 수용을 선택하세요",
  REQUEST: "요청서에 담겨요 · 빼려면 원안 수용을 선택하세요",
};

function TonePolishControl({
  contractId,
  text,
  onApply,
}: {
  contractId: string;
  text: string;
  onApply: (text: string) => void;
}) {
  const [result, setResult] = useState<{ source: string; polished: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ source: string; message: string } | null>(null);
  const currentResult = result?.source === text ? result.polished : null;
  const currentError = error?.source === text ? error.message : null;

  const polish = async () => {
    if (!text.trim() || loading) return;
    const source = text;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const polished = await adapter.polishAdjustmentCopy(contractId, source);
      setResult({ source, polished });
    } catch (cause) {
      setError({
        source,
        message: cause instanceof Error ? cause.message : "문구를 다듬지 못했습니다.",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => void polish()}
        disabled={!text.trim() || loading}
        className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-brand400 bg-brand50 px-2.5 py-1 text-[0.6875em] font-bold text-brand700 transition hover:bg-brand100 disabled:opacity-40"
      >
        {loading ? "AI가 다듬는 중…" : "✨ AI로 정중하게 다듬기"}
      </button>

      {currentError && (
        <p className="mt-1.5 text-[0.6875em] font-bold text-red-700" role="alert">
          ⚠ {currentError}
        </p>
      )}

      {currentResult !== null && (
        <div className="mt-2 rounded-lg border border-brand600 bg-brand50 px-3 py-2.5">
          <div className="mb-1 text-[0.625em] font-bold text-brand800">이렇게 바꿔봤어요</div>
          <p className="text-[0.75em] leading-relaxed text-ink">“{currentResult}”</p>
          <p className="mt-1 text-[0.625em] leading-relaxed text-neutral500">
            숫자와 핵심 조건이 그대로인지 적용 전에 확인해 주세요.
          </p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => onApply(currentResult)}
              className="flex-1 rounded-md bg-ink px-3 py-1.5 text-[0.6875em] font-bold text-white"
            >
              이 문구로 적용
            </button>
            <button
              type="button"
              onClick={() => setResult(null)}
              className="flex-1 rounded-md border border-neutral300 bg-white px-3 py-1.5 text-[0.6875em] font-bold text-neutral700"
            >
              취소
            </button>
          </div>
        </div>
      )}
    </>
  );
}

function UnlinkedClauseSourceCard({
  clause,
  confirmed,
  onAction,
}: {
  clause: ClauseData;
  confirmed: boolean;
  onAction: () => void;
}) {
  return (
    <div className="rounded-xl border border-brand200 bg-brand50 px-4 py-3.5">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-[0.84em] font-black text-ink">{clause.title}</h4>
        <span className="rounded-full bg-brand100 px-2 py-0.5 text-[0.68em] font-bold text-brand700">
          {SIGNAL_META[clause.signal]}
        </span>
      </div>
      <p className="mt-2 text-[0.74em] leading-relaxed text-neutral700">
        {clause.aiExplanation}
      </p>
      <button
        type="button"
        onClick={onAction}
        className="mt-3 rounded-lg bg-brand800 px-3 py-1.5 text-[0.72em] font-bold text-white"
      >
        {confirmed ? "요청서에서 보기" : "확인하고 요청서에 담기"}
      </button>
    </div>
  );
}

function RequestCard({
  contractId,
  clause,
  choice,
  text,
  active,
  onChoice,
  onText,
  onViewOriginal,
  onDelete,
}: {
  contractId: string;
  clause: ClauseData;
  choice: SuggestionChoice;
  text: string;
  active: boolean;
  onChoice: (choice: SuggestionChoice) => void;
  onText: (text: string) => void;
  onViewOriginal?: () => void;
  onDelete: () => void;
}) {
  const changeText = (v: string) => {
    onText(v);
  };
  // 확인 필요 조항 삭제 — 되돌아가면 원문에서 다시 확인해야 하므로 한 번 더 확인받는다
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div
      id={`req-${clause.id}`}
      className={`scroll-mt-4 rounded-xl border px-4 py-3.5 transition ${
        active ? "border-brand700 bg-brand50" : "border-neutral200 bg-white"
      }`}
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-[0.875em] font-black text-ink">{clause.title}</h3>
        <div className="flex flex-none items-center gap-2">
          <span className="rounded-full bg-brand100 px-2 py-0.5 text-[0.6875em] font-bold text-brand700">
            {SIGNAL_META[clause.signal]}
          </span>
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="text-[0.6875em] font-bold text-neutral500 hover:text-brand700"
          >
            ✕ 삭제
          </button>
        </div>
      </div>

      <p className="mb-2.5 text-[0.75em] leading-relaxed text-neutral700">
        {clause.aiExplanation}
      </p>

      {onViewOriginal && (
        <button
          onClick={onViewOriginal}
          className="mb-2.5 text-[0.6875em] font-bold text-brand700 underline underline-offset-2"
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
              className={`rounded-lg border px-3 py-2 text-left text-[0.75em] transition ${
                sel
                  ? "border-2 border-brand700 bg-brand50 font-bold"
                  : "border-neutral300 bg-white hover:border-brand400"
              }`}
            >
              <span className="text-neutral500">{s.label}</span> — {s.text}
              {sel && <span className="ml-1 text-brand700">✓</span>}
            </button>
          );
        })}
      </div>

      {/* 직접 수정 (원안 수용이 아닐 때만) */}
      {choice === "ACCEPT" ? (
        <p className="mt-2.5 text-[0.6875em] text-neutral500">원안을 그대로 수용해요 · 요청서에서 제외</p>
      ) : (
        <div className="mt-2.5">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[0.625em] font-bold text-neutral700">보낼 문구 (직접 수정 가능)</span>
            <span className="text-[0.625em] font-bold text-brand700">{CHOICE_HINT[choice]}</span>
          </div>
          <textarea
            value={text}
            onChange={(e) => changeText(e.target.value)}
            rows={2}
            placeholder="내 말로 막 써도 돼요. 예) 5년은 너무 길어요 ㅠㅠ"
            className="w-full resize-y rounded-lg border border-neutral300 px-3 py-2 text-[0.75em] leading-relaxed text-ink outline-none focus:border-ink placeholder:text-neutral400"
          />

          <TonePolishControl contractId={contractId} text={text} onApply={onText} />
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
  contractId,
  draftId,
  draft,
  sourceBody,
  onText,
  onRemove,
  onViewOriginal,
}: {
  contractId: string;
  draftId: string;
  draft: ClauseDraft;
  sourceBody: string;
  onText: (text: string) => void;
  onRemove: () => void;
  onViewOriginal?: () => void;
}) {
  const changeText = (v: string) => {
    onText(v);
  };

  return (
    <div
      id={`req-${draftId}`}
      className="scroll-mt-4 rounded-xl border border-neutral200 bg-white px-4 py-3.5"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-[0.875em] font-black text-ink">{draft.title}</h3>
        <div className="flex flex-none items-center gap-2">
          <span className="rounded-full bg-brand100 px-2 py-0.5 text-[0.6875em] font-bold text-brand700">
            직접 추가
          </span>
          <button
            type="button"
            onClick={onRemove}
            className="text-[0.6875em] font-bold text-neutral500 hover:text-brand700"
          >
            ✕ 삭제
          </button>
        </div>
      </div>

      {sourceBody && (
        <p className="mb-2.5 whitespace-pre-line text-[0.75em] leading-relaxed text-neutral700">
          {sourceBody}
        </p>
      )}

      {onViewOriginal && (
        <button
          onClick={onViewOriginal}
          className="mb-2.5 text-[0.6875em] font-bold text-brand700 underline underline-offset-2"
        >
          ↖ 원문에서 보기
        </button>
      )}

      <div className="mt-1">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-[0.625em] font-bold text-neutral700">보낼 문구 (직접 작성)</span>
          <span className="text-[0.625em] font-bold text-brand700">요청서에 담겨요</span>
        </div>
        <textarea
          value={draft.text}
          onChange={(e) => changeText(e.target.value)}
          rows={2}
          placeholder="추가하고 싶은 요청을 자유롭게 써주세요."
          className="w-full resize-y rounded-lg border border-neutral300 px-3 py-2 text-[0.75em] leading-relaxed text-ink outline-none focus:border-ink placeholder:text-neutral400"
        />

        <TonePolishControl contractId={contractId} text={draft.text} onApply={onText} />
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  tile,
  num,
}: {
  label: string;
  value: number;
  /** 타일 배경·테두리 유틸 클래스 */
  tile: string;
  /** 라벨·숫자 글자색 유틸 클래스 */
  num: string;
}) {
  return (
    <div className={`rounded-2xl px-4 py-3.5 ${tile}`}>
      <div className={`text-[12px] font-bold ${num}`}>{label}</div>
      <div className={`mt-1 text-3xl font-black tabular-nums ${num}`}>{value}</div>
    </div>
  );
}
