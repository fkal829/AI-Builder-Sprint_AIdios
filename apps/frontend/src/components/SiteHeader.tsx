"use client";

/* 데스크탑 웹 상단 네비게이션 바 — 전체 폭, 중앙 정렬 컨테이너. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "./Logo";
import { AuthControl } from "./AuthControl";
import { DEMO_CONTRACT_ID } from "@/lib/mock";

const NAV = [
  { key: "contracts", label: "내 계약", href: "/dashboard" },
  {
    key: "obligations",
    label: "이행 관리",
    href: `/contracts/${DEMO_CONTRACT_ID}/obligations`,
  },
  {
    key: "renewal",
    label: "재계약 검토",
    href: `/contracts/${DEMO_CONTRACT_ID}/renewal`,
  },
];

function activeKey(pathname: string): string {
  if (pathname.includes("/obligations")) return "obligations";
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
          <AuthControl />
        </nav>
      </div>
    </header>
  );
}
