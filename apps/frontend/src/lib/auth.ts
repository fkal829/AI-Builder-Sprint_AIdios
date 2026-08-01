"use client";

/* ===========================================================================
   인증 (목업) — 로컬 세션.
   ---------------------------------------------------------------------------
   현재는 백엔드 인증(Supabase Auth) 연동 전이라 localStorage로만 동작한다.
   화면·폼·가드는 이 모듈 하나에만 의존하므로, 나중에 실제 연동 시
   signUp/signIn/signOut 세 함수의 내부만 API 명세(Bearer 토큰 발급)에 맞춰
   교체하면 된다. 컴포넌트는 손대지 않는다.

   저장 키:
   - dandi:session  현재 로그인 세션(이메일 또는 게스트)
   - dandi:users    가입한 이메일→비밀번호(목업 검증용, 데모 한정)
   =========================================================================== */

const SESSION_KEY = "dandi:session";
const USERS_KEY = "dandi:users";

/** 로그아웃 시 비우는 계정 귀속 데이터 키 프리픽스 — 계정 간 혼입 방지 */
const OWNED_PREFIXES = ["understood:", "request:", "dandi:last-link:"];

export type Session = {
  email: string;
  /** 가입 없이 둘러보기(체험) 세션 */
  guest: boolean;
};

/** 세션 변경을 같은 탭 안에서 구독하기 위한 이벤트 이름 */
const SESSION_EVENT = "dandi:session-change";

export class AuthError extends Error {}

function readSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function writeSession(session: Session | null): void {
  if (typeof window === "undefined") return;
  if (session) {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } else {
    window.localStorage.removeItem(SESSION_KEY);
  }
  window.dispatchEvent(new Event(SESSION_EVENT));
}

function readUsers(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(USERS_KEY);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function writeUsers(users: Record<string, string>): void {
  window.localStorage.setItem(USERS_KEY, JSON.stringify(users));
}

/** 계정에 귀속된 localStorage 데이터 정리 (로그아웃 시) */
function purgeOwnedData(): void {
  if (typeof window === "undefined") return;
  const toRemove: string[] = [];
  for (let i = 0; i < window.localStorage.length; i++) {
    const key = window.localStorage.key(i);
    if (key && OWNED_PREFIXES.some((p) => key.startsWith(p))) toRemove.push(key);
  }
  toRemove.forEach((k) => window.localStorage.removeItem(k));
}

/** 목업 지연 — 실제 네트워크처럼 잠깐 기다린다 */
const delay = (ms = 320) => new Promise((r) => setTimeout(r, ms));

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(email: string): boolean {
  return EMAIL_RE.test(email.trim());
}

/**
 * 회원가입 (목업).
 * 실제 연동 시: POST 가입 → Bearer 토큰 저장으로 교체.
 */
export async function signUp(email: string, password: string): Promise<Session> {
  await delay();
  const id = email.trim().toLowerCase();
  if (!isValidEmail(id)) {
    throw new AuthError("이메일 주소를 다시 한 번 확인해주세요.");
  }
  if (password.length < 8) {
    throw new AuthError("비밀번호는 8자 이상으로 만들어주세요.");
  }
  const users = readUsers();
  if (users[id]) {
    throw new AuthError("이미 가입된 이메일이에요. 로그인해주세요.");
  }
  users[id] = password;
  writeUsers(users);
  const session: Session = { email: id, guest: false };
  writeSession(session);
  return session;
}

/**
 * 로그인 (목업).
 * 실제 연동 시: 인증 요청 → Bearer 토큰 저장으로 교체.
 */
export async function signIn(email: string, password: string): Promise<Session> {
  await delay();
  const id = email.trim().toLowerCase();
  const users = readUsers();
  if (!users[id] || users[id] !== password) {
    throw new AuthError("이메일 또는 비밀번호가 맞지 않습니다. 다시 한 번 확인해주세요.");
  }
  const session: Session = { email: id, guest: false };
  writeSession(session);
  return session;
}

/** 가입 없이 둘러보기 — 목업 데이터로 대시보드까지 진입시키는 체험 세션 */
export function signInAsGuest(): Session {
  const session: Session = { email: "체험 중", guest: true };
  writeSession(session);
  return session;
}

/** 로그아웃 — 세션 제거 + 계정 귀속 데이터 정리 */
export function signOut(): void {
  purgeOwnedData();
  writeSession(null);
}

export function getSession(): Session | null {
  return readSession();
}

export { SESSION_EVENT };
