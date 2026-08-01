"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { AuthShell, Field } from "@/components/AuthShell";
import { isUsingDemoOwnerToken, isUsingMock } from "@/lib/adapter";
import {
  getSupabaseBrowserClient,
  isSupabaseAuthConfigured,
} from "@/lib/supabase/client";

function safeNextPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/dashboard";
  return value;
}

function ForgotPasswordForm() {
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const loginHref = searchParams.has("next")
    ? `/login?next=${encodeURIComponent(nextPath)}`
    : "/login";
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(
    searchParams.get("error")
      ? "비밀번호 재설정 링크를 처리하지 못했습니다. 새 링크를 요청해 주세요."
      : null,
  );
  const configured = isSupabaseAuthConfigured();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !configured) return;

    setSubmitting(true);
    setError(null);
    const resetUrl = new URL("/reset-password", window.location.origin);
    resetUrl.searchParams.set("next", nextPath);
    const callbackUrl = new URL("/auth/callback", window.location.origin);
    callbackUrl.searchParams.set("flow", "recovery");
    callbackUrl.searchParams.set("next", `${resetUrl.pathname}${resetUrl.search}`);
    const { error: authError } = await getSupabaseBrowserClient().auth.resetPasswordForEmail(
      email.trim(),
      { redirectTo: callbackUrl.toString() },
    );
    setSubmitting(false);

    if (authError) {
      setError("재설정 링크를 보내지 못했습니다. 잠시 후 다시 시도해 주세요.");
      return;
    }
    setSent(true);
  }

  return (
    <AuthShell>
      <h1 className="text-[28px] font-black tracking-tight text-ink">비밀번호 찾기</h1>
      <p className="mt-2.5 text-[15px] leading-relaxed text-neutral500">
        가입한 이메일로 비밀번호 재설정 링크를 보내드립니다.
      </p>

      {isUsingMock || isUsingDemoOwnerToken ? (
        <div className="mt-8 rounded-xl bg-brand50 p-4 text-sm leading-relaxed text-brand900">
          데모 모드에서는 비밀번호 재설정이 필요하지 않습니다.
          <Link href={nextPath} className="ml-1 font-bold underline">계속하기</Link>
        </div>
      ) : !configured ? (
        <div className="mt-8 rounded-xl bg-neutral100 p-4 text-sm leading-relaxed text-neutral700">
          운영 인증 설정이 없습니다. 배포 환경의 Supabase 공개 설정을 확인해 주세요.
        </div>
      ) : sent ? (
        <div
          className="mt-8 rounded-xl bg-brand50 p-4 text-sm leading-relaxed text-brand900"
          aria-live="polite"
        >
          가입 여부와 관계없이 입력하신 주소로 전송을 요청했습니다. 메일이 오면 링크를 열어
          새 비밀번호를 설정해 주세요.
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="mt-8 grid gap-5">
          <Field
            id="email"
            label="이메일"
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="가입한 이메일을 입력하세요"
            autoComplete="email"
            required
            error={error ?? undefined}
          />
          <button
            type="submit"
            disabled={submitting}
            className="flex h-14 w-full items-center justify-center rounded-xl bg-brand800 text-[17px] font-bold text-white transition hover:bg-brand900 disabled:opacity-50"
          >
            {submitting ? "보내는 중" : "재설정 링크 받기"}
          </button>
        </form>
      )}

      <p className="mt-7 text-center text-[15px] text-neutral500">
        비밀번호가 기억나셨나요?{" "}
        <Link href={loginHref} className="font-bold text-brand700 hover:underline">
          로그인
        </Link>
      </p>
    </AuthShell>
  );
}

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ForgotPasswordForm />
    </Suspense>
  );
}
