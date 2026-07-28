"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AgencyShell } from "@/components/AgencyShell";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import type { AgencyDecision } from "@/lib/types";

type ItemState = { decision: AgencyDecision | null; reason: string; counter: string };

/* 대행사 ② 조항별 수락/거절/역제안 — 거절·역제안 시 한 줄 사유 입력. */
export default function AgencyRespondPage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getAdjustmentRequest(token), [token]);
  const [answers, setAnswers] = useState<Record<string, ItemState>>({});

  const items = state.status === "ready" && state.data ? state.data.items : [];
  const answeredCount = useMemo(
    () => items.filter((it) => answers[it.clauseId]?.decision).length,
    [items, answers],
  );
  const allAnswered = items.length > 0 && answeredCount === items.length;

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

  return (
    <AgencyShell
      ownerLabel="조정 요청 응답"
      subtitle="조항마다 수락·거절·역제안 중 하나를 선택해주세요"
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}

      {state.status === "ready" && (
        <div className="flex flex-col gap-3">
          {items.map((it) => {
            const cur = answers[it.clauseId];
            return (
              <div
                key={it.clauseId}
                className="rounded-xl border border-gray200 bg-white p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-[13px] font-bold text-ink">
                    “{it.requestText}”
                  </p>
                  {it.officialBasis && (
                    <span className="flex-none rounded-full bg-gray100 px-2 py-1 text-[10px] text-gray700">
                      근거 있음
                    </span>
                  )}
                </div>
                {it.officialBasis && (
                  <p className="mt-1.5 text-[11px] text-gray500">
                    {it.officialBasis}
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
                              ? "border-2 border-amber700 bg-amber50 text-ink"
                              : "border-gray300 bg-white text-gray700 hover:bg-paper"
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
                    className="mt-2 w-full rounded-lg border border-gray300 px-3 py-2 text-[13px] outline-none"
                  />
                )}
              </div>
            );
          })}

          <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-gray200 bg-paper/95 py-3 backdrop-blur">
            <span className="text-[12px] text-gray500">
              {answeredCount} / {items.length}건 응답 완료
            </span>
            <button
              disabled={!allAnswered}
              onClick={() => router.push(`/r/${token}/done`)}
              className="h-11 rounded-lg bg-ink px-6 text-[13px] font-bold text-white disabled:opacity-40"
            >
              응답 제출하기
            </button>
          </div>
        </div>
      )}
    </AgencyShell>
  );
}
