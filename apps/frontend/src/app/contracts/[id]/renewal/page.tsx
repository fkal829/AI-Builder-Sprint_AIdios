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
    <AppScreen title="만료·재계약 검토" size="md" backHref="/dashboard">
      {state.status === "loading" && (
        <p className="py-10 text-center text-base text-neutral500">불러오는 중…</p>
      )}
      {state.status === "error" && (
        <p className="py-10 text-center text-base font-bold text-brand800">⚠ {state.error}</p>
      )}
      {view && (
        <div className="flex flex-col gap-6">
          <div>
            <h2 className="text-xl font-black text-ink">{view.title}</h2>
            <p className="mt-1.5 text-[15px] text-neutral500">계약 만료와 통보기한을 확인해주세요.</p>
          </div>
          <DdayRow renewal={view} />

          {view.currentDecision ? (
            <div className="rounded-xl border-2 border-brand700 bg-brand50 p-6">
              <div className="text-lg font-black text-brand700">
                {decisionLabel(view.currentDecision)}
              </div>
              <p className="mt-2 text-[15px] leading-loose text-neutral700">
                선택만 저장했습니다. 새 계약서·조정 요청·서명은 자동으로 시작되지 않습니다.
              </p>
              {view.currentDecision === "RENEW_WITH_CHANGES" && (
                <p className="mt-3 text-[15px] font-bold text-neutral700">
                  다시 검토할 원안 유지 항목 {view.revisitReviewItemIds.length}건
                </p>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-3">
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

          {error && <p className="text-sm font-bold text-red-700">{error}</p>}
          <p className="text-[14px] leading-loose text-neutral500">
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
    <div className="flex gap-3">
      {items.map((item) => (
        <div
          key={item.label}
          className={`flex-1 rounded-xl px-4 py-5 text-center ${
            item.emphasis ? "border-2 border-brand600 bg-brand50" : "bg-subtle"
          }`}
        >
          <div className={`text-2xl font-black ${item.emphasis ? "text-brand700" : "text-ink"}`}>
            {item.d === null ? "—" : item.d >= 0 ? `D-${item.d}` : `D+${Math.abs(item.d)}`}
          </div>
          <div className="mt-1.5 text-[13px] text-neutral500">{item.label}</div>
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
      className={`rounded-xl border-2 px-5 py-4 text-left text-[16px] font-bold transition disabled:opacity-40 ${
        emphasized
          ? "border-brand700 bg-brand50 text-ink hover:bg-brand100"
          : "border-ink bg-white text-ink hover:bg-subtle"
      }`}
    >
      {active ? "저장 중…" : label}
      {description && <span className="mt-1.5 block text-[14px] font-medium leading-relaxed text-neutral500">{description}</span>}
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
