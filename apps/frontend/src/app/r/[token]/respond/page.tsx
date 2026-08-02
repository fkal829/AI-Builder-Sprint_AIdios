"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AgencyShell } from "@/components/AgencyShell";
import { adapter } from "@/lib/adapter";
import { displayText } from "@/lib/displayText";
import { useAsync } from "@/lib/hooks";
import type { AgencyDecision } from "@/lib/types";

type ItemState = { decision: AgencyDecision | null; reason: string; counter: string };

/* 대행사 ② 조항별 수락/거절/역제안 — 거절·역제안 시 한 줄 사유 입력. */
export default function AgencyRespondPage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getAdjustmentRequest(token), [token]);
  const [answers, setAnswers] = useState<Record<string, ItemState>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const items = useMemo(
    () => (state.status === "ready" && state.data ? state.data.items : []),
    [state],
  );
  const answeredCount = useMemo(
    () => items.filter((it) => answers[it.clauseId]?.decision).length,
    [items, answers],
  );
  const allAnswered =
    items.length > 0 &&
    answeredCount === items.length &&
    items.every((item) => {
      const answer = answers[item.clauseId];
      if (answer?.decision === "REJECT") return Boolean(answer.reason.trim());
      if (answer?.decision === "COUNTER") {
        return Boolean(answer.counter.trim() && answer.reason.trim());
      }
      return answer?.decision === "ACCEPT";
    });

  const setItem = (id: string, patch: Partial<ItemState>) =>
    setAnswers((a) => ({
      ...a,
      [id]: {
        decision: a[id]?.decision ?? null,
        reason: a[id]?.reason ?? "",
        counter: a[id]?.counter ?? "",
        ...patch,
      },
    }));

  const submit = async () => {
    if (!allAnswered || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await adapter.submitAdjustmentResponses(
        token,
        items.map((item) => ({
          itemId: item.clauseId,
          decision: answers[item.clauseId].decision!,
          counterText: answers[item.clauseId].counter,
          reason: answers[item.clauseId].reason,
        })),
      );
      router.push(`/r/${token}/done`);
    } catch (error) {
      setSubmitError(
        error instanceof Error ? error.message : "응답을 제출하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AgencyShell
      ownerLabel="조정 요청 응답"
      subtitle="조항마다 수락·거절·역제안 중 하나를 선택해주세요"
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>
      )}

      {state.status === "ready" && (
        <div className="flex flex-col gap-3">
          {items.map((it) => {
            const cur = answers[it.clauseId];
            return (
              <div
                key={it.clauseId}
                className="rounded-xl border border-neutral200 bg-white p-4"
              >
                {/* 원본 계약서 — 무엇이 바뀌는 요청인지 판단할 근거 */}
                <div className="rounded-lg bg-subtle px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-bold text-neutral500">
                      원본 계약서
                    </span>
                    {it.sourcePage && (
                      <span className="flex-none text-[10px] text-neutral500">
                        원계약 {it.sourcePage}쪽
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[12px] leading-relaxed text-neutral700">
                    {it.beforeText
                      ? `“${displayText(it.beforeText)}”`
                      : "원계약에서 확인되지 않아 추가 확인이 필요합니다."}
                  </p>
                </div>

                <div className="py-1 text-center text-[11px] text-neutral400">
                  ↓
                </div>

                {/* 변경사항 확인 — 사장님이 보낸 요청 문구 */}
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <span className="text-[10px] font-bold text-brand700">
                      변경사항 확인
                    </span>
                    <p className="mt-1 text-[13px] font-bold text-ink">
                      “{displayText(it.requestText)}”
                    </p>
                  </div>
                  {it.officialBasis && (
                    <span className="flex-none rounded-full bg-neutral100 px-2 py-1 text-[10px] text-neutral700">
                      근거 있음
                    </span>
                  )}
                </div>
                {it.officialBasis && (
                  <p className="mt-1.5 text-[11px] text-neutral500">
                    {displayText(it.officialBasis)}
                  </p>
                )}

                <div className="mt-3 flex gap-2">
                  {(["ACCEPT", "REJECT", "COUNTER"] as AgencyDecision[]).map(
                    (d) => {
                      const active = cur?.decision === d;
                      const label =
                        d === "ACCEPT"
                          ? "수락"
                          : d === "REJECT"
                            ? "거절"
                            : "역제안";
                      return (
                        <button
                          key={d}
                          onClick={() => setItem(it.clauseId, { decision: d })}
                          className={`h-9 flex-1 rounded-lg border text-[12px] font-bold transition ${
                            active
                              ? "border-2 border-brand700 bg-brand50 text-ink"
                              : "border-neutral300 bg-white text-neutral700 hover:bg-subtle"
                          }`}
                        >
                          {label}
                        </button>
                      );
                    },
                  )}
                </div>

                {/* 거절·역제안 시 사유/문구 입력 */}
                {cur?.decision === "COUNTER" && (
                  <input
                    value={cur.counter}
                    onChange={(e) =>
                      setItem(it.clauseId, { counter: e.target.value })
                    }
                    placeholder="역제안 문구 (예: 2년)"
                    className="mt-2 w-full rounded-lg border-2 border-ink px-3 py-2 text-[13px] outline-none"
                  />
                )}
                {(cur?.decision === "REJECT" || cur?.decision === "COUNTER") && (
                  <input
                    value={cur.reason}
                    onChange={(e) =>
                      setItem(it.clauseId, { reason: e.target.value })
                    }
                    placeholder="한 줄 사유 (예: 사내 규정상 조정 어려움)"
                    className="mt-2 w-full rounded-lg border border-neutral300 px-3 py-2 text-[13px] outline-none"
                  />
                )}
              </div>
            );
          })}

          <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-neutral200 bg-white py-3">
            <span className="text-[12px] text-neutral500">
              {answeredCount} / {items.length}건 응답 완료
            </span>
            <button
              disabled={!allAnswered || submitting}
              onClick={submit}
              className="h-11 rounded-lg bg-ink px-6 text-[13px] font-bold text-white disabled:opacity-40"
            >
              {submitting ? "제출 중…" : "응답 제출하기"}
            </button>
          </div>
          {submitError && <p className="text-[12px] text-brand800">{submitError}</p>}
        </div>
      )}
    </AgencyShell>
  );
}
