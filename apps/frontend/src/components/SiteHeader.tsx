"use client";

/* 데스크탑 웹 상단 네비게이션 바 — 전체 폭, 중앙 정렬 컨테이너. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "./Logo";
import { DEMO_CONTRACT_ID } from "@/lib/mock";

const NAV = [
  { key: "contracts", label: "내 계약", href: "/dashboard" },
  {
    key: "manage",
    label: "이행 관리",
    href: `/contracts/${DEMO_CONTRACT_ID}/performance`,
  },
  // 광고효과는 계약 하나에 묶이지 않으므로 전역 경로를 쓴다.
  // 성격이 이어지는 '이행 관리' 바로 옆에 둔다.
  { key: "performance", label: "광고효과", href: "/performance" },
  {
    key: "renewal",
    label: "재계약 검토",
    href: `/contracts/${DEMO_CONTRACT_ID}/renewal`,
  },
];

function activeKey(pathname: string): string {
  if (pathname.startsWith("/performance")) return "performance";
  // 계약별 관리 화면(/contracts/{id}/performance)은 '이행 관리'로 표시
  if (pathname.includes("/performance")) return "manage";
  if (pathname.includes("/renewal")) return "renewal";
  if (pathname.startsWith("/dashboard") || pathname.startsWith("/contracts"))
    return "contracts";
  return "";
}

export function SiteHeader() {
  const pathname = usePathname() ?? "";
  const active = activeKey(pathname);

  return (
    <header className="sticky top-0 z-30 border-b border-neutral200 bg-white">
      <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-6 lg:px-10">
        <Link href="/dashboard" aria-label="Dandi 홈">
          <Logo />
        </Link>

        <nav className="flex items-center gap-1">
          {NAV.map((it) => {
            const on = active === it.key;
            return (
              <Link
                key={it.key}
                href={it.href}
                className={`rounded-lg px-3.5 py-2 text-sm transition ${
                  on
                    ? "bg-brand50 font-bold text-brand800"
                    : "font-medium text-neutral500 hover:text-ink"
                }`}
              >
                {it.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
