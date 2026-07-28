"use client";

import { useRouter, useParams } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ClauseCard } from "@/components/ClauseCard";
import { LayerBlock } from "@/components/LayerBlock";
import { EmptyState } from "@/components/EmptyState";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";
import { SIGNAL_META } from "@/lib/status";
import type { ContractDetail, ReviewSignalType } from "@/lib/types";

/* ④ 핵심조건·원문 비교 + 분석 요약 → 조항 카드 목록(⑤ 진입) */
export default function ComparePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(id), [id]);

  return (
    <AppScreen
      title="분석 결과"
      backHref="/dashboard"
      footer={
        state.status === "ready" && state.data.clauses.length > 0 ? (
          <CTAButton href={`/contracts/${id}/request`}>
            조정 요청서 만들기
          </CTAButton>
        ) : undefined
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
      )}
      {state.status === "ready" && (
        <CompareBody
          data={state.data}
          onOpenClause={(cid) =>
            router.push(`/contracts/${id}/clauses/${cid}`)
          }
        />
      )}
    </AppScreen>
  );
}

function CompareBody({
  data,
  onOpenClause,
}: {
  data: ContractDetail;
  onOpenClause: (clauseId: string) => void;
}) {
  const signalClauses = data.clauses.filter((c) => c.signal);

  // 불일치 0건 — 정상 계약 (빈 상태)
  if (signalClauses.length === 0) {
    return (
      <EmptyState
        title="이해하신 내용과 계약서가 같아요"
        big="0건"
        bigEmphasis
        body="확인이 필요한 부분을 찾지 못했어요. 그대로 서명하셔도 좋아요."
        actions={<CTAButton href={`/contracts/${data.summary.id}/signature`}>그대로 서명 진행</CTAButton>}
      />
    );
  }

  // 확인 신호 유형별 집계 (실제 조항 기준)
  const counts = signalClauses.reduce<Record<string, number>>((acc, c) => {
    acc[c.signal] = (acc[c.signal] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-black text-ink">{data.summary.title}</h2>

      {/* 요약 칩 */}
      <div className="flex flex-wrap gap-2 rounded-xl bg-gray100 px-4 py-3">
        {(Object.keys(counts) as ReviewSignalType[]).map((sig) => (
          <span key={sig} className="text-xs text-gray700">
            <b className="text-base text-ink">{counts[sig]}</b>건{" "}
            {SIGNAL_META[sig]}
          </span>
        ))}
      </div>
      <p className="text-xs text-gray500">
        내가 이해한 내용과 계약서가 다른 부분 {signalClauses.length}개를 찾았어요.
      </p>

      {/* 내가 이해한 조건 요약 (사용자 기억) */}
      <LayerBlock layer="understood" label="내가 이해한 조건 요약">
        {data.understood.durationText} · {data.understood.monthlyAmount} ·{" "}
        {data.understood.refundText} · {data.understood.terminationText}
      </LayerBlock>

      {/* 조항 카드 목록 (row 변형) — 탭하면 상세로 */}
      <div className="flex flex-col gap-2">
        {data.clauses.map((c) => (
          <ClauseCard
            key={c.id}
            clause={c}
            variant="row"
            onOpen={() => onOpenClause(c.id)}
          />
        ))}
      </div>
    </div>
  );
}
