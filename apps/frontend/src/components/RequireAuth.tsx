"use client";

/* ===========================================================================
   소유자 화면 접근 가드.
   ---------------------------------------------------------------------------
   세션이 없으면 /login?next=<원래 경로> 로 보낸다. 로그인 후 원래 자리로
   돌아오기 위한 딥링크 보존. 대행사 토큰 화면(/r/*)과 공개 화면(소개·데모)은
   이 가드를 쓰지 않는다.

   preview 우회: 소개 페이지가 실제 화면을 iframe으로 미리보기할 때만 쓴다.
   mock 모드(모든 데이터가 가상)에서 URL에 ?preview=1 이 있을 때에 한해
   로그인 없이 화면을 렌더한다. 실제 백엔드 연결(NEXT_PUBLIC_USE_MOCK=false)
   시 자동으로 꺼지므로 실데이터가 노출되지 않는다.
   =========================================================================== */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useSession } from "@/lib/useSession";
import { isUsingMock } from "@/lib/adapter";

function isPreviewBypass(): boolean {
  if (!isUsingMock || typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("preview") === "1";
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useSession();
  const router = useRouter();
  const pathname = usePathname() ?? "/dashboard";
  // 서버 렌더에서는 항상 false로 시작(hydration 불일치 방지), 마운트 후 URL을 읽는다
  const [preview, setPreview] = useState(false);

  useEffect(() => {
    setPreview(isPreviewBypass());
  }, []);

  useEffect(() => {
    if (!preview && !loading && !session) {
      const next = encodeURIComponent(pathname);
      router.replace(`/login?next=${next}`);
    }
  }, [preview, loading, session, pathname, router]);

  if (preview) return <>{children}</>;

  // localStorage 확인 전 또는 리다이렉트 대기 중 — 콘텐츠를 미리 그리지 않는다
  if (loading || !session) {
    return (
      <p className="py-24 text-center text-sm text-neutral500">불러오는 중…</p>
    );
  }

  return <>{children}</>;
}
