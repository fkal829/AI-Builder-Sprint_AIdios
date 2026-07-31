/* ===========================================================================
   조정 요청서 초안 저장 — 뷰어에서 인라인으로 고른 문구/직접수정을 보관.
   목업 단계에서는 localStorage 사용(설문 understood.ts와 동일 패턴).
   요청서 미리보기(/request)에서 이 초안을 우선 사용한다.
   =========================================================================== */
import type { SuggestionChoice } from "./types";

export interface ClauseDraft {
  choice: SuggestionChoice; // 원안수용(ACCEPT) / 절충안(COMPROMISE) / 요청안(REQUEST)
  text: string; // 발송 문구(직접 수정 가능). ACCEPT면 요청서에서 제외.
  origin: "auto" | "manual"; // auto=AI가 고른 초기 조항 / manual=사용자가 직접 추가
  title?: string; // manual 조항 렌더용(초기 조항은 ClauseCard.title 사용)
  docClauseId?: string; // manual 조항이 참조한 원문 조항 id(원문 보기 연동용)
}

/** 조항 id → 초안 */
export type RequestDraft = Record<string, ClauseDraft>;

const storageKey = (contractId: string) => `request:${contractId}`;

export function saveRequestDraft(contractId: string, draft: RequestDraft) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(contractId), JSON.stringify(draft));
  } catch {
    /* 저장 실패는 무시 — /request가 목업으로 폴백 */
  }
}

export function loadRequestDraft(contractId: string): RequestDraft | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(storageKey(contractId));
    return raw ? (JSON.parse(raw) as RequestDraft) : null;
  } catch {
    return null;
  }
}
