"use client";

import { useParams, useRouter } from "next/navigation";
import { AppScreen } from "@/components/AppScreen";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import type { RenewalState } from "@/lib/types";

/* ⑪ 만료·재계약 검토 — D-30/D-14/D-7 3단계 + 선택지 3종.
   조건 변경을 고르면 지난번 거절·원안유지된 조항을 다시 보여줌(§6.12). */
export default function RenewalPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(id), [id]);

  return (
    <AppScreen title="만료·재계약 검토" size="sm" backHref="/dashboard">
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}

      {state.status === "ready" && (
        <div className="flex flex-col gap-4">
          <h2 className="text-base font-black text-ink">계약 만료가 다가와요</h2>

          <DdayRow renewal={state.data.renewal} />

          {state.data.renewal.previouslyKeptClause && (
            <div className="rounded-lg bg-gray100 px-3.5 py-3 text-xs text-ink">
              지난번 원안 유지된 조항:{" "}
              <b>{state.data.renewal.previouslyKeptClause}</b>
              <span className="text-gray500"> — 재계약 시 다시 조정 요청 가능</span>
            </div>
          )}

          <div className="flex flex-col gap-2">
            <button
              onClick={() => router.push(`/contracts/${id}/signature`)}
              className="rounded-lg border-2 border-ink bg-white px-4 py-3 text-left text-[13px] font-bold text-ink hover:bg-paper"
            >
              동일 조건 재계약
            </button>
            <button
              onClick={() => router.push(`/contracts/${id}/request`)}
              className="rounded-lg border-2 border-amber700 bg-amber50 px-4 py-3 text-left text-[13px] font-bold text-ink"
            >
              조건 변경 후 재계약
              <span className="ml-1 block text-[11px] font-medium text-amber700">
                지난번 원안 유지된 조항을 다시 조정 요청해요
              </span>
            </button>
            <button
              onClick={() => router.push("/dashboard")}
              className="rounded-lg border border-gray300 bg-white px-4 py-3 text-left text-[13px] font-bold text-gray500 hover:bg-paper"
            >
              종료
            </button>
          </div>

          <p className="text-[11px] leading-relaxed text-gray500">
            알림은 웹 대시보드로만 표시돼요. 재계약 문서 자동 생성은 다음 버전(P1)
            입니다.
          </p>
        </div>
      )}
    </AppScreen>
  );
}

function DdayRow({ renewal }: { renewal: RenewalState }) {
  const items = [
    { d: renewal.expiryDday, label: "만료", emphasis: false },
    { d: renewal.noticeDday, label: "해지통보", emphasis: false },
    { d: renewal.autoRenewDday, label: "자동갱신 임박", emphasis: true },
  ];
  return (
    <div className="flex gap-2">
      {items.map((it) => (
        <div
          key={it.label}
          className={`flex-1 rounded-lg px-2 py-2.5 text-center ${
            it.emphasis ? "border border-amber600 bg-amber50" : "bg-paper"
          }`}
        >
          <div
            className={`text-sm font-black ${
              it.emphasis ? "text-amber700" : "text-ink"
            }`}
          >
            D-{it.d}
          </div>
          <div className="text-[9px] text-gray500">{it.label}</div>
        </div>
      ))}
    </div>
  );
}
