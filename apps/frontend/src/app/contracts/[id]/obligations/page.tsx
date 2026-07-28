"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { Disclaimer } from "@/components/Bits";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import type { ObligationStatus } from "@/lib/types";

/* ⑩ 산출물 증빙 확인 — '지급 조건 충족'은 실제 송금이 아님을 문구로 명시(설계 원칙 #8). */
export default function ObligationsPage() {
  const { id } = useParams<{ id: string }>();
  const state = useAsync(() => adapter.getContract(id), [id]);
  const [decision, setDecision] = useState<ObligationStatus | null>(null);

  return (
    <AppScreen
      title="산출물 증빙 확인"
      size="sm"
      backHref="/dashboard"
      footer={
        <CTAButton href={`/contracts/${id}/renewal`} variant="secondary">
          만료·재계약 검토로
        </CTAButton>
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}

      {state.status === "ready" && (
        <div className="flex flex-col gap-4">
          <h2 className="text-base font-black text-ink">산출물을 확인해주세요</h2>

          <div className="rounded-lg bg-paper p-3.5">
            <div className="text-[13px] font-bold text-ink">
              {state.data.obligation.title}
            </div>
            <div className="mt-1 text-[11px] text-gray500">
              기한 {state.data.obligation.dueDate} · 대행사 제출됨
            </div>
            {state.data.obligation.evidenceUrl && (
              <a
                href={state.data.obligation.evidenceUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-1.5 inline-block text-[11px] text-amber700 underline underline-offset-2"
              >
                제출된 증빙 URL 보기 →
              </a>
            )}
          </div>

          {decision === "APPROVED" ? (
            <div className="rounded-lg border-2 border-amber700 bg-amber50 px-4 py-3 text-center">
              <div className="text-sm font-black text-amber700">
                지급 조건 충족으로 표시됨
              </div>
            </div>
          ) : decision === "DISPUTED" ? (
            <div className="rounded-lg border border-gray500 bg-gray100 px-4 py-3 text-center">
              <div className="text-sm font-bold text-gray700">
                이의가 접수됐어요 — 대행사에 전달됩니다
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <CTAButton onClick={() => setDecision("APPROVED")}>
                확인 완료
              </CTAButton>
              <button
                onClick={() => setDecision("DISPUTED")}
                className="h-11 rounded-lg border border-gray300 bg-white text-[13px] font-bold text-gray500"
              >
                이의 있어요
              </button>
            </div>
          )}

          <Disclaimer>
            확인 완료를 누르면 &lsquo;지급 조건 충족&rsquo;으로 표시돼요. 실제
            송금·결제는 이 화면에서 진행되지 않습니다.
          </Disclaimer>
        </div>
      )}
    </AppScreen>
  );
}
