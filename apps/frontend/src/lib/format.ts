/** 금액 표시 유틸 — 계산은 코드로 수행(§6.2, LLM 계산 의존 금지) */

/** 6000000 → "600만원", 1200000 → "120만원", 15000 → "1만 5,000원" */
export function won(amount: number | null | undefined): string {
  if (amount == null) return "—";
  if (amount === 0) return "0원";
  const man = Math.floor(amount / 10000);
  const rest = amount % 10000;
  if (man > 0 && rest === 0) return `${man.toLocaleString("ko-KR")}만원`;
  if (man > 0) return `${man.toLocaleString("ko-KR")}만 ${rest.toLocaleString("ko-KR")}원`;
  return `${amount.toLocaleString("ko-KR")}원`;
}

/** 백분율 표시 — 확신도 92% */
export function pct(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}
