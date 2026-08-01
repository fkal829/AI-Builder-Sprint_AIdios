"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell, Field } from "@/components/AuthShell";
import { isUsingDemoOwnerToken, isUsingMock } from "@/lib/adapter";
import { getSignupErrorMessage } from "@/lib/authErrors";
import { getPasswordValidationError, PASSWORD_MIN_LENGTH } from "@/lib/authPassword";
import {
  getSupabaseBrowserClient,
  isSupabaseAuthConfigured,
} from "@/lib/supabase/client";

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
  const configured = isSupabaseAuthConfigured();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState(
    params.get("error") ? "이메일 확인 링크를 처리하지 못했습니다. 다시 가입해 주세요." : "",
  );
  const [passwordError, setPasswordError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [confirmationSent, setConfirmationSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    const nextPasswordError = getPasswordValidationError(password) ?? "";
    const nextConfirmError = password === confirm
      ? ""
      : "비밀번호가 서로 다릅니다. 다시 한 번 확인해주세요.";
    setPasswordError(nextPasswordError);
    setConfirmError(nextConfirmError);
    if (nextPasswordError || nextConfirmError) return;
    if (!agree) {
      setError("이용약관과 개인정보처리방침에 동의해주세요.");
      return;
    }
    if (!configured || isUsingMock || isUsingDemoOwnerToken) return;

    setBusy(true);
    try {
      const callbackUrl = new URL("/auth/callback", window.location.origin);
      callbackUrl.searchParams.set("flow", "signup");
      callbackUrl.searchParams.set("next", next);
      const { data, error: authError } = await getSupabaseBrowserClient().auth.signUp({
        email: email.trim(),
        password,
        options: { emailRedirectTo: callbackUrl.toString() },
      });
      if (authError) {
        setError(getSignupErrorMessage(authError));
        return;
      }
      if (data.session) {
        router.replace(next);
        router.refresh();
        return;
      }
      setConfirmationSent(true);
    } catch {
      setError("인증 서버에 연결하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  };

  const loginHref = params.has("next") ? `/login?next=${encodeURIComponent(next)}` : "/login";

  return (
    <AuthShell>
      <h2 className="text-[28px] font-black tracking-tight text-ink">단디계약 시작하기</h2>
      <p className="mt-2.5 text-[15px] text-neutral500">
        이메일과 비밀번호만 있으면 됩니다. 1분이면 끝납니다.
      </p>

      {isUsingMock || isUsingDemoOwnerToken ? (
        <div className="mt-8 rounded-xl bg-brand50 p-4 text-sm leading-relaxed text-brand900">
          현재는 {isUsingMock ? "목업 모드" : "로컬 API 인증 모드"}입니다. 회원가입 없이
          데모 화면을 확인할 수 있어요.
          <Link href={next} className="ml-1 font-bold underline">계속하기</Link>
        </div>
      ) : !configured ? (
        <div className="mt-8 rounded-xl bg-neutral100 p-4 text-sm leading-relaxed text-neutral700">
          운영 인증 설정이 없습니다. 배포 환경의 Supabase 공개 설정을 확인해 주세요.
        </div>
      ) : confirmationSent ? (
        <div
          className="mt-8 rounded-xl bg-brand50 p-4 text-sm leading-relaxed text-brand900"
          aria-live="polite"
        >
          확인 메일을 보냈습니다. 이메일 주소를 확인하면 가입이 완료됩니다.
        </div>
      ) : (
        <form onSubmit={submit} className="mt-8 grid gap-5">
          <Field
            id="email"
            label="이메일"
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="sajang@example.com"
            autoComplete="email"
            required
            help="비밀번호를 잊으셨을 때 이 주소로 안내를 보내드립니다."
          />
          <Field
            id="password"
            label="비밀번호"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder={`${PASSWORD_MIN_LENGTH}자 이상`}
            autoComplete="new-password"
            minLength={PASSWORD_MIN_LENGTH}
            required
            help={`비밀번호는 ${PASSWORD_MIN_LENGTH}자 이상으로 만들어주세요.`}
            error={passwordError || undefined}
          />
          <Field
            id="confirm"
            label="비밀번호 다시 입력"
            type="password"
            value={confirm}
            onChange={setConfirm}
            placeholder="같은 비밀번호를 한 번 더"
            autoComplete="new-password"
            minLength={PASSWORD_MIN_LENGTH}
            required
            error={confirmError || undefined}
          />

          <label className="flex items-start gap-2.5 text-sm leading-relaxed text-neutral700">
            <input
              type="checkbox"
              checked={agree}
              onChange={(event) => setAgree(event.target.checked)}
              className="mt-0.5 h-5 w-5 flex-none accent-brand700"
            />
            <span>
              <Link href="#" className="text-brand700 underline">이용약관</Link>과{" "}
              <Link href="#" className="text-brand700 underline">개인정보처리방침</Link>에
              동의합니다.
            </span>
          </label>

          {error && (
            <p className="text-[13px] font-bold text-brand800" aria-live="polite">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="flex h-14 w-full items-center justify-center rounded-xl bg-brand800 text-[17px] font-bold text-white transition hover:bg-brand900 disabled:cursor-wait disabled:opacity-50"
          >
            {busy && (
              <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            )}
            {busy ? "가입하는 중" : "가입하고 시작하기"}
          </button>
        </form>
      )}

      <p className="mt-7 text-center text-[15px] text-neutral500">
        이미 계정이 있으신가요?{" "}
        <Link href={loginHref} className="font-bold text-brand700 hover:underline">
          로그인
        </Link>
      </p>
    </AuthShell>
  );
}
