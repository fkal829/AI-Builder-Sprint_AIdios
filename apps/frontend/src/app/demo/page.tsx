"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { DEMO_TOKEN } from "@/lib/mock";
import { signInAsGuest } from "@/lib/auth";
import { isUsingMock } from "@/lib/adapter";

/* 데모 런처 — 발표·개발용 진입 인덱스.
   실제 서비스 진입점은 소개(/)와 로그인. 이 페이지는 무가입 공개 경로로 남겨
   시연 때 각 상태·화면으로 바로 들어가기 위한 것이다.
   소유자 화면은 가드가 걸려 있으므로, '사장님 데모'는 체험 세션을 만든 뒤 이동한다. */
export default function DemoLauncher() {
  const router = useRouter();

  const startOwnerDemo = () => {
    if (!isUsingMock) {
      router.push("/login?next=/dashboard");
      return;
    }
    signInAsGuest();
    router.push("/dashboard");
  };

  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <header className="border-b-2 border-ink pb-6">
        <div className="text-[13px] font-medium text-neutral500">
          부산 관광상권 소상공인용 AI 광고대행 계약 CLM · 데모 런처
        </div>
        <h1 className="mt-1 text-3xl font-black text-ink">단디계약</h1>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-neutral700">
          발표·개발용 진입 인덱스입니다. 소개 페이지는{" "}
          <Link href="/" className="font-bold text-brand700 underline underline-offset-2">
            여기
          </Link>
          에서 볼 수 있어요.
        </p>
      </header>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <button onClick={startOwnerDemo} className="text-left">
          <LaunchCard
            badge="소상공인"
            title="사장님 데모 시작"
            desc="체험 세션으로 대시보드 → 업로드 → 5문항 → AI 분석 → 조항 조정 → 합의 → 서명 → 산출물 → 재계약"
            primary
          />
        </button>
        <LaunchCard
          badge="대행사 · 무가입"
          title="대행사 응답 화면"
          desc="토큰 링크로 조정 요청서를 열람하고 조항별로 수락·거절·역제안"
          href={`/r/${DEMO_TOKEN}`}
        />
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <LaunchCard
          badge="빈 · 실패 상태"
          title="예외 상태 갤러리"
          desc="대행사 무응답 · 전부 거절 · 불일치 0건 · PDF 파싱 실패 · 첫 사용자"
          href="/states"
          subtle
        />
        <button onClick={startOwnerDemo} className="text-left">
          <LaunchCard
            badge="바로가기"
            title="대표 계약 상세"
            desc="광안리 카페 SNS광고 계약 — 분석 결과·조항 카드로 바로 진입"
            subtle
          />
        </button>
      </div>

      <p className="mt-10 text-[12px] leading-relaxed text-neutral500">
        모든 데이터는 목업입니다(가상 데이터). 외부 API(Upstage·Solar·모두싸인)는
        Adapter 뒤에서 mock/live로 분리합니다. &lsquo;지급 조건 충족&rsquo;은 실제 송금이
        아닙니다. 체험 세션은 mock 모드에서만 생성됩니다.
      </p>
    </div>
  );
}

function LaunchCard({
  badge,
  title,
  desc,
  href,
  primary,
  subtle,
}: {
  badge: string;
  title: string;
  desc: string;
  href?: string;
  primary?: boolean;
  subtle?: boolean;
}) {
  const className = `group block h-full rounded-2xl border-2 p-5 transition hover:-translate-y-0.5 hover:shadow-[0_10px_30px_rgba(42,42,42,0.1)] ${
    primary
      ? "border-ink bg-brand50"
      : subtle
        ? "border-neutral300 bg-white"
        : "border-ink bg-white"
  }`;

  const inner = (
    <>
      <span
        className={`inline-block rounded-full px-2.5 py-1 text-[11px] font-bold ${
          primary ? "bg-brand700 text-white" : "bg-neutral100 text-neutral700"
        }`}
      >
        {badge}
      </span>
      <h2 className="mt-3 text-lg font-black text-ink">
        {title}
        <span className="ml-1 inline-block transition group-hover:translate-x-1">
          →
        </span>
      </h2>
      <p className="mt-1.5 text-[13px] leading-relaxed text-neutral500">{desc}</p>
    </>
  );

  if (href) {
    return (
      <Link href={href} className={className}>
        {inner}
      </Link>
    );
  }
  return <div className={className}>{inner}</div>;
}
