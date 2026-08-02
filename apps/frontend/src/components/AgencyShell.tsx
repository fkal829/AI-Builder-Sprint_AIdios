/* ===========================================================================
   대행사 공개 화면 셸 — 무가입 · 토큰 접근 (기획안 §5.2, §8).
   데스크탑·모바일 양쪽 지원(반응형 중앙 카드). 계정 유도 없음.
   =========================================================================== */
import type { ReactNode } from "react";
import Link from "next/link";
import { Logo } from "./Logo";

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
    <div className="min-h-dvh bg-white">
      {/* 상단 바 — 로고를 누르면 서비스 소개로 이동 */}
      <div className="border-b border-neutral200 bg-white">
        <div className="mx-auto flex max-w-2xl items-center px-5 py-3">
          <Link href="/" aria-label="단디계약 소개 보기">
            <Logo size={20} />
          </Link>
        </div>
      </div>

      <div className="mx-auto max-w-2xl px-5 py-6">
        {(ownerLabel || subtitle) && (
          <div className="mb-4">
            {ownerLabel && (
              <h1 className="text-lg font-black text-ink">{ownerLabel}</h1>
            )}
            {subtitle && (
              <p className="mt-1 text-[13px] text-neutral500">{subtitle}</p>
            )}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
