"use client";

/* 로그인·회원가입 공통 셸 — 좌 남색 브랜드 패널 + 우 폼. 모바일은 폼만 1단. */
import Link from "next/link";
import type { ReactNode } from "react";
import { Logo } from "./Logo";

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[0.85fr_1fr]">
      {/* 좌 : 브랜드 패널 (모바일 숨김) */}
      <aside className="hidden flex-col justify-between bg-brand900 p-14 text-white lg:flex">
        <Link href="/" aria-label="단디계약 소개로" className="w-fit">
          <span className="flex items-center gap-[11px]">
            <span className="text-[23px] font-bold tracking-[0.01em] text-white">Dandi</span>
          </span>
        </Link>

        <div>
          <h1 className="max-w-[14ch] text-4xl font-black leading-snug tracking-tight">
            계약서는 사장님만 봅니다.
          </h1>
          <p className="mt-5 max-w-sm text-base leading-loose text-white/70">
            올리신 계약서는 사장님 계정 안에만 남습니다. 대행사에게는 사장님이 만든 요청서 링크만 전달됩니다.
          </p>
          <ul className="mt-10 grid gap-3.5">
            {[
              "사장님 이메일과 비밀번호로 계정을 보호합니다.",
              "비밀번호나 운영 비밀키를 단디계약 DB에 저장하지 않습니다.",
              "계약서를 올리기 전까지는 아무것도 저장되지 않습니다.",
            ].map((t, i) => (
              <li key={i} className="relative pl-6 text-sm leading-relaxed text-white/80">
                <span className="absolute left-0 top-2 h-2 w-2 rounded-full bg-brand400" />
                {t}
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="text-xs leading-loose text-white/45">
            단디계약은 법률 자문을 제공하지 않으며 계약의 위법 여부를 판정하지 않습니다.
          </p>
          <div className="mt-4 flex gap-5 text-xs text-white/60">
            <Link href="/terms" className="hover:text-white">이용약관</Link>
            <Link href="/privacy" className="hover:text-white">개인정보처리방침</Link>
          </div>
        </div>
      </aside>

      {/* 우 : 폼 */}
      <main className="flex flex-col px-6 py-10">
        <div className="flex justify-between">
          {/* 모바일에서만 로고 노출 (좌 패널이 숨겨지므로) */}
          <span className="lg:hidden">
            <Logo size={20} />
          </span>
          <Link href="/" className="ml-auto text-sm text-neutral500 hover:text-ink">
            소개 페이지로 돌아가기
          </Link>
        </div>
        <div className="mx-auto flex w-full max-w-[420px] flex-1 flex-col justify-center py-8">
          {children}
        </div>
        {/* 좌 브랜드 패널이 숨는 모바일에서도 약관·방침에 닿을 수 있게 한다 */}
        <div className="flex justify-center gap-5 text-xs text-neutral500 lg:hidden">
          <Link href="/terms" className="hover:text-ink">이용약관</Link>
          <Link href="/privacy" className="hover:text-ink">개인정보처리방침</Link>
        </div>
      </main>
    </div>
  );
}

/* 폼 필드 — 라벨 위, 도움말/오류 아래. 자리표시자를 라벨로 쓰지 않는다. */
export function Field({
  id,
  label,
  type = "text",
  value,
  onChange,
  placeholder,
  autoComplete,
  required = false,
  minLength,
  help,
  error,
  right,
}: {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoComplete?: string;
  required?: boolean;
  minLength?: number;
  help?: string;
  error?: string;
  right?: ReactNode;
}) {
  const invalid = !!error;
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="text-sm font-bold text-neutral700">{label}</label>
        {right}
      </div>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        required={required}
        minLength={minLength}
        aria-invalid={invalid}
        aria-describedby={invalid ? `${id}-err` : help ? `${id}-help` : undefined}
        className={`w-full rounded-xl border px-4 text-base text-ink transition placeholder:text-neutral400 focus:outline-none ${
          invalid
            ? "border-brand700 bg-brand50 focus:ring-2 focus:ring-brand200"
            : "border-neutral300 hover:border-neutral400 focus:border-brand500 focus:ring-2 focus:ring-brand100"
        }`}
        style={{ height: 52 }}
      />
      {invalid ? (
        <p id={`${id}-err`} className="text-[13px] font-bold text-brand800">{error}</p>
      ) : help ? (
        <p id={`${id}-help`} className="text-[13px] text-neutral500">{help}</p>
      ) : null}
    </div>
  );
}
