"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { Logo } from "@/components/Logo";
import {
  getSupabaseBrowserClient,
  isSupabaseAuthConfigured,
} from "@/lib/supabase/client";
import { isUsingDemoOwnerToken, isUsingMock } from "@/lib/adapter";

function LoginForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(
    searchParams.get("error") ? "로그인 링크를 확인하지 못했습니다. 새 링크를 요청해 주세요." : null,
  );
  const configured = isSupabaseAuthConfigured();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !configured) return;

    setSubmitting(true);
    setError(null);
    const callbackUrl = new URL("/auth/callback", window.location.origin);
    callbackUrl.searchParams.set("next", "/dashboard");
    const { error: authError } = await getSupabaseBrowserClient().auth.signInWithOtp({
      email: email.trim(),
      options: {
        emailRedirectTo: callbackUrl.toString(),
        shouldCreateUser: false,
      },
    });
    setSubmitting(false);

    if (authError) {
      setError("로그인 링크를 보내지 못했습니다. 가입된 이메일인지 확인해 주세요.");
      return;
    }
    setSent(true);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-6 py-12">
      <section className="card w-full p-7 sm:p-8">
        <Link href="/" aria-label="단디계약 홈" className="inline-flex">
          <Logo />
        </Link>
        <h1 className="mt-8 text-2xl font-black text-ink">사장님 로그인</h1>
        <p className="mt-2 text-sm leading-relaxed text-neutral500">
          가입한 이메일로 일회용 로그인 링크를 보내드려요. 링크는 직접 확인해야 하며,
          계약이나 요청을 자동으로 실행하지 않습니다.
        </p>

        {isUsingMock || isUsingDemoOwnerToken ? (
          <div className="mt-6 rounded-xl bg-brand50 p-4 text-sm leading-relaxed text-brand900">
            현재는 {isUsingMock ? "목업 모드" : "로컬 API 인증 모드"}입니다. 로그인 없이
            데모 화면을 확인할 수 있어요.
            <Link href="/dashboard" className="ml-1 font-bold underline">대시보드로 이동</Link>
          </div>
        ) : !configured ? (
          <div className="mt-6 rounded-xl bg-neutral100 p-4 text-sm leading-relaxed text-neutral700">
            운영 인증 설정이 없습니다. 배포 환경의 Supabase 공개 설정을 확인해 주세요.
          </div>
        ) : sent ? (
          <div className="mt-6 rounded-xl bg-brand50 p-4 text-sm leading-relaxed text-brand900">
            로그인 링크를 보냈습니다. 이메일에서 링크를 열어 계속해 주세요.
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mt-6">
            <label htmlFor="email" className="block text-sm font-bold text-neutral700">
              이메일
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="가입한 이메일을 입력하세요"
              className="mt-2 w-full rounded-xl border border-neutral300 px-4 py-3 text-sm outline-none focus:border-brand500"
            />
            {error ? <p role="alert" className="mt-3 text-sm text-neutral700">{error}</p> : null}
            <button
              type="submit"
              disabled={submitting}
              className="mt-5 w-full rounded-xl bg-brand800 px-4 py-3 text-sm font-bold text-white hover:bg-brand900 disabled:opacity-50"
            >
              {submitting ? "보내는 중" : "로그인 링크 받기"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
