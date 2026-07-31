"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { AppScreen } from "@/components/AppScreen";
import { useAsync } from "@/lib/hooks";
import { adapter, type LiveRenewalView } from "@/lib/adapter";

type RenewalDecision = NonNullable<LiveRenewalView["currentDecision"]>;

/* ⑪ 만료·재계약 검토 — 선택을 저장하되 계약·문서·조정·서명을 자동 생성하지 않는다. */
export default function RenewalPage() {
  const { id } = useParams<{ id: string }>();
  const state = useAsync(() => adapter.getRenewalView(id), [id]);
  const [saved, setSaved] = useState<LiveRenewalView | null>(null);
  const [saving, setSaving] = useState<RenewalDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const view = saved ?? (state.status === "ready" ? state.data : null);

  const decide = async (decision: RenewalDecision) => {
    if (saving) return;
    setSaving(decision);
    setError(null);
    try {
      setSaved(await adapter.saveRenewalDecision(id, decision));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "재계약 결정을 저장하지 못했습니다.");
    } finally {
      setSaving(null);
    }
  };

  return (
    <AppScreen title="만료·재계약 검토" size="sm" backHref="/dashboard">
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}
      {state.status === "error" && (
        <p className="py-10 text-center text-sm font-bold text-amber800">⚠ {state.error}</p>
      )}
      {view && (
        <div className="flex flex-col gap-4">
          <div>
            <h2 className="text-base font-black text-ink">{view.title}</h2>
            <p className="mt-1 text-xs text-gray500">계약 만료와 통보기한을 확인해주세요.</p>
          </div>
          <DdayRow renewal={view} />

          {view.currentDecision ? (
            <div className="rounded-xl border-2 border-amber700 bg-amber50 p-4">
              <div className="text-sm font-black text-amber700">
                {decisionLabel(view.currentDecision)}
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-gray700">
                선택만 저장했습니다. 새 계약서·조정 요청·서명은 자동으로 시작되지 않습니다.
              </p>
              {view.currentDecision === "RENEW_WITH_CHANGES" && (
                <p className="mt-2 text-[11px] font-bold text-gray700">
                  다시 검토할 원안 유지 항목 {view.revisitReviewItemIds.length}건
                </p>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <DecisionButton
                label="동일 조건 재계약 의사 저장"
                active={saving === "RENEW_SAME_TERMS"}
                disabled={saving !== null}
                onClick={() => decide("RENEW_SAME_TERMS")}
              />
              <DecisionButton
                label="조건 변경 후 재계약 의사 저장"
                description="지난번 원안 유지 항목을 재검토 대상으로 불러옵니다."
                active={saving === "RENEW_WITH_CHANGES"}
                disabled={saving !== null}
                emphasized
                onClick={() => decide("RENEW_WITH_CHANGES")}
              />
              <DecisionButton
                label="계약 종료 의사 저장"
                active={saving === "TERMINATE"}
                disabled={saving !== null}
                onClick={() => decide("TERMINATE")}
              />
            </div>
          )}

          {error && <p className="text-xs font-bold text-red-700">{error}</p>}
          <p className="text-[11px] leading-relaxed text-gray500">
            재계약 의사는 정해진 검토 기간에만 저장할 수 있습니다. 선택을 저장해도 상대방에게
            자동 통지하거나 계약을 자동 갱신하지 않습니다.
          </p>
        </div>
      )}
    </AppScreen>
  );
}

function DdayRow({ renewal }: { renewal: LiveRenewalView }) {
  const items = [
    { d: renewal.expiryDday, label: "만료", emphasis: false },
    { d: renewal.noticeDday, label: "해지통보", emphasis: false },
    { d: renewal.autoRenewalDday, label: "자동갱신 임박", emphasis: true },
  ];
  return (
    <div className="flex gap-2">
      {items.map((item) => (
        <div
          key={item.label}
          className={`flex-1 rounded-lg px-2 py-2.5 text-center ${
            item.emphasis ? "border border-amber600 bg-amber50" : "bg-paper"
          }`}
        >
          <div className={`text-sm font-black ${item.emphasis ? "text-amber700" : "text-ink"}`}>
            {item.d === null ? "—" : item.d >= 0 ? `D-${item.d}` : `D+${Math.abs(item.d)}`}
          </div>
          <div className="text-[9px] text-gray500">{item.label}</div>
        </div>
      ))}
    </div>
  );
}

function DecisionButton({
  label,
  description,
  active,
  disabled,
  emphasized = false,
  onClick,
}: {
  label: string;
  description?: string;
  active: boolean;
  disabled: boolean;
  emphasized?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-lg border-2 px-4 py-3 text-left text-[13px] font-bold disabled:opacity-40 ${
        emphasized ? "border-amber700 bg-amber50 text-ink" : "border-ink bg-white text-ink"
      }`}
    >
      {active ? "저장 중…" : label}
      {description && <span className="mt-1 block text-[11px] font-medium text-gray500">{description}</span>}
    </button>
  );
}

function decisionLabel(decision: RenewalDecision): string {
  return {
    RENEW_SAME_TERMS: "동일 조건 재계약 의사를 저장했어요",
    RENEW_WITH_CHANGES: "조건 변경 후 재계약 의사를 저장했어요",
    TERMINATE: "계약 종료 의사를 저장했어요",
  }[decision];
}
