"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  getSupabaseBrowserClient,
  isSupabaseAuthConfigured,
} from "@/lib/supabase/client";
import { isUsingDemoOwnerToken, isUsingMock } from "@/lib/adapter";

export function AuthControl() {
  const router = useRouter();
  const [signedIn, setSignedIn] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const configured = isSupabaseAuthConfigured();

  useEffect(() => {
    if (!configured || isUsingMock || isUsingDemoOwnerToken) return;

    const supabase = getSupabaseBrowserClient();
    void supabase.auth.getUser().then(({ data }) => setSignedIn(Boolean(data.user)));
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setSignedIn(Boolean(session));
    });
    return () => data.subscription.unsubscribe();
  }, [configured]);

  if (isUsingMock || isUsingDemoOwnerToken) {
    return (
      <span className="px-2 text-xs font-bold text-neutral500">
        {isUsingMock ? "데모 모드" : "로컬 인증"}
      </span>
    );
  }

  if (!configured || !signedIn) {
    return (
      <Link
        href="/login"
        className="ml-2 rounded-lg border border-neutral300 px-3 py-2 text-sm font-bold text-neutral700 hover:bg-neutral50"
      >
        로그인
      </Link>
    );
  }

  async function handleSignOut() {
    setSigningOut(true);
    await getSupabaseBrowserClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  return (
    <button
      type="button"
      onClick={handleSignOut}
      disabled={signingOut}
      className="ml-2 rounded-lg border border-neutral300 px-3 py-2 text-sm font-bold text-neutral700 hover:bg-neutral50 disabled:opacity-50"
    >
      {signingOut ? "로그아웃 중" : "로그아웃"}
    </button>
  );
}
