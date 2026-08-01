"use client";

import Link from "next/link";
import { useState } from "react";
import { useSession } from "@/lib/useSession";
import { clearDemoSession } from "@/lib/auth";
import { isUsingDemoOwnerToken, isUsingMock } from "@/lib/adapter";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export function AuthControl() {
  const { session, loading } = useSession();
  const [signingOut, setSigningOut] = useState(false);

  if (loading) return <span className="ml-1 w-16" aria-hidden="true" />;

  if (session?.guest) {
    return (
      <Link
        href="/signup"
        className="ml-1 flex h-9 items-center rounded-lg bg-ink px-4 text-sm font-bold text-white hover:bg-ink/90"
      >
        가입하기
      </Link>
    );
  }

  if (!session) {
    return (
      <Link
        href="/login"
        className="ml-1 rounded-lg px-3 py-2 text-sm font-medium text-neutral500 transition hover:text-ink"
      >
        로그인
      </Link>
    );
  }

  if (isUsingDemoOwnerToken) {
    return <span className="ml-1 px-3 py-2 text-sm font-medium text-neutral500">로컬 인증</span>;
  }

  const handleSignOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    if (isUsingMock) clearDemoSession();
    else await getSupabaseBrowserClient().auth.signOut();
    window.location.assign("/");
  };

  return (
    <button
      type="button"
      onClick={handleSignOut}
      disabled={signingOut}
      className="ml-1 rounded-lg px-3 py-2 text-sm font-medium text-neutral500 transition hover:text-ink disabled:opacity-50"
    >
      {signingOut ? "로그아웃 중" : "로그아웃"}
    </button>
  );
}
