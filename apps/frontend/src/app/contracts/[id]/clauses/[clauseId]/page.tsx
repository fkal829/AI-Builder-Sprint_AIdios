"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ClauseCard } from "@/components/ClauseCard";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import type { SuggestionChoice } from "@/lib/types";

/* ⑤ 조항 카드 상세 / 문구 선택 — 2-2 상세 패널을 화면으로 사용. */
export default function ClauseDetailPage() {
  const { id, clauseId } = useParams<{ id: string; clauseId: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(id), [id]);
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
      backHref={`/contracts/${id}`}
      footer={
        clause ? (
          <CTAButton
            disabled={!selected}
            onClick={() => router.push(`/contracts/${id}`)}
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
