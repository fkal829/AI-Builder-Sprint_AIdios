"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { isUsingDemoOwnerToken, isUsingMock } from "@/lib/adapter";
import {
  getSupabaseBrowserClient,
  isSupabaseAuthConfigured,
} from "@/lib/supabase/client";

function isPreviewBypass(): boolean {
  if (!isUsingMock || typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("preview") === "1";
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() ?? "/dashboard";
  const bypass = isUsingMock || isUsingDemoOwnerToken || isPreviewBypass();
  const configured = isSupabaseAuthConfigured();
  const authRequired = !bypass && configured;
  const [loading, setLoading] = useState(authRequired);
  const [signedIn, setSignedIn] = useState(bypass);

  useEffect(() => {
    if (!authRequired) return;

    let alive = true;
    const supabase = getSupabaseBrowserClient();
    void supabase.auth.getSession().then(({ data }) => {
      if (!alive) return;
      setSignedIn(Boolean(data.session));
      setLoading(false);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!alive) return;
      setSignedIn(Boolean(session));
      setLoading(false);
    });
    return () => {
      alive = false;
      data.subscription.unsubscribe();
    };
  }, [authRequired]);

  useEffect(() => {
    if (!bypass && !loading && !signedIn) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [bypass, loading, pathname, router, signedIn]);

  if (bypass) return <>{children}</>;
  if (loading || !signedIn) {
    return <p className="py-24 text-center text-sm text-neutral500">불러오는 중…</p>;
  }
  return <>{children}</>;
}
