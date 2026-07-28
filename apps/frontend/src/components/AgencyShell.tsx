/* ===========================================================================
   대행사 공개 화면 셸 — 무가입 · 토큰 접근 (기획안 §5.2, §8).
   데스크탑·모바일 양쪽 지원(반응형 중앙 카드). 계정 유도 없음.
   =========================================================================== */
import type { ReactNode } from "react";

export function AgencyShell({
  ownerLabel,
  subtitle,
  children,
}: {
  /** 상단 컨텍스트 (예: 광안리 카페 사장님이 요청) */
  ownerLabel?: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-paper">
      {/* 무가입 안내 바 */}
      <div className="border-b border-gray200 bg-white">
        <div className="mx-auto flex max-w-2xl items-center justify-between px-5 py-3">
          <span className="text-sm font-black text-ink">안심홍보계약</span>
          <span className="rounded-full bg-gray100 px-2.5 py-1 text-[11px] font-medium text-gray700">
            회원가입 없이 · 토큰 접근
          </span>
        </div>
      </div>

      <div className="mx-auto max-w-2xl px-5 py-6">
        {(ownerLabel || subtitle) && (
          <div className="mb-4">
            {ownerLabel && (
              <h1 className="text-lg font-black text-ink">{ownerLabel}</h1>
            )}
            {subtitle && (
              <p className="mt-1 text-[13px] text-gray500">{subtitle}</p>
            )}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
