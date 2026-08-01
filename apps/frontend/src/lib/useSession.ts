"use client";

import { useEffect, useState } from "react";
import { getSession, SESSION_EVENT, type Session } from "./auth";

export type SessionState = {
  session: Session | null;
  /** localStorage를 아직 읽기 전(첫 클라이언트 렌더) */
  loading: boolean;
};

/**
 * 현재 로그인 세션을 구독한다.
 * 서버 렌더에서는 항상 loading=true로 시작하고, 마운트 후 localStorage를 읽는다.
 * 같은 탭의 로그인/로그아웃(커스텀 이벤트)과 다른 탭(storage 이벤트) 모두 반영한다.
 */
export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({
    session: null,
    loading: true,
  });

  useEffect(() => {
    const sync = () => setState({ session: getSession(), loading: false });
    sync();
    window.addEventListener(SESSION_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(SESSION_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return state;
}
