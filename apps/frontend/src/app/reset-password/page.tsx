"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { AuthShell, Field } from "@/components/AuthShell";
import { isUsingDemoOwnerToken, isUsingMock } from "@/lib/adapter";
import { getPasswordValidationError, PASSWORD_MIN_LENGTH } from "@/lib/authPassword";
import {
  getSupabaseBrowserClient,
  isSupabaseAuthConfigured,
} from "@/lib/supabase/client";

function safeNextPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/dashboard";
  return value;
}

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const configured = isSupabaseAuthConfigured();
  const shouldCheckSession = !isUsingMock && !isUsingDemoOwnerToken && configured;
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [checkingSession, setCheckingSession] = useState(shouldCheckSession);
  const [hasSession, setHasSession] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!shouldCheckSession) return;

    let alive = true;
    void getSupabaseBrowserClient().auth.getSession().then(({ data }) => {
      if (!alive) return;
      setHasSession(Boolean(data.session));
      setCheckingSession(false);
    });
    return () => {
      alive = false;
    };
  }, [shouldCheckSession]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextPasswordError = getPasswordValidationError(password);
    const nextConfirmError = password === confirmPassword
      ? null
      : "비밀번호가 서로 다릅니다.";
    setPasswordError(nextPasswordError);
    setConfirmError(nextConfirmError);
    setFormError(null);
    if (nextPasswordError || nextConfirmError || !hasSession) return;

    setSubmitting(true);
    const { error: authError } = await getSupabaseBrowserClient().auth.updateUser({ password });
    setSubmitting(false);
    if (authError) {
      setFormError("비밀번호를 변경하지 못했습니다. 재설정 링크를 다시 요청해 주세요.");
      return;
    }
    router.replace(nextPath);
    router.refresh();
  }

  return (
    <AuthShell>
      <h1 className="text-[28px] font-black tracking-tight text-ink">새 비밀번호 설정</h1>
      <p className="mt-2.5 text-[15px] leading-relaxed text-neutral500">
        앞으로 로그인할 때 사용할 새 비밀번호를 입력해 주세요.
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
      ) : checkingSession ? (
        <p className="mt-8 text-sm text-neutral500">재설정 링크를 확인하는 중…</p>
      ) : !hasSession ? (
        <div className="mt-8 rounded-xl bg-neutral100 p-4 text-sm leading-relaxed text-neutral700">
          재설정 링크가 만료됐거나 올바르지 않습니다.
          <Link href="/forgot-password" className="ml-1 font-bold text-brand700 underline">
            새 링크 받기
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="mt-8 grid gap-5">
          <Field
            id="password"
            label="새 비밀번호"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder={`${PASSWORD_MIN_LENGTH}자 이상`}
            autoComplete="new-password"
            minLength={PASSWORD_MIN_LENGTH}
            required
            help={`비밀번호는 ${PASSWORD_MIN_LENGTH}자 이상으로 만들어 주세요.`}
            error={passwordError ?? undefined}
          />
          <Field
            id="confirm-password"
            label="새 비밀번호 다시 입력"
            type="password"
            value={confirmPassword}
            onChange={setConfirmPassword}
            placeholder="같은 비밀번호를 한 번 더 입력하세요"
            autoComplete="new-password"
            minLength={PASSWORD_MIN_LENGTH}
            required
            error={confirmError ?? undefined}
          />
          {formError && (
            <p className="text-[13px] font-bold text-brand800" aria-live="polite">
              {formError}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="flex h-14 w-full items-center justify-center rounded-xl bg-brand800 text-[17px] font-bold text-white transition hover:bg-brand900 disabled:opacity-50"
          >
            {submitting ? "변경하는 중" : "비밀번호 변경"}
          </button>
        </form>
      )}
    </AuthShell>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
