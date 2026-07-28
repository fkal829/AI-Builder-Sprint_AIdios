"use client";

/* ===========================================================================
   소상공인 화면 셸 — 데스크탑 웹 기준. 전체 폭 상단 네비 + 중앙 정렬 컨테이너.
   size로 콘텐츠 폭 제어(sm: 폼, md: 일반, wide: 대시보드). CTA는 인라인 배치.
   =========================================================================== */
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { SiteHeader } from "./SiteHeader";

const MAXW = {
  sm: "max-w-[520px]",
  md: "max-w-[780px]",
  wide: "max-w-[1120px]",
} as const;

export function AppScreen({
  title,
  step,
  backHref,
  onBack,
  right,
  footer,
  size = "md",
  wide,
  children,
}: {
  title?: string;
  step?: string;
  backHref?: string;
  onBack?: () => void;
  right?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "wide";
  /** 하위호환: wide=true → size "wide" */
  wide?: boolean;
  children: ReactNode;
}) {
  const router = useRouter();
  const showBack = !!backHref || !!onBack;
  const handleBack = () => {
    if (onBack) onBack();
    else if (backHref) router.push(backHref);
    else router.back();
  };
  const max = wide ? MAXW.wide : MAXW[size];

  return (
    <div className="min-h-dvh bg-paper">
      <SiteHeader />

      <div className={`mx-auto w-full ${max} px-6 py-8 lg:px-10 lg:py-10`}>
        {showBack && (
          <button
            onClick={handleBack}
            className="mb-4 inline-flex items-center gap-1 text-[13px] font-medium text-gray500 hover:text-ink"
          >
            <span className="text-base">‹</span> 뒤로
          </button>
        )}

        {(title || step || right) && (
          <div className="mb-6 flex items-baseline justify-between gap-4">
            {title && (
              <h1 className="text-2xl font-black tracking-tight text-ink">
                {title}
              </h1>
            )}
            {(step || right) && (
              <div className="flex-none text-[13px] font-medium text-gray500">
                {right ?? step}
              </div>
            )}
          </div>
        )}

        {children}

        {footer && (
          <div className="mt-8 max-w-[440px] border-t border-gray200 pt-5">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/** 기본 CTA 버튼 — 높이 48px */
export function CTAButton({
  children,
  onClick,
  href,
  variant = "primary",
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  href?: string;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
}) {
  const base =
    "flex h-12 w-full items-center justify-center rounded-lg text-[15px] font-bold transition disabled:opacity-40";
  const styles = {
    primary: "bg-ink text-white hover:bg-ink/90",
    secondary: "border-2 border-ink bg-white text-ink hover:bg-paper",
    ghost: "border border-gray300 bg-white text-gray500 hover:bg-paper",
  }[variant];

  if (href && !disabled) {
    return (
      <a href={href} className={`${base} ${styles}`}>
        {children}
      </a>
    );
  }
  return (
    <button onClick={onClick} disabled={disabled} className={`${base} ${styles}`}>
      {children}
    </button>
  );
}
