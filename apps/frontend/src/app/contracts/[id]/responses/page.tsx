"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { EmptyState } from "@/components/EmptyState";
import { SavedPublicLink } from "@/components/PublicLinkCard";
import { useAsync } from "@/lib/hooks";
import {
  adapter,
  isUsingMock,
  type AdjustmentResolutionInput,
  type LiveAdjustmentDetail,
} from "@/lib/adapter";
import type { ContractDetail } from "@/lib/types";

/* ⑦ 발송 후 대기 + 역제안 비교. P0는 응답 한 번 뒤 사람이 결과를 확정한다. */
export default function ResponsesPage() {
  const { id } = useParams<{ id: string }>();
  return isUsingMock ? <MockResponsesPage id={id} /> : <LiveResponsesPage id={id} />;
}

function MockResponsesPage({ id }: { id: string }) {
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
      const resolutions: AdjustmentResolutionInput[] = state.status === "ready"
        ? state.data.clauses
            .filter((clause) => clause.agencyResponse)
            .map((clause) => ({
              reviewItemId: clause.id,
              resolution: clause.agencyResponse?.decision === "COUNTER"
                ? "ACCEPT_COUNTERPROPOSAL"
                : clause.agencyResponse?.decision === "ACCEPT"
                  ? "ACCEPT_REQUEST"
                  : "KEEP_ORIGINAL",
            }))
        : [];
      await adapter.confirmAdjustmentResult(id, adjustmentId, resolutions);
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
        <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>
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
                className="h-11 flex-1 rounded-lg border border-neutral300 bg-white text-[13px] font-bold text-neutral500"
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

      {/* 응답이 없거나 다시 보내야 할 때를 위해 전달 링크를 여기서도 확인할 수 있게 둔다 */}
      <div className="mt-4">
        <SavedPublicLink
          contractId={id}
          title="대행사 전달 링크 다시 보기"
          note="답변이 없다면 이 링크를 다시 보내보세요. 같은 요청서를 여는 링크예요."
        />
      </div>
    </AppScreen>
  );
}

function LiveResponsesPage({ id }: { id: string }) {
  const router = useRouter();
  const state = useAsync(async () => {
    const adjustmentId = window.localStorage.getItem(`dandi:last-adjustment:${id}`);
    if (!adjustmentId) {
      throw new Error("이 브라우저에서 발송한 조정 요청을 찾지 못했습니다.");
    }
    return adapter.getAdjustmentDetail(id, adjustmentId);
  }, [id]);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [resolutionOverrides, setResolutionOverrides] = useState<
    Record<string, AdjustmentResolutionInput["resolution"]>
  >({});

  const confirmedItems = state.status === "ready"
    ? state.data.items.map((item) => ({
        reviewItemId: item.reviewItemId,
        resolution: resolutionOverrides[item.reviewItemId] ?? defaultResolution(item.decision),
      }))
    : [];
  const canConfirm = state.status === "ready" && state.data.status === "CONFIRMED"
    ? true
    : confirmedItems.length > 0 && confirmedItems.every((item) => item.resolution !== null);

  const confirmResult = async () => {
    if (state.status !== "ready" || confirming) return;
    if (state.data.status === "CONFIRMED") {
      router.push(`/contracts/${id}/revision`);
      return;
    }
    setConfirming(true);
    setConfirmError(null);
    try {
      if (!canConfirm) {
        throw new Error("각 역제안을 반영할지 원안을 유지할지 선택해주세요.");
      }
      await adapter.confirmAdjustmentResult(
        id,
        state.data.id,
        confirmedItems as AdjustmentResolutionInput[],
      );
      router.push(`/contracts/${id}/revision`);
    } catch (cause) {
      setConfirmError(cause instanceof Error ? cause.message : "조정 결과를 확정하지 못했습니다.");
    } finally {
      setConfirming(false);
    }
  };

  return (
    <AppScreen
      title="대행사 응답"
      backHref="/dashboard"
      footer={
        state.status === "ready"
        && (state.data.status === "RESPONDED" || state.data.status === "CONFIRMED") ? (
          <CTAButton onClick={confirmResult} disabled={confirming || !canConfirm}>
            {confirming ? "확정 중…" : "응답 확정하고 수정 계약서 확인하기"}
          </CTAButton>
        ) : undefined
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-neutral500">응답을 불러오는 중…</p>
      )}
      {state.status === "error" && (
        <p className="py-10 text-center text-sm font-bold text-brand800">⚠ {state.error}</p>
      )}
      {state.status === "ready" && (
        <LiveResponseBody
          detail={state.data}
          resolutions={resolutionOverrides}
          onResolution={(reviewItemId, resolution) => {
            setResolutionOverrides((current) => ({ ...current, [reviewItemId]: resolution }));
          }}
        />
      )}
      {confirmError && <p className="mt-3 text-xs font-bold text-red-700">{confirmError}</p>}

      {/* 응답이 없거나 다시 보내야 할 때를 위해 전달 링크를 여기서도 확인할 수 있게 둔다 */}
      <div className="mt-4">
        <SavedPublicLink
          contractId={id}
          title="대행사 전달 링크 다시 보기"
          note="답변이 없다면 이 링크를 다시 보내보세요. 같은 요청서를 여는 링크예요."
        />
      </div>
    </AppScreen>
  );
}

function LiveResponseBody({
  detail,
  resolutions,
  onResolution,
}: {
  detail: LiveAdjustmentDetail;
  resolutions: Record<string, AdjustmentResolutionInput["resolution"]>;
  onResolution: (
    reviewItemId: string,
    resolution: AdjustmentResolutionInput["resolution"],
  ) => void;
}) {
  if (detail.status === "SENT" || detail.status === "OPENED") {
    return (
      <EmptyState
        title="아직 답변이 없어요"
        body={detail.expiresAt
          ? `응답 기한은 ${detail.expiresAt.slice(0, 10)}까지예요. 필요하면 기존 연락 채널로 확인해주세요.`
          : "대행사의 답변을 기다리고 있어요."}
      />
    );
  }
  if (detail.status === "EXPIRED") {
    return <EmptyState title="응답 기한이 지났어요" body="대행사와 기존 연락 채널로 다음 진행을 확인해주세요." />;
  }

  const respondedCount = detail.items.filter((item) => item.decision !== null).length;
  const counterItems = detail.items.filter((item) => item.decision === "COUNTER");

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-neutral200 bg-white p-4">
        <div className="text-sm font-black text-ink">응답 현황</div>
        <div className="mt-3 flex gap-2.5">
          <div className="flex-1 rounded-lg bg-subtle py-2.5 text-center">
            <div className="text-xl font-black text-ink">
              {respondedCount}/{detail.items.length}
            </div>
            <div className="text-[10px] text-neutral500">응답 완료</div>
          </div>
          <div className="flex-1 rounded-lg bg-subtle py-2.5 text-center">
            <div className="text-sm font-black text-ink">
              {detail.expiresAt?.slice(0, 10) ?? "확인 필요"}
            </div>
            <div className="text-[10px] text-neutral500">응답 기한</div>
          </div>
        </div>

        <div className="mt-3 flex flex-col gap-1.5">
          {detail.items.map((item, index) => (
            <div
              key={item.reviewItemId}
              className="flex items-center justify-between rounded-md bg-subtle px-3 py-2 text-xs"
            >
              <span className="text-neutral700">조정 항목 {index + 1}</span>
              <ResponseDecision decision={item.decision} />
            </div>
          ))}
        </div>
      </div>

      {counterItems.map((item, index) => (
        <article key={item.reviewItemId} className="rounded-xl border-2 border-ink bg-white p-4">
          <div className="text-sm font-black text-ink">
            역제안이 도착했어요 — 조정 항목 {index + 1}
          </div>
          <div className="mt-3 flex gap-2">
            <div className="flex-1 rounded-lg bg-subtle p-3">
              <div className="mb-1 text-[10px] text-neutral500">내 요청안</div>
              <div className="text-[13px] font-bold text-ink">{item.requestText}</div>
            </div>
            <div className="flex-1 rounded-lg border border-brand600 bg-brand50 p-3">
              <div className="mb-1 text-[10px] text-brand700">대행사 역제안</div>
              <div className="text-[13px] font-bold text-ink">{item.counterText}</div>
            </div>
          </div>
          {item.reason && (
            <p className="mt-2 text-[11px] leading-relaxed text-neutral700">사유: {item.reason}</p>
          )}
          {item.comparison && (
            <div className="mt-3 rounded-md bg-subtle px-3 py-2.5 text-[11px] leading-relaxed text-neutral700">
              <b className="text-ink">AI 설명</b>
              <p className="mt-1">{item.comparison.changedSummary}</p>
              {item.comparison.remainingChecks.length > 0 && (
                <ul className="mt-1 list-disc pl-4">
                  {item.comparison.remainingChecks.map((check) => <li key={check}>{check}</li>)}
                </ul>
              )}
              <p className="mt-1 font-bold">{item.comparison.finalConfirmation}</p>
            </div>
          )}
          {detail.status !== "CONFIRMED" && (
            <ResolutionButtons
              selected={resolutions[item.reviewItemId] ?? null}
              acceptLabel="역제안 반영"
              acceptValue="ACCEPT_COUNTERPROPOSAL"
              onSelect={(resolution) => onResolution(item.reviewItemId, resolution)}
            />
          )}
        </article>
      ))}

      {detail.status === "CONFIRMED" && (
        <p className="rounded-lg bg-brand50 p-3 text-[11px] font-bold text-brand700">
          조정 결과를 확정했습니다. 수정 계약서를 업로드해 반영 내용을 확인해주세요.
        </p>
      )}
      <p className="text-[11px] leading-relaxed text-neutral500">
        응답 확정 뒤에도 바로 서명하지 않습니다. 대행사가 다시 보낸 수정 계약서를
        업로드하고 반영 내용을 직접 확인합니다.
      </p>
    </div>
  );
}

function ResolutionButtons({
  selected,
  acceptLabel,
  acceptValue,
  onSelect,
}: {
  selected: AdjustmentResolutionInput["resolution"] | null;
  acceptLabel: string;
  acceptValue: "ACCEPT_REQUEST" | "ACCEPT_COUNTERPROPOSAL";
  onSelect: (resolution: AdjustmentResolutionInput["resolution"]) => void;
}) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      <button
        type="button"
        onClick={() => onSelect(acceptValue)}
        className={`h-10 rounded-lg border text-[12px] font-bold ${
          selected === acceptValue ? "border-brand700 bg-brand50 text-ink" : "border-neutral300 bg-white text-neutral700"
        }`}
      >
        {acceptLabel}
      </button>
      <button
        type="button"
        onClick={() => onSelect("KEEP_ORIGINAL")}
        className={`h-10 rounded-lg border text-[12px] font-bold ${
          selected === "KEEP_ORIGINAL" ? "border-ink bg-neutral100 text-ink" : "border-neutral300 bg-white text-neutral700"
        }`}
      >
        원안 유지
      </button>
    </div>
  );
}

function defaultResolution(
  decision: LiveAdjustmentDetail["items"][number]["decision"],
): AdjustmentResolutionInput["resolution"] | null {
  if (decision === "ACCEPT") return "ACCEPT_REQUEST";
  if (decision === "REJECT") return "KEEP_ORIGINAL";
  return null;
}

function ResponseDecision({ decision }: { decision: LiveAdjustmentDetail["items"][number]["decision"] }) {
  const label = decision === "ACCEPT"
    ? "수락"
    : decision === "COUNTER"
      ? "역제안"
      : decision === "REJECT"
        ? "거절 · 원안 유지"
        : "응답 대기";
  return <span className="rounded bg-subtle px-2 py-1 text-[10px] font-bold text-neutral700">{label}</span>;
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
      className="rounded-md border border-neutral300 bg-white px-1.5 py-1 text-[10px] text-neutral700"
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
      <div className="rounded-xl border border-neutral200 bg-white p-4">
        <div className="text-sm font-black text-ink">응답 현황</div>
        <div className="mt-3 flex gap-2.5">
          <div className="flex-1 rounded-lg bg-subtle py-2.5 text-center">
            <div className="text-xl font-black text-ink">
              {responded.length}/{requested.length}
            </div>
            <div className="text-[10px] text-neutral500">응답 완료</div>
          </div>
          <div className="flex-1 rounded-lg bg-subtle py-2.5 text-center">
            <div className="text-xl font-black text-ink">D-4</div>
            <div className="text-[10px] text-neutral500">응답 기한</div>
          </div>
        </div>

        <div className="mt-3 flex flex-col gap-1.5">
          {requested.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between rounded-md bg-subtle px-3 py-2 text-xs"
            >
              <span className="text-neutral700">{c.title}</span>
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
            <div className="flex-1 rounded-lg bg-subtle p-3">
              <div className="mb-1 text-[10px] text-neutral500">내 요청안</div>
              <div className="text-[13px] font-bold text-ink">
                {counter.understood ?? "조정 요청"}
              </div>
            </div>
            <div className="flex-1 rounded-lg border border-brand600 bg-brand50 p-3">
              <div className="mb-1 text-[10px] text-brand700">대행사 역제안</div>
              <div className="text-[13px] font-bold text-ink">
                {counter.agencyResponse?.counterText}
              </div>
            </div>
          </div>
          <div className="mt-3 rounded-md bg-subtle px-3 py-2.5 text-[11px] leading-relaxed text-neutral700">
            AI 설명: 원 요청보다 기간이 조금 길어졌지만, 위약금·환불 조건은 그대로
            유지돼요. 확인해보세요.
          </div>
          <div className="mt-3 flex flex-col gap-2">
            <button
              type="button"
              onClick={onConfirm}
              className="flex h-11 items-center justify-center rounded-lg border-2 border-brand700 bg-brand50 text-[13px] font-bold text-ink"
            >
              역제안 수락 후 수정 계약서 확인
            </button>
            <p className="text-center text-[11px] leading-relaxed text-neutral500">
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
    return <span className="text-neutral500">대기</span>;
  if (r.decision === "ACCEPT")
    return <span className="font-bold text-brand700">수락</span>;
  if (r.decision === "COUNTER")
    return <span className="font-bold text-brand700">역제안 도착</span>;
  return <span className="font-bold text-neutral700">원안 유지</span>;
}
