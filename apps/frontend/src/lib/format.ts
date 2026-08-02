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

/** 요약 카드용 축약 금액 — 2000000 → "200만 원", 123400000 → "1.23억 원" */
export function compactWon(amount: number): string {
  const compact = compactKoreanNumber(amount);
  return compact.unit ? `${compact.value}${compact.unit} 원` : `${compact.value}원`;
}

/** 요약 카드용 축약 건수 — 125300 → "12.5만", suffix="건"이면 "12.5만 건" */
export function compactCount(value: number, suffix = ""): string {
  const compact = compactKoreanNumber(value);
  if (!suffix) return `${compact.value}${compact.unit}`;
  return compact.unit
    ? `${compact.value}${compact.unit} ${suffix}`
    : `${compact.value}${suffix}`;
}

function compactKoreanNumber(value: number): { value: string; unit: "" | "만" | "억" } {
  const absolute = Math.abs(value);
  const roundedMan = Number((value / 10_000).toFixed(1));
  if (absolute >= 100_000_000 || Math.abs(roundedMan) >= 10_000) {
    return { value: compactDecimal(value / 100_000_000, 2), unit: "억" };
  }
  if (absolute >= 10_000) {
    return { value: compactDecimal(value / 10_000, 1), unit: "만" };
  }
  return { value: value.toLocaleString("ko-KR"), unit: "" };
}

function compactDecimal(value: number, maximumFractionDigits: number): string {
  return value.toLocaleString("ko-KR", {
    maximumFractionDigits,
    minimumFractionDigits: 0,
  });
}

/** 백분율 표시 — 확신도 92% */
export function pct(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}
