"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ConfirmModal } from "@/components/ConfirmModal";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import type { AgreementClause } from "@/lib/types";

/* ⑧ 광고대행 계약조건 변경·확인 합의서 — 최대 4개 조정 조항 고정 슬롯.
   합의/원안유지가 같은 문서에 나란히. 거절된 것도 지우지 않음(설계 원칙 #6). */
export default function AgreementPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(id), [id]);
  const [confirm, setConfirm] = useState(false);

  const agreed =
    state.status === "ready"
      ? state.data.agreement.filter((a) => a.outcome === "AGREED").length
      : 0;
  const kept =
    state.status === "ready"
      ? state.data.agreement.filter((a) => a.outcome === "KEPT_ORIGINAL").length
      : 0;

  return (
    <AppScreen
      title="변경·확인 합의서"
      backHref={`/contracts/${id}/responses`}
      footer={
        state.status === "ready" ? (
          <CTAButton onClick={() => setConfirm(true)}>전자서명 하러가기</CTAButton>
        ) : undefined
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}

      {state.status === "ready" && (
        <div className="flex flex-col gap-4">
          <div>
            <h2 className="text-base font-black leading-snug text-ink">
              광고대행 계약조건
              <br />
              변경·확인 합의서
            </h2>
            <div className="mt-2 inline-block rounded-md bg-gray100 px-3 py-1.5 text-[11px] font-bold text-gray700">
              합의 {agreed}건 · 원안 유지 {kept}건 (4개 슬롯)
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            {state.data.agreement.map((clause, i) => (
              <AgreementRow key={i} clause={clause} />
            ))}
          </div>

          <p className="text-[11px] leading-relaxed text-gray500">
            거절되거나 원안 유지된 조항도 사라지지 않고 이 문서에 함께 남습니다.
            변경되지 않은 나머지 조건은 원계약을 그대로 따릅니다.
          </p>
        </div>
      )}

      <ConfirmModal
        open={confirm}
        title="서명하면 계약이 확정돼요"
        body={
          <>
            합의 {agreed}건, 원안 유지 {kept}건이 그대로 반영됩니다. 서명 후에는
            되돌릴 수 없어요.
          </>
        }
        confirmLabel="네, 서명할게요"
        onCancel={() => setConfirm(false)}
        onConfirm={() => router.push(`/contracts/${id}/signature`)}
      />
    </AppScreen>
  );
}

function AgreementRow({ clause }: { clause: AgreementClause }) {
  const agreed = clause.outcome === "AGREED";
  return (
    <div
      className={`rounded-md border-l-4 px-3.5 py-2.5 ${
        agreed
          ? "border-amber700 bg-amber50"
          : "border-gray500 bg-gray100"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-bold text-ink">{clause.title}</span>
        <span
          className={`text-xs font-bold ${
            agreed ? "text-amber700" : "text-gray700"
          }`}
        >
          {agreed ? "합의" : "원안 유지"}
        </span>
      </div>
      <div className="mt-1 text-[11px] text-gray700">
        {agreed ? (
          <>
            변경 전 <span className="text-gray500">{clause.before}</span> → 변경 후{" "}
            <span className="font-bold text-ink">{clause.after}</span>
          </>
        ) : (
          <>
            {clause.before} 그대로
            {clause.reason && (
              <span className="text-gray500"> · 사유: {clause.reason}</span>
            )}
          </>
        )}
      </div>
    </div>
  );
}
