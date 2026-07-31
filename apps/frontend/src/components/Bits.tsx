import type { ReactNode } from "react";

/** 5문항 등 진행 표시 점선 바 */
export function ProgressDots({ total, current }: { total: number; current: number }) {
  return (
    <div className="flex gap-1">
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className={`h-1 flex-1 rounded-full ${
            i < current ? "bg-brand700" : "bg-neutral200"
          }`}
        />
      ))}
    </div>
  );
}

/** 흰 카드 섹션 */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-neutral200 bg-white p-4 ${className}`}>
      {children}
    </div>
  );
}

/** 섹션 제목 */
export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-[13px] font-bold text-neutral700">{children}</h2>
  );
}

/** '지급 조건 충족 ≠ 실제 송금' 등 고지 문구 (설계 원칙 #8) */
export function Disclaimer({ children }: { children: ReactNode }) {
  return (
    <p className="border-t border-dashed border-neutral300 pt-2 text-[10px] leading-relaxed text-neutral500">
      {children}
    </p>
  );
}
