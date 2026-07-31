"use client";

/* 데스크탑 웹 상단 네비게이션 바 — 전체 폭, 중앙 정렬 컨테이너. */
import Link from "next/link";
import { usePathname } from "next/navigation";
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
    <header className="sticky top-0 z-30 border-b border-gray200 bg-paper/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-6 lg:px-10">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-[15px] font-bold text-white">
            ✓
          </span>
          <span className="text-[19px] font-black tracking-tight text-ink">
            단디계약
          </span>
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
                    ? "bg-gray100 font-bold text-ink"
                    : "font-medium text-gray500 hover:text-ink"
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
