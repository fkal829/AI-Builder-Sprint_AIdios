"use client";

/* ===========================================================================
   조항 카드 — 핵심 재사용 컴포넌트 (기획안 §6.5, 와이어프레임 2번)
   props.variant 로 두 변형을 제어:
     - "row"    : 목록 요약 행 (8상태)
     - "detail" : 상세 패널 (6구성 + 층위 분리)
   =========================================================================== */
import { Badge } from "./Badge";
import { LayerBlock } from "./LayerBlock";
import { SourceLink } from "./SourceLink";
import { CLAUSE_STATE_META, SIGNAL_META, toneStyle } from "@/lib/status";
import { pct } from "@/lib/format";
import type { ClauseCard as ClauseCardData, SuggestionChoice } from "@/lib/types";

export function ClauseCard(props: {
  clause: ClauseCardData;
  variant: "row" | "detail";
  /** row: 클릭 시 상세 이동 */
  onOpen?: () => void;
  /** detail: 현재 선택된 문구 (제어형) */
  selectedChoice?: SuggestionChoice | null;
  /** detail: 문구 선택 콜백. 없으면 읽기 전용(선택 비활성) */
  onSelectChoice?: (choice: SuggestionChoice) => void;
  /** detail: 대행사 응답 블록 표시 여부 */
  showAgencyResponse?: boolean;
}) {
  return props.variant === "row" ? (
    <ClauseRow {...props} />
  ) : (
    <ClauseDetail {...props} />
  );
}

/* --------------------------------- 목록 요약 행 --------------------------------- */
function ClauseRow({
  clause,
  onOpen,
}: {
  clause: ClauseCardData;
  onOpen?: () => void;
}) {
  const meta = CLAUSE_STATE_META[clause.state];
  const tone = toneStyle(meta.tone);
  const Comp = onOpen ? "button" : "div";
  return (
    <Comp
      onClick={onOpen}
      className={`flex w-full items-center gap-3 rounded-lg border-2 px-4 py-3 text-left transition ${tone.card} ${
        onOpen ? "hover:brightness-[0.98] active:scale-[0.995]" : ""
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-bold text-ink">{clause.title}</div>
        <div className="mt-0.5 text-[11px] text-neutral500">
          {SIGNAL_META[clause.signal]}
          {clause.understood ? ` · 이해: ${clause.understood}` : ""}
        </div>
      </div>
      <Badge label={meta.label} tone={meta.tone} icon={meta.icon} size="sm" />
    </Comp>
  );
}

/* --------------------------------- 상세 패널 (6구성) --------------------------------- */
function ClauseDetail({
  clause,
  selectedChoice,
  onSelectChoice,
  showAgencyResponse,
}: {
  clause: ClauseCardData;
  selectedChoice?: SuggestionChoice | null;
  onSelectChoice?: (choice: SuggestionChoice) => void;
  showAgencyResponse?: boolean;
}) {
  const meta = CLAUSE_STATE_META[clause.state];
  const selected = selectedChoice ?? clause.userChoice;

  return (
    <div className="overflow-hidden rounded-xl border-2 border-ink bg-white">
      {/* 헤더 */}
      <div className="flex items-center justify-between gap-2 border-b-2 border-ink bg-brand200 px-5 py-3.5">
        <h3 className="text-[15px] font-black text-ink">{clause.title}</h3>
        <Badge label={meta.label} tone={meta.tone} icon={meta.icon} size="sm" />
      </div>

      <div className="flex flex-col gap-3 px-5 py-4">
        {/* ① 원문 (사실) */}
        <LayerBlock
          layer="original"
          label={clause.original.page > 0
            ? `① 원문 · 계약서 ${clause.original.page}페이지`
            : "① 원문 근거 미확인"}
        >
          “{clause.original.text}”
          {clause.original.page > 0 && (
            <div className="mt-1.5">
              <SourceLink source={clause.original} />
            </div>
          )}
        </LayerBlock>

        {/* ② 내가 이해한 조건 */}
        {clause.understood && (
          <LayerBlock layer="understood" label="② 내가 이해한 조건">
            {clause.understood}
          </LayerBlock>
        )}

        {/* ③ AI 쉬운 설명 (추정) + 확신도 */}
        <LayerBlock
          layer="ai"
          label="③ 무엇이 다른지 쉬운 설명"
          meta={`확신도 ${pct(clause.confidence)}`}
        >
          {clause.aiExplanation}
        </LayerBlock>

        {/* ④ 공식 기준·근거 (참고) */}
        {clause.officialBasis && (
          <LayerBlock layer="official" label="④ 공식 기준 · 내부 검토 규칙">
            {clause.officialBasis}
          </LayerBlock>
        )}

        {/* ⑤ 선택 가능한 문구 3종 */}
        <div>
          <div className="mb-2 text-[10px] font-bold text-neutral700">
            ⑤ 선택 가능한 문구
          </div>
          <div className="flex flex-col gap-2">
            {clause.suggestions.map((s) => {
              const isSel = selected === s.choice;
              const clickable = !!onSelectChoice;
              return (
                <button
                  key={s.choice}
                  type="button"
                  disabled={!clickable}
                  onClick={() => onSelectChoice?.(s.choice)}
                  className={`rounded-lg border px-3.5 py-2.5 text-left text-[13px] transition ${
                    isSel
                      ? "border-2 border-brand700 bg-brand50 font-bold"
                      : "border-neutral300 bg-white"
                  } ${clickable ? "cursor-pointer hover:border-brand400" : "cursor-default"}`}
                >
                  <span className="text-neutral500">{s.label}</span> — {s.text}
                  {isSel && <span className="ml-1 text-brand700">✓ 선택됨</span>}
                </button>
              );
            })}
          </div>
        </div>

        {/* 대행사 응답 (선택) */}
        {showAgencyResponse && clause.agencyResponse && (
          <div className="rounded-lg border border-neutral300 bg-subtle px-3.5 py-2.5">
            <div className="mb-1 text-[10px] font-bold text-neutral700">대행사 응답</div>
            <AgencyResponseLine clause={clause} />
          </div>
        )}

        {/* ⑥ AI 한계 고지 */}
        <p className="border-t border-dashed border-neutral300 pt-2.5 text-[11px] text-neutral500">
          ⑥ AI는 계약서와 답변만 근거로 판단합니다. 실제 법적 효력은 다를 수 있습니다.
        </p>
      </div>
    </div>
  );
}

function AgencyResponseLine({ clause }: { clause: ClauseCardData }) {
  const r = clause.agencyResponse!;
  if (r.decision === "ACCEPT")
    return <p className="text-[13px] text-ink">수락했어요.</p>;
  if (r.decision === "REJECT")
    return (
      <p className="text-[13px] text-ink">
        거절 · <span className="text-neutral500">{r.reason}</span>
      </p>
    );
  return (
    <p className="text-[13px] text-ink">
      역제안 <span className="font-bold text-brand700">{r.counterText}</span>
      {r.reason && <span className="text-neutral500"> · {r.reason}</span>}
    </p>
  );
}
