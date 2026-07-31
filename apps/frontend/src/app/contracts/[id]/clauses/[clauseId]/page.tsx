"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ClauseCard } from "@/components/ClauseCard";
import { useAsync } from "@/lib/hooks";
import { adapter, isUsingMock } from "@/lib/adapter";
import type { SuggestionChoice } from "@/lib/types";

/* ⑤ 조항 카드 상세 / 문구 선택 — 2-2 상세 패널을 화면으로 사용. */
export default function ClauseDetailPage() {
  const { id, clauseId } = useParams<{ id: string; clauseId: string }>();
  return isUsingMock
    ? <MockClauseDetail contractId={id} clauseId={clauseId} />
    : <LiveClauseDetail contractId={id} clauseId={clauseId} />;
}

function MockClauseDetail({ contractId, clauseId }: { contractId: string; clauseId: string }) {
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(contractId), [contractId]);
  const [choice, setChoice] = useState<SuggestionChoice | null>(null);

  const clause =
    state.status === "ready"
      ? state.data.clauses.find((c) => c.id === clauseId) ?? null
      : null;

  const selected = choice ?? clause?.userChoice ?? null;

  return (
    <AppScreen
      title="조항 검토"
      size="sm"
      backHref={`/contracts/${contractId}`}
      footer={
        clause ? (
          <CTAButton
            disabled={!selected}
            onClick={() => router.push(`/contracts/${contractId}`)}
          >
            이 문구로 저장
          </CTAButton>
        ) : undefined
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}
      {state.status === "ready" && !clause && (
        <p className="py-10 text-center text-sm text-gray500">
          조항을 찾을 수 없어요.
        </p>
      )}
      {clause && (
        <ClauseCard
          clause={clause}
          variant="detail"
          selectedChoice={selected}
          onSelectChoice={setChoice}
        />
      )}
    </AppScreen>
  );
}

function LiveClauseDetail({ contractId, clauseId }: { contractId: string; clauseId: string }) {
  const router = useRouter();
  const state = useAsync(() => adapter.getLiveContractReview(contractId), [contractId]);
  const [choice, setChoice] = useState<SuggestionChoice | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const item = state.status === "ready"
    ? state.data.items.find((candidate) => candidate.id === clauseId) ?? null
    : null;
  const selected = choice ?? item?.userChoice ?? null;

  const save = async () => {
    if (!item || !selected || saving) return;
    setSaving(true);
    setError(null);
    try {
      await adapter.selectReviewItem(contractId, item.id, selected);
      router.push(`/contracts/${contractId}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "선택을 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppScreen
      title="조항 검토"
      size="sm"
      backHref={`/contracts/${contractId}`}
      footer={
        item ? (
          <CTAButton disabled={!selected || saving} onClick={save}>
            {saving ? "저장 중…" : "이 문구로 저장"}
          </CTAButton>
        ) : undefined
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}
      {state.status === "error" && (
        <p className="py-10 text-center text-sm font-bold text-amber800">⚠ {state.error}</p>
      )}
      {state.status === "ready" && !item && (
        <p className="py-10 text-center text-sm text-gray500">조항을 찾을 수 없어요.</p>
      )}
      {item && (
        <div className="flex flex-col gap-3">
          <div className="rounded-xl border border-gray200 bg-white p-4">
            <h2 className="text-sm font-black text-ink">{item.plainExplanation}</h2>
            <p className="mt-3 rounded-lg bg-paper p-3 text-[12px] leading-relaxed text-gray700">
              {item.sourcePage ? `계약서 ${item.sourcePage}쪽: ` : "원문 근거 없음: "}
              {item.sourceText ?? "직접 확인이 필요합니다."}
            </p>
          </div>
          {([
            ["ACCEPT", "원안 수용", item.suggestionAccept],
            ["COMPROMISE", "절충안", item.suggestionCompromise],
            ["REQUEST", "요청안", item.suggestionRequest],
          ] as const).map(([value, label, text]) => (
            <button
              key={value}
              type="button"
              onClick={() => setChoice(value)}
              className={`rounded-xl border p-4 text-left ${
                selected === value ? "border-amber700 bg-amber50" : "border-gray300 bg-white"
              }`}
            >
              <span className="text-[11px] font-bold text-gray500">{label}</span>
              <span className="mt-1 block text-[13px] font-bold leading-relaxed text-ink">{text}</span>
            </button>
          ))}
          {error && <p className="text-xs font-bold text-red-700">{error}</p>}
        </div>
      )}
    </AppScreen>
  );
}
