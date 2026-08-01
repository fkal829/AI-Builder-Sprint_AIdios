/* ===========================================================================
   대행사 전달 링크 보관 — 링크는 한 번 만들면 같은 요청서로 다시 만들 수 없으므로
   브라우저에 남겨 두고 요청서 미리보기·응답 대기 화면에서 다시 열람·복사한다.
   목업 단계에서는 localStorage 사용(requestDraft.ts와 동일 패턴).
   =========================================================================== */

export interface PublicLink {
  publicUrl: string;
  expiresAt: string;
}

const storageKey = (contractId: string) => `dandi:last-link:${contractId}`;

export function savePublicLink(contractId: string, link: PublicLink) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(contractId), JSON.stringify(link));
  } catch {
    /* 저장 실패는 무시 — 이번 화면에서는 state로 계속 보인다 */
  }
}

export function loadPublicLink(contractId: string): PublicLink | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(storageKey(contractId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PublicLink>;
    if (typeof parsed.publicUrl !== "string" || typeof parsed.expiresAt !== "string") {
      return null;
    }
    const expiresAt = Date.parse(parsed.expiresAt);
    if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      window.localStorage.removeItem(storageKey(contractId));
      return null;
    }
    return { publicUrl: parsed.publicUrl, expiresAt: parsed.expiresAt };
  } catch {
    return null;
  }
}

/** 목업 어댑터는 "/r/..." 상대 경로를 돌려준다. 그대로 복사하면 받는 쪽에서 열 수
    없으므로 복사·표시 전에 절대 URL로 맞춘다(라이브는 이미 절대 URL이라 그대로). */
export function absolutePublicUrl(url: string): string {
  try {
    if (typeof window === "undefined" && url.startsWith("/") && !url.startsWith("//")) {
      return url;
    }
    const parsed = new URL(
      url,
      typeof window === "undefined" ? undefined : window.location.origin,
    );
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "";
  } catch {
    return "";
  }
}
