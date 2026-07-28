import type { ReactNode } from "react";

/* 실패·빈 상태 (설계 원칙 #7) — 판정색 없이 중립적으로 안내. */
export function EmptyState({
  title,
  body,
  big,
  bigEmphasis,
  code,
  actions,
}: {
  title: string;
  body: ReactNode;
  /** 큰 숫자/문구 강조 (예: D+6, 0건) */
  big?: string;
  bigEmphasis?: boolean;
  /** 오류 코드/자리표시 박스 */
  code?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-base font-black text-ink">{title}</h2>
      {big && (
        <div
          className={`rounded-lg px-4 py-3.5 text-center text-3xl font-black ${
            bigEmphasis ? "bg-amber50 text-amber700" : "bg-paper text-gray700"
          }`}
        >
          {big}
        </div>
      )}
      {code && (
        <div className="flex h-24 items-center justify-center rounded-lg border-2 border-dashed border-gray300 text-[11px] text-gray500">
          {code}
        </div>
      )}
      <p className="text-[13px] leading-relaxed text-gray700">{body}</p>
      {actions && <div className="flex flex-col gap-2">{actions}</div>}
    </div>
  );
}
