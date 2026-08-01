"use client";

/* 소유자 화면 접근 가드 — develop의 딥링크·preview 동작을 유지한다. */
import { useEffect, useSyncExternalStore } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useSession } from "@/lib/useSession";
import { isUsingMock } from "@/lib/adapter";

function isPreviewBypass(): boolean {
  if (!isUsingMock || typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("preview") === "1";
}

const subscribePreview = () => () => {};
const getServerPreview = () => false;

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useSession();
  const router = useRouter();
  const pathname = usePathname() ?? "/dashboard";
  // 최신 develop과 동일하게 서버 렌더에서는 false로 시작해 hydration 불일치를 막는다.
  const preview = useSyncExternalStore(
    subscribePreview,
    isPreviewBypass,
    getServerPreview,
  );

  useEffect(() => {
    if (!preview && !loading && !session) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [preview, loading, session, pathname, router]);

  if (preview) return <>{children}</>;
  if (loading || !session) {
    return <p className="py-24 text-center text-sm text-neutral500">불러오는 중…</p>;
  }
  return <>{children}</>;
}
