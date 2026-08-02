/* ===========================================================================
   약관·방침 공개 문서 셸 — 소개(랜딩)와 같은 흰 바탕·잉크 검정.
   본문은 읽기 좋은 폭으로 고정하고, 조문은 <Article>로 번호를 함께 표시한다.
   =========================================================================== */
import type { ReactNode } from "react";
import Link from "next/link";
import { Logo } from "./Logo";

export function LegalShell({
  title,
  effectiveDate,
  intro,
  children,
}: {
  title: string;
  /** 시행일 — 문서 상단에 표기 */
  effectiveDate: string;
  intro: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-white text-ink">
      <header className="sticky top-0 z-30 border-b border-neutral200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[820px] items-center justify-between px-6">
          <Link href="/" aria-label="단디계약 소개로">
            <Logo />
          </Link>
          <div className="flex items-center gap-5 text-sm text-neutral500">
            <Link href="/terms" className="hover:text-ink">이용약관</Link>
            <Link href="/privacy" className="hover:text-ink">개인정보처리방침</Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[820px] px-6 py-16 lg:py-20">
        <h1 className="text-3xl font-black tracking-tight text-ink">{title}</h1>
        <p className="mt-3 text-sm text-neutral500">시행일 {effectiveDate}</p>

        <div className="mt-6 rounded-xl border border-brand200 bg-brand50 px-5 py-4 text-[13px] leading-relaxed text-brand800">
          이 문서는 AI Builder Sprint 해커톤 출품작 &lsquo;단디계약&rsquo;의 시연용 초안입니다.
          법률 검토를 거치지 않았으며, 실제 서비스 출시 전 변호사 검토를 통해 확정할 예정입니다.
        </div>

        <p className="mt-8 text-[15px] leading-loose text-neutral700">{intro}</p>

        <div className="mt-4">{children}</div>

        <div className="mt-16 border-t border-neutral200 pt-8 text-sm text-neutral500">
          <Link href="/" className="hover:text-ink">← 단디계약 소개로 돌아가기</Link>
        </div>
      </main>
    </div>
  );
}

/** 조문 한 개 — 제목 + 본문(문자열이면 문단, 배열이면 번호 목록) */
export function Article({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-neutral200 py-8">
      <h2 className="text-lg font-black tracking-tight text-ink">{title}</h2>
      <div className="mt-3 flex flex-col gap-2.5 text-[15px] leading-loose text-neutral700">
        {children}
      </div>
    </section>
  );
}

/** 번호가 붙는 항 목록 — ① ② ③ … */
export function Clauses({ items }: { items: string[] }) {
  return (
    <ol className="flex flex-col gap-2.5">
      {items.map((text, i) => (
        <li key={i} className="relative pl-7">
          <span className="absolute left-0 top-0 font-bold text-brand700">
            {CIRCLED[i] ?? `${i + 1}.`}
          </span>
          {text}
        </li>
      ))}
    </ol>
  );
}

const CIRCLED = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫"];
