"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell, Field } from "@/components/AuthShell";
import { signUp, AuthError } from "@/lib/auth";

export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <SignupInner />
    </Suspense>
  );
}

function safeNext(next: string | null): string {
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/dashboard";
}

function SignupInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setConfirmError("");
    if (password !== confirm) {
      setConfirmError("비밀번호가 서로 다릅니다. 다시 한 번 확인해주세요.");
      return;
    }
    if (!agree) {
      setError("이용약관과 개인정보처리방침에 동의해주세요.");
      return;
    }
    setBusy(true);
    try {
      await signUp(email, password);
      router.replace(next);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "가입하지 못했습니다. 잠시 후 다시 시도해주세요.");
      setBusy(false);
    }
  };

  const loginHref = params.has("next") ? `/login?next=${encodeURIComponent(next)}` : "/login";

  return (
    <AuthShell>
      <h2 className="text-[28px] font-black tracking-tight text-ink">단디계약 시작하기</h2>
      <p className="mt-2.5 text-[15px] text-neutral500">이메일과 비밀번호만 있으면 됩니다. 1분이면 끝납니다.</p>

      <form onSubmit={submit} className="mt-8 grid gap-5">
        <Field
          id="email"
          label="이메일"
          type="email"
          value={email}
          onChange={setEmail}
          placeholder="sajang@example.com"
          autoComplete="email"
          help="비밀번호를 잊으셨을 때 이 주소로 안내를 보내드립니다."
        />
        <Field
          id="password"
          label="비밀번호"
          type="password"
          value={password}
          onChange={setPassword}
          placeholder="8자 이상"
          autoComplete="new-password"
          help="영문과 숫자를 섞어 8자 이상으로 만들어주세요."
        />
        <Field
          id="confirm"
          label="비밀번호 다시 입력"
          type="password"
          value={confirm}
          onChange={setConfirm}
          placeholder="같은 비밀번호를 한 번 더"
          autoComplete="new-password"
          error={confirmError}
        />

        <label className="flex items-start gap-2.5 text-sm leading-relaxed text-neutral700">
          <input
            type="checkbox"
            checked={agree}
            onChange={(e) => setAgree(e.target.checked)}
            className="mt-0.5 h-5 w-5 flex-none accent-brand700"
          />
          <span>
            <Link href="#" className="text-brand700 underline">이용약관</Link>과{" "}
            <Link href="#" className="text-brand700 underline">개인정보처리방침</Link>에 동의합니다.
          </span>
        </label>

        {error && <p className="text-[13px] font-bold text-brand800">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="flex h-14 w-full items-center justify-center rounded-xl bg-brand800 text-[17px] font-bold text-white transition hover:bg-brand900 disabled:cursor-wait"
        >
          {busy && <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
          {busy ? "가입하는 중" : "가입하고 시작하기"}
        </button>
      </form>

      <p className="mt-7 text-center text-[15px] text-neutral500">
        이미 계정이 있으신가요?{" "}
        <Link href={loginHref} className="font-bold text-brand700 hover:underline">로그인</Link>
      </p>
    </AuthShell>
  );
}
