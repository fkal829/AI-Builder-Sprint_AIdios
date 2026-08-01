"use client";

/* 데스크탑 웹 상단 네비게이션 바 — 전체 폭, 중앙 정렬 컨테이너. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "./Logo";
import { DEMO_CONTRACT_ID } from "@/lib/mock";
import { useSession } from "@/lib/useSession";
import { signOut } from "@/lib/auth";

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
  const { session } = useSession();
  const isGuest = session?.guest ?? false;

  const handleSignOut = () => {
    signOut();
    // 전체 네비게이션으로 소개(/)로 이동한다. 이렇게 해야 현재 화면의
    // 접근 가드가 /login 으로 가로채는 경쟁을 피하고 깔끔히 로그아웃된다.
    window.location.assign("/");
  };

  return (
    <>
      {/* 체험(게스트) 안내 바 — 내 계약서를 올리려면 가입해야 함을 상단에 고정 */}
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
        <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-6 lg:px-10">
          <Link href={session ? "/dashboard" : "/"} aria-label="Dandi 홈">
            <Logo />
          </Link>

          <div className="flex items-center gap-2">
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

            {/* 소개는 작업 메뉴와 성격이 달라 구분선 뒤 회색 보조로 분리 */}
            <span className="mx-1 h-5 w-px bg-neutral200" />
            <Link
              href="/"
              className="rounded-lg px-3 py-2 text-sm font-medium text-neutral500 transition hover:text-ink"
            >
              소개
            </Link>

            {/* 계정 영역 — 게스트는 가입 유도, 로그인 사용자는 로그아웃 */}
            {isGuest ? (
              <Link
                href="/signup"
                className="ml-1 flex h-9 items-center rounded-lg bg-ink px-4 text-sm font-bold text-white hover:bg-ink/90"
              >
                가입하기
              </Link>
            ) : (
              <button
                onClick={handleSignOut}
                className="ml-1 rounded-lg px-3 py-2 text-sm font-medium text-neutral500 transition hover:text-ink"
              >
                로그아웃
              </button>
            )}
          </div>
        </div>
      </header>
    </>
  );
}
