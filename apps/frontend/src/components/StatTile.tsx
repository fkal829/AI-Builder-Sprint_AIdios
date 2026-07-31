import type { ReactNode } from "react";

/* 대시보드 숫자 타일 (§6.13) — 화려한 차트 대신 숫자 타일 위주.
   emphasis는 채움 무게로 구분한다. 색조로 튀게 하지 않는다. */
export function StatTile({
  value,
  label,
  emphasis,
  size = "sm",
}: {
  value: ReactNode;
  label: string;
  /** 만료 임박 등 강조 — 유일한 솔리드 타일 */
  emphasis?: boolean;
  size?: "sm" | "lg";
}) {
  const pad = size === "lg" ? "px-4 py-5" : "px-3 py-2.5";
  const num = size === "lg" ? "text-3xl" : "text-lg";
  return (
    <div
      className={`card text-center ${pad} ${
        emphasis ? "border-brand200 bg-brand50" : ""
      }`}
    >
      <div
        className={`font-black tabular-nums ${num} ${emphasis ? "text-brand700" : "text-ink"}`}
      >
        {value}
      </div>
      <div className="mt-1 text-[11px] text-neutral500">{label}</div>
    </div>
  );
}

/** 좌우 라벨/값 한 줄 지표 */
export function StatRow({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="card flex items-center justify-between px-5 py-4 text-sm">
      <span className="text-neutral700">{label}</span>
      <span className="font-bold tabular-nums text-ink">{value}</span>
    </div>
  );
}
