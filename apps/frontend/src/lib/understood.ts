/* ===========================================================================
   설문(내가 이해한 조건 5문항) 응답 저장·요약 — 목업 단계에서는 localStorage 사용.
   실제 API 연동 시 이 파일의 read/write만 서버 호출로 교체하면 된다.
   =========================================================================== */
import type { UnderstoodTerm } from "./types";

export type UnderstoodKey = keyof Omit<UnderstoodTerm, "sourceType">;

/** "잘 모르겠다" 계열 응답 — 요약에서 제외한다 (§ 사용자 요청) */
export const UNKNOWN_ANSWER = "잘 기억 안 나요";

/** 문항 key → 요약 표시 라벨 (질문 순서와 동일) */
export const UNDERSTOOD_LABELS: Record<UnderstoodKey, string> = {
  durationText: "계약 기간",
  monthlyAmount: "매달 내는 금액",
  totalAmount: "총 계약금액",
  refundText: "환불 조건",
  terminationText: "중도 해지",
};

const KEY_ORDER = Object.keys(UNDERSTOOD_LABELS) as UnderstoodKey[];

const storageKey = (contractId: string) => `understood:${contractId}`;

/** 설문 응답 저장 (문항 key → 사용자가 고르거나 직접 입력한 값) */
export function saveUnderstood(
  contractId: string,
  answers: Partial<Record<UnderstoodKey, string>>,
) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(contractId), JSON.stringify(answers));
  } catch {
    /* 저장 실패는 무시 — 요약은 목업 값으로 폴백 */
  }
}

/** 저장된 설문 응답 읽기. 없으면 null */
export function loadUnderstood(
  contractId: string,
): Partial<Record<UnderstoodKey, string>> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(storageKey(contractId));
    return raw ? (JSON.parse(raw) as Partial<Record<UnderstoodKey, string>>) : null;
  } catch {
    return null;
  }
}

/** 응답이 "모르겠다" 또는 공란인지 */
function isUnknown(value: string | undefined): boolean {
  return !value || value.trim() === "" || value.trim() === UNKNOWN_ANSWER;
}

export interface UnderstoodSummary {
  /** 표시할 항목 (모르겠다·공란 제외) */
  items: { key: UnderstoodKey; label: string; value: string }[];
  /** 5문항 전부 모르겠다/공란 */
  allUnknown: boolean;
}

/** 설문 응답 → 요약 (모르겠다 항목 제외, 전부 모르면 allUnknown) */
export function summarizeUnderstood(
  answers: Partial<Record<UnderstoodKey, string>> | null,
): UnderstoodSummary {
  if (!answers) return { items: [], allUnknown: false };
  const items = KEY_ORDER.filter((k) => !isUnknown(answers[k])).map((k) => ({
    key: k,
    label: UNDERSTOOD_LABELS[k],
    value: (answers[k] as string).trim(),
  }));
  const answeredCount = KEY_ORDER.filter((k) => answers[k] !== undefined).length;
  return { items, allUnknown: answeredCount > 0 && items.length === 0 };
}
