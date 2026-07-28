import type { ReactNode } from "react";

/* 대시보드 숫자 타일 (§6.13) — 화려한 차트 대신 숫자 타일 위주. */
export function StatTile({
  value,
  label,
  emphasis,
  size = "sm",
}: {
  value: ReactNode;
  label: string;
  /** 만료 임박 등 강조(앰버) */
  emphasis?: boolean;
  size?: "sm" | "lg";
}) {
  const pad = size === "lg" ? "px-4 py-5" : "px-3 py-2.5";
  const num = size === "lg" ? "text-3xl" : "text-lg";
  return (
    <div
      className={`rounded-2xl text-center ${pad} ${
        emphasis ? "bg-amber50 ring-1 ring-amber200" : "bg-gray100"
      }`}
    >
      <div className={`font-black ${num} ${emphasis ? "text-amber700" : "text-ink"}`}>
        {value}
      </div>
      <div className="mt-1 text-[11px] text-gray500">{label}</div>
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
    <div className="flex items-center justify-between rounded-xl bg-white px-5 py-4 text-sm ring-1 ring-gray200">
      <span className="text-gray700">{label}</span>
      <span className="font-bold text-ink">{value}</span>
    </div>
  );
}
