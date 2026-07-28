"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { EmptyState } from "@/components/EmptyState";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import type { ContractDetail } from "@/lib/types";

/* ⑦ 발송 후 대기 + 역제안 비교. 역제안이 오면 ⑥~⑦ 루프로 다시 들어감. */
export default function ResponsesPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(id), [id]);
  const [view, setView] = useState<"normal" | "no_response" | "all_rejected">(
    "normal",
  );

  return (
    <AppScreen
      title="대행사 응답"
      backHref="/dashboard"
      right={
        <ViewSwitch view={view} onChange={setView} />
      }
      footer={
        view === "normal" && state.status === "ready" ? (
          <CTAButton href={`/contracts/${id}/agreement`}>
            변경·확인 합의서 만들기
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
                onClick={() => router.push(`/contracts/${id}/agreement`)}
                className="h-11 flex-1 rounded-lg border border-gray300 bg-white text-[13px] font-bold text-gray500"
              >
                원안대로 진행
              </button>
            </div>
          }
        />
      )}

      {state.status === "ready" && view === "normal" && (
        <ResponsesBody data={state.data} contractId={id} />
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
  contractId,
}: {
  data: ContractDetail;
  contractId: string;
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
            <a
              href={`/contracts/${contractId}/agreement`}
              className="flex h-11 items-center justify-center rounded-lg border-2 border-amber700 bg-amber50 text-[13px] font-bold text-ink"
            >
              역제안 수락 — {counter.agencyResponse?.counterText}으로 합의
            </a>
            <a
              href={`/contracts/${contractId}/request`}
              className="flex h-11 items-center justify-center rounded-lg border border-gray300 bg-white text-[13px] font-medium text-gray700"
            >
              다시 조정 요청하기
            </a>
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
