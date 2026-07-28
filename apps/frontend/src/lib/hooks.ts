"use client";

import { useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "error"; data: null; error: string }
  | { status: "ready"; data: T; error: null };

/** Adapter 호출을 로딩/에러/성공 상태로 감싸는 최소 훅 */
export function useAsync<T>(
  fetcher: () => Promise<T>,
  deps: React.DependencyList = [],
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({
    status: "loading",
    data: null,
    error: null,
  });

  useEffect(() => {
    let alive = true;
    setState({ status: "loading", data: null, error: null });
    fetcher()
      .then((data) => {
        if (alive) setState({ status: "ready", data, error: null });
      })
      .catch((e: unknown) => {
        if (alive)
          setState({
            status: "error",
            data: null,
            error: e instanceof Error ? e.message : "unknown error",
          });
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
