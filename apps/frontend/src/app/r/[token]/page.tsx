"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AgencyShell } from "@/components/AgencyShell";
import { EmptyState } from "@/components/EmptyState";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";

/* 대행사 ① 조정 요청서 열람 — 무가입·토큰 접근. */
export default function AgencyRequestPage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getAdjustmentRequest(token), [token]);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);

  const startResponse = async () => {
    setOpening(true);
    setOpenError(null);
    try {
      await adapter.openAdjustmentRequest(token);
      router.push(`/r/${token}/respond`);
    } catch (error) {
      setOpenError(
        error instanceof Error ? error.message : "요청을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
      );
    } finally {
      setOpening(false);
    }
  };

  if (state.status === "loading")
    return (
      <AgencyShell>
        <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>
      </AgencyShell>
    );

  if (state.status === "error" || !state.data)
    return (
      <AgencyShell>
        <div className="rounded-xl border-2 border-ink bg-white p-6">
          <EmptyState
            title="링크가 만료됐어요"
            code="ADJUSTMENT_LINK_EXPIRED"
            body="이 조정 요청 링크는 만료되었거나 유효하지 않아요. 요청하신 사장님께 새 링크를 부탁해 주세요."
          />
        </div>
      </AgencyShell>
    );

  const req = state.data;

  return (
    <AgencyShell>
      <div className="overflow-hidden rounded-xl border-2 border-ink bg-white">
        <div className="border-b-2 border-ink px-5 py-4">
          <h1 className="text-base font-black text-ink">
            {req.ownerLabel ? `${req.ownerLabel}이 조건 조정을 요청했어요` : "계약 조건 조정 요청이 도착했어요"}
          </h1>
          <p className="mt-1 text-[12px] text-neutral500">
            {req.contractTitle} · 조항 {req.items.length}건
          </p>
        </div>
        <div className="flex flex-col gap-3 border-b border-neutral200 bg-subtle px-5 py-4">
          <h2 className="text-[12px] font-black text-ink">조정 요청 내용</h2>
          {req.items.map((item) => (
            <section
              key={item.clauseId}
              className="rounded-lg border border-neutral200 bg-white p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-bold text-neutral500">원계약 해당 문구</p>
                {item.sourcePage && (
                  <span className="text-[10px] text-neutral500">
                    원계약 {item.sourcePage}쪽
                  </span>
                )}
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-neutral700">
                {item.beforeText
                  ? `“${item.beforeText}”`
                  : "원계약에서 확인되지 않아 추가 확인이 필요합니다."}
              </p>
              <div className="py-1 text-center text-[11px] text-neutral400">↓</div>
              <p className="text-[10px] font-bold text-brand700">요청받은 변경사항</p>
              <p className="mt-1 text-[12px] font-bold leading-relaxed text-ink">
                “{item.requestText}”
              </p>
            </section>
          ))}
        </div>
        <div className="px-5 py-4">
          <button
            onClick={startResponse}
            disabled={opening}
            className="h-12 w-full rounded-lg bg-ink text-[14px] font-bold text-white disabled:opacity-40"
          >
            {opening ? "검토 화면을 여는 중…" : "회원가입 없이 검토 시작"}
          </button>
          {openError && <p className="mt-3 text-[12px] text-brand800">{openError}</p>}
          <p className="mt-3 text-[11px] leading-relaxed text-neutral500">
            수락·거절·역제안한 내용과 사유는 기록으로 남아 사후 분쟁을 줄이는 데
            쓰여요. 별도 가입은 필요하지 않아요.
          </p>
        </div>
      </div>
    </AgencyShell>
  );
}
