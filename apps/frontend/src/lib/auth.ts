"use client";

const SESSION_KEY = "dandi:demo-session";
const SESSION_EVENT = "dandi:demo-session-change";
const OWNED_PREFIXES = ["understood:", "request:", "dandi:last-link:"];

export type Session = {
  email: string;
  guest: boolean;
};

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function signInAsGuest(): Session {
  const session: Session = { email: "체험 중", guest: true };
  if (typeof window !== "undefined") {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    window.dispatchEvent(new Event(SESSION_EVENT));
  }
  return session;
}

export function clearDemoSession(): void {
  if (typeof window === "undefined") return;
  const toRemove: string[] = [SESSION_KEY];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index);
    if (key && OWNED_PREFIXES.some((prefix) => key.startsWith(prefix))) toRemove.push(key);
  }
  toRemove.forEach((key) => window.localStorage.removeItem(key));
  window.dispatchEvent(new Event(SESSION_EVENT));
}

export { SESSION_EVENT };
