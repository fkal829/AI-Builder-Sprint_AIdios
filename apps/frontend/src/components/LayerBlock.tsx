import type { ReactNode } from "react";

/* ===========================================================================
   층위 블록 — 설계 원칙 #2 "다섯 항목 분리"를 강제하는 프리미티브.
   원문(사실) / 내가 이해한 조건 / AI 해석(추정) / 공식 기준·근거 / 조정 요청안(미확정)
   을 색·배경·라벨로 항상 구분. 같은 톤으로 섞지 않음. 빨강 없음.
   =========================================================================== */
export type Layer = "original" | "understood" | "ai" | "official" | "request";

const LAYER_STYLE: Record<
  Layer,
  { wrap: string; label: string; defaultLabel: string }
> = {
  // 원문(사실) — 흰 배경, 회색 테두리
  original: {
    wrap: "bg-white border border-gray300",
    label: "text-gray500",
    defaultLabel: "원문",
  },
  // 내가 이해한 조건 — 회색톤(paper), 라벨로만 구분
  understood: {
    wrap: "bg-paper",
    label: "text-gray700",
    defaultLabel: "내가 이해한 조건",
  },
  // AI 해석(추정) — amber50 점선. 확신도 병기.
  ai: {
    wrap: "bg-amber50 border border-dashed border-amber400",
    label: "text-amber700",
    defaultLabel: "AI가 본 차이 · 추정",
  },
  // 공식 기준·근거 — 회색톤(paper), 라벨로만 구분(제3의 참고정보)
  official: {
    wrap: "bg-paper",
    label: "text-gray700",
    defaultLabel: "공식 기준 · 내부 검토 규칙",
  },
  // 조정 요청안(미확정) — amber100, 아직 확정 아님을 라벨로 명시
  request: {
    wrap: "bg-amber100 border border-amber600",
    label: "text-amber800",
    defaultLabel: "조정 요청안 · 미확정",
  },
};

export function LayerBlock({
  layer,
  label,
  meta,
  children,
}: {
  layer: Layer;
  /** 라벨 텍스트 override (기본값은 층위별 기본 라벨) */
  label?: ReactNode;
  /** 라벨 우측 보조 정보 (예: 확신도 92%) */
  meta?: ReactNode;
  children: ReactNode;
}) {
  const s = LAYER_STYLE[layer];
  return (
    <div className={`rounded-lg px-3.5 py-2.5 ${s.wrap}`}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className={`text-[10px] font-bold ${s.label}`}>
          {label ?? s.defaultLabel}
        </span>
        {meta && <span className="text-[10px] font-bold text-amber700">{meta}</span>}
      </div>
      <div className="text-sm leading-relaxed text-ink">{children}</div>
    </div>
  );
}
