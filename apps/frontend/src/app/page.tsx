import Link from "next/link";
import { DEMO_CONTRACT_ID, DEMO_TOKEN } from "@/lib/mock";

/* 데모 런처 — 발표·개발용 진입 인덱스.
   실제 서비스 진입점은 소상공인 대시보드(⓪). */
export default function Home() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <header className="border-b-2 border-ink pb-6">
        <div className="text-[13px] font-medium text-neutral500">
          부산 관광상권 소상공인용 AI 광고대행 계약 CLM
        </div>
        <h1 className="mt-1 text-3xl font-black text-ink">단디계약</h1>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-neutral700">
          읽지 못한 계약을 읽어주고, 하지 못한 말을 대신해준다. 내가 이해한 조건과
          실제 계약서를 AI가 비교하고, 조정 요청을 대신 작성해 전자서명으로
          확정합니다.
        </p>
      </header>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <LaunchCard
          badge="소상공인"
          title="사장님 데모 시작"
          desc="대시보드 → 업로드 → 5문항 → AI 분석 → 조항 조정 → 합의 → 서명 → 산출물 → 재계약"
          href="/dashboard"
          primary
        />
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
        <LaunchCard
          badge="바로가기"
          title="대표 계약 상세"
          desc="광안리 카페 SNS광고 계약 — 분석 결과·조항 카드로 바로 진입"
          href={`/contracts/${DEMO_CONTRACT_ID}`}
          subtle
        />
      </div>

      <p className="mt-10 text-[12px] leading-relaxed text-neutral500">
        모든 데이터는 목업입니다(가상 데이터). 외부 API(Upstage·Solar·모두싸인)는
        Adapter 뒤에 두어 이후 실제 연동으로 전환합니다. &lsquo;지급 조건 충족&rsquo;은
        실제 송금이 아닙니다.
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
  href: string;
  primary?: boolean;
  subtle?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`group block rounded-2xl border-2 p-5 transition hover:-translate-y-0.5 hover:shadow-[0_10px_30px_rgba(42,42,42,0.1)] ${
        primary
          ? "border-ink bg-brand50"
          : subtle
            ? "border-neutral300 bg-white"
            : "border-ink bg-white"
      }`}
    >
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
    </Link>
  );
}
