"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell, Field } from "@/components/AuthShell";
import { isUsingDemoOwnerToken, isUsingMock } from "@/lib/adapter";
import { signInAsGuest } from "@/lib/auth";
import {
  getSupabaseBrowserClient,
  isSupabaseAuthConfigured,
} from "@/lib/supabase/client";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}

function safeNext(next: string | null): string {
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/dashboard";
}

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const fromGuard = params.has("next");
  const configured = isSupabaseAuthConfigured();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(
    params.get("error") ? "인증을 처리하지 못했습니다. 다시 로그인해 주세요." : "",
  );
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!configured || isUsingMock || isUsingDemoOwnerToken) return;
    setError("");
    setBusy(true);
    try {
      const { error: authError } = await getSupabaseBrowserClient().auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (authError) {
        setError("이메일 또는 비밀번호가 맞지 않습니다. 다시 한 번 확인해주세요.");
        return;
      }
      router.replace(next);
      router.refresh();
    } catch {
      setError("로그인하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setBusy(false);
    }
  };

  const guest = () => {
    if (isUsingMock) signInAsGuest();
    router.replace(next);
  };

  const signupHref = fromGuard ? `/signup?next=${encodeURIComponent(next)}` : "/signup";
  const forgotPasswordHref = fromGuard
    ? `/forgot-password?next=${encodeURIComponent(next)}`
    : "/forgot-password";

  return (
    <AuthShell>
      {fromGuard && (
        <div className="mb-6 rounded-xl border border-brand200 bg-brand50 p-4 text-sm leading-relaxed text-brand800">
          <b className="mb-0.5 block font-bold">로그인이 필요한 화면입니다</b>
          로그인하시면 보시던 곳으로 바로 돌아갑니다. 작성 중이던 조정 요청 내용은 그대로
          남아 있습니다.
        </div>
      )}

      <h2 className="text-[28px] font-black tracking-tight text-ink">다시 오셨네요</h2>
      <p className="mt-2.5 text-[15px] text-neutral500">
        단디계약에 가입한 이메일로 로그인해주세요.
      </p>

      {!isUsingMock && !isUsingDemoOwnerToken && !configured ? (
        <div className="mt-8 rounded-xl bg-neutral100 p-4 text-sm leading-relaxed text-neutral700">
          운영 인증 설정이 없습니다. 배포 환경의 Supabase 공개 설정을 확인해 주세요.
        </div>
      ) : !isUsingMock && !isUsingDemoOwnerToken ? (
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
          />
          <Field
            id="password"
            label="비밀번호"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder="비밀번호를 입력해주세요"
            autoComplete="current-password"
            required
            error={error || undefined}
            right={(
              <Link
                href={forgotPasswordHref}
                className="text-sm font-medium text-brand700 hover:underline"
              >
                비밀번호를 잊으셨나요
              </Link>
            )}
          />
          <button
            type="submit"
            disabled={busy}
            className="flex h-14 w-full items-center justify-center rounded-xl bg-brand800 text-[17px] font-bold text-white transition hover:bg-brand900 disabled:cursor-wait disabled:opacity-50"
          >
            {busy && (
              <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            )}
            {busy ? "확인하는 중" : "로그인"}
          </button>
        </form>
      ) : null}

      {(isUsingMock || isUsingDemoOwnerToken) && (
        <>
          <div className="my-7 flex items-center gap-3.5 text-[13px] text-neutral400">
            <span className="h-px flex-1 bg-neutral200" />체험 모드<span className="h-px flex-1 bg-neutral200" />
          </div>
          <button
            type="button"
            onClick={guest}
            className="flex h-14 w-full items-center justify-center rounded-xl border border-neutral300 bg-white text-[17px] font-bold text-ink transition hover:border-brand200 hover:bg-brand50"
          >
            가입 없이 둘러보기
          </button>
        </>
      )}

      <p className="mt-7 text-center text-[15px] text-neutral500">
        아직 계정이 없으신가요?{" "}
        <Link href={signupHref} className="font-bold text-brand700 hover:underline">
          회원가입
        </Link>
      </p>
    </AuthShell>
  );
}
