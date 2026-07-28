"use client";

import { useParams } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { Timeline } from "@/components/Timeline";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import { MODUSIGN_STATUS_LABEL, modusignStep } from "@/lib/status";
import type { SignatureState } from "@/lib/types";

/* ⑨ 모두싸인 서명 상태 + 감사 타임라인.
   외부 상태(ON_PROCESSING 등)를 쉬운 한국어로 변환해 표시(§6.9). */
export default function SignaturePage() {
  const { id } = useParams<{ id: string }>();
  const state = useAsync(() => adapter.getContract(id), [id]);

  return (
    <AppScreen
      title="서명 상태 · 타임라인"
      backHref="/dashboard"
      footer={
        state.status === "ready" ? (
          <CTAButton href={`/contracts/${id}/obligations`}>
            산출물 증빙 확인하기
          </CTAButton>
        ) : undefined
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}

      {state.status === "ready" && (
        <div className="flex flex-col gap-5">
          <SignatureStatus sig={state.data.signature} />

          <div>
            <h3 className="mb-3 text-[13px] font-bold text-gray700">
              감사 타임라인
            </h3>
            <Timeline events={state.data.timeline} />
          </div>
        </div>
      )}
    </AppScreen>
  );
}

function SignatureStatus({ sig }: { sig: SignatureState }) {
  const step = modusignStep(sig.modusign);
  const labels = ["처리 중", "서명 진행 중", "서명 완료"];

  return (
    <div className="rounded-xl border border-gray200 bg-white p-4">
      <div className="text-sm font-black text-ink">
        {MODUSIGN_STATUS_LABEL[sig.modusign]}
      </div>

      {/* 3단계 진행 바 */}
      <div className="mt-3 flex gap-1.5">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={`h-1.5 flex-1 rounded-full ${
              i < step
                ? "bg-amber700"
                : i === step
                  ? "bg-amber400"
                  : "bg-gray200"
            }`}
          />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-gray500">
        {labels.map((l, i) => (
          <span
            key={l}
            className={i === step ? "font-bold text-amber700" : ""}
          >
            {l}
          </span>
        ))}
      </div>

      <div className="mt-3 text-xs text-gray700">
        {sig.ownerSigned ? "사장님 서명 완료" : "사장님 서명 대기"} ·{" "}
        {sig.agencySigned ? "대행사 서명 완료" : "대행사 서명 대기 중"}
      </div>
      {sig.documentId && (
        <div className="mt-1 text-[10px] text-gray500">
          모두싸인 문서 ID: {sig.documentId}
        </div>
      )}
    </div>
  );
}
