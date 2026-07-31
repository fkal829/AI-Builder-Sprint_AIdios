"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { EmptyState } from "@/components/EmptyState";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import type { ContractDetail } from "@/lib/types";

/* ⑦ 발송 후 대기 + 역제안 비교. P0는 응답 한 번 뒤 사람이 결과를 확정한다. */
export default function ResponsesPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(id), [id]);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [view, setView] = useState<"normal" | "no_response" | "all_rejected">(
    "normal",
  );

  const continueToRevision = async () => {
    if (confirming) return;
    setConfirming(true);
    setConfirmError(null);
    try {
      const adjustmentId =
        window.localStorage.getItem(`dandi:last-adjustment:${id}`) ?? "mock-adjustment";
      await adapter.confirmAdjustmentResult(id, adjustmentId);
      router.push(`/contracts/${id}/revision`);
    } catch (error) {
      setConfirmError(
        error instanceof Error ? error.message : "조정 결과를 확정하지 못했습니다.",
      );
    } finally {
      setConfirming(false);
    }
  };

  return (
    <AppScreen
      title="대행사 응답"
      backHref="/dashboard"
      right={
        <ViewSwitch view={view} onChange={setView} />
      }
      footer={
        view === "normal" && state.status === "ready" ? (
          <CTAButton onClick={continueToRevision}>
            {confirming ? "확정 중…" : "응답 확정하고 수정 계약서 확인하기"}
          </CTAButton>
        ) : undefined
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}

      {state.status === "ready" && view === "no_response" && (
        <EmptyState
          title="아직 답변이 없어요"
          big="D+6"
          body="응답이 없는 것도 중요한 정보예요. 대행사에 다시 알림을 보내거나, 직접 연락해보실 수 있어요."
          actions={
            <CTAButton variant="secondary" onClick={() => setView("normal")}>
              알림 다시 보내기
            </CTAButton>
          }
        />
      )}

      {state.status === "ready" && view === "all_rejected" && (
        <EmptyState
          title="요청하신 조항이 모두 원안으로 유지돼요"
          body="대행사가 조정에 동의하지 않았어요. 원안대로 서명할지, 여기서 멈출지 결정하실 수 있어요."
          actions={
            <div className="flex gap-2">
              <button
                onClick={() => setView("normal")}
                className="h-11 flex-1 rounded-lg border-2 border-ink bg-white text-[13px] font-bold text-ink"
              >
                여기서 멈출게요
              </button>
              <button
                onClick={continueToRevision}
                className="h-11 flex-1 rounded-lg border border-gray300 bg-white text-[13px] font-bold text-gray500"
              >
                원안대로 최종 계약서 확인
              </button>
            </div>
          }
        />
      )}

      {state.status === "ready" && view === "normal" && (
        <>
          <ResponsesBody data={state.data} onConfirm={continueToRevision} />
          {confirmError && (
            <p className="mt-3 text-xs font-bold text-red-700">{confirmError}</p>
          )}
        </>
      )}
    </AppScreen>
  );
}

function ViewSwitch({
  view,
  onChange,
}: {
  view: string;
  onChange: (v: "normal" | "no_response" | "all_rejected") => void;
}) {
  return (
    <select
      value={view}
      onChange={(e) =>
        onChange(e.target.value as "normal" | "no_response" | "all_rejected")
      }
      className="rounded-md border border-gray300 bg-white px-1.5 py-1 text-[10px] text-gray700"
      aria-label="상태 미리보기"
    >
      <option value="normal">정상 응답</option>
      <option value="no_response">무응답</option>
      <option value="all_rejected">전부 거절</option>
    </select>
  );
}

function ResponsesBody({
  data,
  onConfirm,
}: {
  data: ContractDetail;
  onConfirm: () => void;
}) {
  const requested = useMemo(
    () =>
      data.clauses.filter(
        (c) => c.userChoice === "REQUEST" || c.userChoice === "COMPROMISE",
      ),
    [data],
  );
  const responded = requested.filter((c) => c.agencyResponse);
  const counter = requested.find((c) => c.agencyResponse?.decision === "COUNTER");

  return (
    <div className="flex flex-col gap-4">
      {/* 대기 상태 */}
      <div className="rounded-xl border border-gray200 bg-white p-4">
        <div className="text-sm font-black text-ink">응답 현황</div>
        <div className="mt-3 flex gap-2.5">
          <div className="flex-1 rounded-lg bg-paper py-2.5 text-center">
            <div className="text-xl font-black text-ink">
              {responded.length}/{requested.length}
            </div>
            <div className="text-[10px] text-gray500">응답 완료</div>
          </div>
          <div className="flex-1 rounded-lg bg-paper py-2.5 text-center">
            <div className="text-xl font-black text-ink">D-4</div>
            <div className="text-[10px] text-gray500">응답 기한</div>
          </div>
        </div>

        <div className="mt-3 flex flex-col gap-1.5">
          {requested.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between rounded-md bg-paper px-3 py-2 text-xs"
            >
              <span className="text-gray700">{c.title}</span>
              <ResponseTag clause={c} />
            </div>
          ))}
        </div>
      </div>

      {/* 역제안 비교 */}
      {counter && (
        <div className="rounded-xl border-2 border-ink bg-white p-4">
          <div className="text-sm font-black text-ink">
            역제안이 도착했어요 — {counter.title}
          </div>
          <div className="mt-3 flex gap-2">
            <div className="flex-1 rounded-lg bg-paper p-3">
              <div className="mb-1 text-[10px] text-gray500">내 요청안</div>
              <div className="text-[13px] font-bold text-ink">
                {counter.understood ?? "조정 요청"}
              </div>
            </div>
            <div className="flex-1 rounded-lg border border-amber600 bg-amber50 p-3">
              <div className="mb-1 text-[10px] text-amber700">대행사 역제안</div>
              <div className="text-[13px] font-bold text-ink">
                {counter.agencyResponse?.counterText}
              </div>
            </div>
          </div>
          <div className="mt-3 rounded-md bg-paper px-3 py-2.5 text-[11px] leading-relaxed text-gray700">
            AI 설명: 원 요청보다 기간이 조금 길어졌지만, 위약금·환불 조건은 그대로
            유지돼요. 확인해보세요.
          </div>
          <div className="mt-3 flex flex-col gap-2">
            <button
              type="button"
              onClick={onConfirm}
              className="flex h-11 items-center justify-center rounded-lg border-2 border-amber700 bg-amber50 text-[13px] font-bold text-ink"
            >
              역제안 수락 후 수정 계약서 확인
            </button>
            <p className="text-center text-[11px] leading-relaxed text-gray500">
              P0에서는 조정 응답을 한 번만 받습니다. 수정본이 다르면 기존 채널로 다시
              요청해주세요.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function ResponseTag({
  clause,
}: {
  clause: ContractDetail["clauses"][number];
}) {
  const r = clause.agencyResponse;
  if (!r)
    return <span className="text-gray500">대기</span>;
  if (r.decision === "ACCEPT")
    return <span className="font-bold text-amber700">수락</span>;
  if (r.decision === "COUNTER")
    return <span className="font-bold text-amber700">역제안 도착</span>;
  return <span className="font-bold text-gray700">원안 유지</span>;
}
