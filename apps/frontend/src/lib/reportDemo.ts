"use client";

/* 데모용 — 리포트 저장 여부를 계약별 관리 화면과 전체 광고효과 모아보기가 함께 본다.
   실제로는 사장님이 확인한 지표를 백엔드가 저장하고 두 화면 모두 API로 읽는다.
   목업 단계에서 "저장하면 모아보기에 쌓인다"를 보이기 위한 세션 한정 플래그. */

import { useSyncExternalStore } from "react";

const KEY = "dandi:demo:saved-report";

export type SavedReport = {
  contractId: string;
  /** 리포트가 다루는 기간 — "2026년 7월" */
  period: string;
  impressions: number;
  reactions: number;
  posts: number;
  savedAt: string;
};

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/* useSyncExternalStore는 스냅샷이 매번 같은 참조여야 하므로 원본 문자열로 캐시한다 */
let cachedRaw: string | null = null;
let cachedValue: SavedReport | null = null;

function getSnapshot(): SavedReport | null {
  const raw = sessionStorage.getItem(KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedValue = raw ? (JSON.parse(raw) as SavedReport) : null;
  }
  return cachedValue;
}

export function writeSavedReport(report: SavedReport) {
  sessionStorage.setItem(KEY, JSON.stringify(report));
  listeners.forEach((listener) => listener());
}

export function clearSavedReport() {
  sessionStorage.removeItem(KEY);
  listeners.forEach((listener) => listener());
}

/** 저장된 리포트 — sessionStorage는 서버에 없으므로 SSR에서는 null로 그린다. */
export function useSavedReport(): SavedReport | null {
  return useSyncExternalStore(subscribe, getSnapshot, () => null);
}
