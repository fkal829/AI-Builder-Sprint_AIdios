"use client";

/* 데스크탑 웹 상단 네비게이션 바 — develop의 정보 구조와 표현을 유지한다. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Logo } from "./Logo";
import { AuthControl } from "./AuthControl";
import { DEMO_CONTRACT_ID } from "@/lib/mock";
import { useSession } from "@/lib/useSession";
import { adapter, isUsingMock } from "@/lib/adapter";

const navItems = (contractId: string | null) => [
  { key: "contracts", label: "내 계약", href: "/dashboard" },
  {
    key: "manage",
    label: "이행 관리",
    href: "/manage",
  },
  { key: "performance", label: "광고효과", href: "/performance" },
  {
    key: "renewal",
    label: "재계약 검토",
    href: contractId ? `/contracts/${contractId}/renewal` : "/dashboard",
  },
];

function activeKey(pathname: string): string {
  if (pathname.startsWith("/performance")) return "performance";
  if (
    pathname.startsWith("/manage")
    || pathname.includes("/performance")
    || pathname.includes("/obligations")
  ) return "manage";
  if (pathname.includes("/renewal")) return "renewal";
  if (pathname.startsWith("/dashboard") || pathname.startsWith("/contracts")) {
    return "contracts";
  }
  return "";
}

function OwnerNavigation({
  active,
  contractId,
  className,
}: {
  active: string;
  contractId: string | null;
  className: string;
}) {
  return (
    <nav aria-label="주요 메뉴" className={className}>
      {navItems(contractId).map((item) => {
        const on = active === item.key;
        return (
          <Link
            key={item.key}
            href={item.href}
            aria-current={on ? "page" : undefined}
            className={`whitespace-nowrap rounded-lg px-3.5 py-2 text-sm transition ${
              on
                ? "bg-brand50 font-bold text-brand800"
                : "font-medium text-neutral500 hover:text-ink"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function SiteHeader() {
  const pathname = usePathname() ?? "";
  const active = activeKey(pathname);
  const { session } = useSession();
  const isGuest = session?.guest ?? false;
  const routeContractId = pathname.match(/^\/contracts\/([^/]+)/)?.[1] ?? null;
  const [ownerContractId, setOwnerContractId] = useState<string | null>(
    isUsingMock ? DEMO_CONTRACT_ID : null,
  );

  useEffect(() => {
    if (isUsingMock || !session || routeContractId) return;
    let alive = true;
    void adapter.getDashboard()
      .then((dashboard) => {
        if (alive) setOwnerContractId(dashboard.contracts[0]?.id ?? null);
      })
      .catch(() => {
        if (alive) setOwnerContractId(null);
      });
    return () => {
      alive = false;
    };
  }, [routeContractId, session]);

  const contractId = routeContractId ?? ownerContractId;

  return (
    <>
      {isGuest && (
        <div className="bg-brand800 px-6 py-2 text-center text-[13px] text-white">
          체험 중이에요. 내 계약서를 올리려면{" "}
          <Link href="/signup" className="font-bold underline underline-offset-2">
            가입하세요
          </Link>
          . 체험 데이터는 저장되지 않습니다.
        </div>
      )}

      <header className="sticky top-0 z-30 border-b border-neutral200 bg-white">
        <div className="mx-auto max-w-[1200px] px-4 md:px-6 lg:px-10">
          <div className="flex h-14 items-center justify-between gap-3 md:h-16">
            <Link href={session ? "/dashboard" : "/"} aria-label="Dandi 홈">
              <Logo />
            </Link>

            <div className="flex min-w-0 items-center gap-2">
              <OwnerNavigation
                active={active}
                contractId={contractId}
                className="hidden items-center gap-1 md:flex"
              />
              <span className="mx-1 hidden h-5 w-px bg-neutral200 md:block" />
              <Link
                href="/"
                className="hidden rounded-lg px-3 py-2 text-sm font-medium text-neutral500 transition hover:text-ink md:block"
              >
                소개
              </Link>
              <AuthControl />
            </div>
          </div>

          <OwnerNavigation
            active={active}
            contractId={contractId}
            className="no-scrollbar flex items-center gap-1 overflow-x-auto pb-2 md:hidden"
          />
        </div>
      </header>
    </>
  );
}
