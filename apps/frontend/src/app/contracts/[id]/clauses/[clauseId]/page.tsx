"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ClauseCard } from "@/components/ClauseCard";
import { useAsync } from "@/lib/hooks";
import { adapter, isUsingMock } from "@/lib/adapter";
import { liveReviewItemToClause } from "@/lib/reviewViewModel";
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
        <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>
      )}
      {state.status === "ready" && !clause && (
        <p className="py-10 text-center text-sm text-neutral500">
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
  const clause = item ? liveReviewItemToClause(item) : null;
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
        <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>
      )}
      {state.status === "error" && (
        <p className="py-10 text-center text-sm font-bold text-brand800">⚠ {state.error}</p>
      )}
      {state.status === "ready" && !item && (
        <p className="py-10 text-center text-sm text-neutral500">조항을 찾을 수 없어요.</p>
      )}
      {clause && (
        <div className="flex flex-col gap-3">
          <ClauseCard
            clause={clause}
            variant="detail"
            selectedChoice={selected}
            onSelectChoice={setChoice}
          />
          {error && <p className="text-xs font-bold text-red-700">{error}</p>}
        </div>
      )}
    </AppScreen>
  );
}
