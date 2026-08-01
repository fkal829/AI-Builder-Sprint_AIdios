"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell, Field } from "@/components/AuthShell";
import { signIn, signInAsGuest, AuthError } from "@/lib/auth";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}

/** next 파라미터가 안전한 내부 경로인지 확인 (오픈 리다이렉트 방지) */
function safeNext(next: string | null): string {
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/dashboard";
}

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const fromGuard = params.has("next");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await signIn(email, password);
      router.replace(next);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "로그인하지 못했습니다. 잠시 후 다시 시도해주세요.");
      setBusy(false);
    }
  };

  const guest = () => {
    signInAsGuest();
    router.replace(next);
  };

  const signupHref = fromGuard ? `/signup?next=${encodeURIComponent(next)}` : "/signup";

  return (
    <AuthShell>
      {fromGuard && (
        <div className="mb-6 rounded-xl border border-brand200 bg-brand50 p-4 text-sm leading-relaxed text-brand800">
          <b className="mb-0.5 block font-bold">로그인이 필요한 화면입니다</b>
          로그인하시면 보시던 곳으로 바로 돌아갑니다. 작성 중이던 조정 요청 내용은 그대로 남아 있습니다.
        </div>
      )}

      <h2 className="text-[28px] font-black tracking-tight text-ink">다시 오셨네요</h2>
      <p className="mt-2.5 text-[15px] text-neutral500">단디계약에 가입한 이메일로 로그인해주세요.</p>

      <form onSubmit={submit} className="mt-8 grid gap-5">
        <Field
          id="email"
          label="이메일"
          type="email"
          value={email}
          onChange={setEmail}
          placeholder="sajang@example.com"
          autoComplete="email"
        />
        <Field
          id="password"
          label="비밀번호"
          type="password"
          value={password}
          onChange={setPassword}
          placeholder="비밀번호를 입력해주세요"
          autoComplete="current-password"
          error={error}
          right={<Link href="#" className="text-sm font-medium text-brand700 hover:underline">비밀번호를 잊으셨나요</Link>}
        />
        <button
          type="submit"
          disabled={busy}
          className="flex h-14 w-full items-center justify-center rounded-xl bg-brand800 text-[17px] font-bold text-white transition hover:bg-brand900 disabled:cursor-wait"
        >
          {busy && <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
          {busy ? "확인하는 중" : "로그인"}
        </button>
      </form>

      <div className="my-7 flex items-center gap-3.5 text-[13px] text-neutral400">
        <span className="h-px flex-1 bg-neutral200" />또는<span className="h-px flex-1 bg-neutral200" />
      </div>
      <button
        onClick={guest}
        className="flex h-14 w-full items-center justify-center rounded-xl border border-neutral300 bg-white text-[17px] font-bold text-ink transition hover:border-brand200 hover:bg-brand50"
      >
        가입 없이 둘러보기
      </button>

      <p className="mt-7 text-center text-[15px] text-neutral500">
        아직 계정이 없으신가요?{" "}
        <Link href={signupHref} className="font-bold text-brand700 hover:underline">회원가입</Link>
      </p>
    </AuthShell>
  );
}
