"use client";

import { useEffect, useState } from "react";
import { isUsingDemoOwnerToken, isUsingMock } from "./adapter";
import { getSession, SESSION_EVENT, type Session } from "./auth";
import {
  getSupabaseBrowserClient,
  isSupabaseAuthConfigured,
} from "./supabase/client";

export type SessionState = {
  session: Session | null;
  loading: boolean;
};

export function useSession(): SessionState {
  const configured = isSupabaseAuthConfigured();
  const [state, setState] = useState<SessionState>(() => {
    if (isUsingDemoOwnerToken) {
      return { session: { email: "로컬 인증", guest: false }, loading: false };
    }
    if (!isUsingMock && !configured) return { session: null, loading: false };
    return { session: null, loading: true };
  });

  useEffect(() => {
    if (isUsingMock) {
      const sync = () => setState({ session: getSession(), loading: false });
      const timer = window.setTimeout(sync, 0);
      window.addEventListener(SESSION_EVENT, sync);
      window.addEventListener("storage", sync);
      return () => {
        window.clearTimeout(timer);
        window.removeEventListener(SESSION_EVENT, sync);
        window.removeEventListener("storage", sync);
      };
    }

    if (isUsingDemoOwnerToken) return;

    if (!configured) return;

    let alive = true;
    const supabase = getSupabaseBrowserClient();
    const update = (email: string | undefined) => {
      if (!alive) return;
      setState({
        session: email ? { email, guest: false } : null,
        loading: false,
      });
    };
    void supabase.auth.getSession().then(({ data }) => update(data.session?.user.email));
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      update(session?.user.email);
    });
    return () => {
      alive = false;
      data.subscription.unsubscribe();
    };
  }, [configured]);

  return state;
}
