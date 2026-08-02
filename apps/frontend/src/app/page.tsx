"use client";

/* ===========================================================================
   소개(랜딩) — 서비스 공개 진입점.
   ---------------------------------------------------------------------------
   흰 바탕 · 잉크 검정 · 하늘색 포인트. 그라데이션·빨강 없음(앱 원칙).
   섹션마다 레이아웃을 달리해 반복 인상을 피한다. 데스크탑 우선 + 반응형.
   세션이 있으면 CTA를 '내 계약 보기'로 바꾼다.
   =========================================================================== */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Logo } from "@/components/Logo";
import { useSession } from "@/lib/useSession";
import { signInAsGuest } from "@/lib/auth";
import { isUsingMock } from "@/lib/adapter";
import { DEMO_CONTRACT_ID, DEMO_TOKEN } from "@/lib/mock";

export default function LandingPage() {
  const router = useRouter();
  const { session } = useSession();

  const startGuest = () => {
    signInAsGuest();
    router.push("/dashboard");
  };

  return (
    <div className="min-h-dvh bg-white text-ink">
      {/* ── 상단 네비 (공개) ─────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-neutral200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1160px] items-center justify-between px-6 lg:px-8">
          <Link href="#top" aria-label="단디계약">
            <Logo />
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            <a href="#empathy" className="rounded-lg px-3.5 py-2 text-sm font-medium text-neutral500 hover:text-ink">무엇을 하나요</a>
            <a href="#steps" className="rounded-lg px-3.5 py-2 text-sm font-medium text-neutral500 hover:text-ink">사용 방법</a>
            <a href="#faq" className="rounded-lg px-3.5 py-2 text-sm font-medium text-neutral500 hover:text-ink">자주 묻는 질문</a>
          </nav>
          <div className="flex items-center gap-2">
            {session ? (
              <Link href="/dashboard" className="flex h-10 items-center rounded-lg bg-ink px-4 text-sm font-bold text-white hover:bg-ink/90">
                내 계약 보기
              </Link>
            ) : (
              <>
                <Link href="/login" className="rounded-lg px-3 py-2 text-sm font-medium text-neutral500 hover:text-ink">로그인</Link>
                <Link href="/signup" className="flex h-10 items-center rounded-lg bg-ink px-4 text-sm font-bold text-white hover:bg-ink/90">
                  시작하기
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main id="top">
        {/* ── ① 히어로 : 비대칭 분할 ───────────────────────────── */}
        <section className="mx-auto grid max-w-[1160px] items-center gap-12 px-6 py-20 lg:grid-cols-2 lg:gap-16 lg:px-8 lg:py-24">
          <div>
            <h1 className="text-4xl font-black leading-[1.25] tracking-tight text-ink sm:text-5xl">
              광고대행 계약서,<br />혼자 읽지 마세요.
            </h1>
            <p className="mt-6 max-w-md text-lg leading-relaxed text-neutral700">
              계약서에서 확인할 곳을 짚어드리고, 사장님이 하실 말씀을 요청서로 정리해드립니다.
            </p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              {session ? (
                <Link href="/dashboard" className="flex h-14 items-center justify-center rounded-xl bg-ink px-7 text-[17px] font-bold text-white hover:bg-ink/90">
                  내 계약 보기
                </Link>
              ) : (
                <>
                  <Link href="/signup" className="flex h-14 items-center justify-center rounded-xl bg-ink px-7 text-[17px] font-bold text-white hover:bg-ink/90">
                    시작하기
                  </Link>
                  {isUsingMock && (
                    <button onClick={startGuest} className="flex h-14 items-center justify-center rounded-xl border border-neutral300 bg-white px-7 text-[17px] font-bold text-ink transition hover:border-brand200 hover:bg-brand50">
                      가입 없이 둘러보기
                    </button>
                  )}
                </>
              )}
            </div>
            <p className="mt-5 text-sm text-neutral500">
              계약서는 사장님만 볼 수 있습니다. 위법 여부는 판정하지 않습니다.
            </p>
          </div>

          <Preview
            src={`/contracts/${DEMO_CONTRACT_ID}?preview=1`}
            label="계약서 원문(좌) · 분석 결과(우) 2단 뷰어"
            w={1440}
            h={1080}
          />
        </section>

        {/* ── ② 공감 : 세로 편집형 스택 ─────────────────────────── */}
        <section id="empathy" className="border-y border-neutral200 bg-subtle">
          <div className="mx-auto max-w-[1160px] px-6 py-20 lg:px-8 lg:py-24">
            <h2 className="text-3xl font-black tracking-tight text-ink">이런 순간, 한 번쯤 있으셨을 겁니다.</h2>
            <p className="mt-3.5 max-w-2xl text-[17px] text-neutral500">
              단디계약은 계약서를 대신 읽어주는 데서 그치지 않고, 그다음에 무엇을 해야 하는지까지 함께 정리합니다.
            </p>

            <div className="mt-14">
              {EMPATHY.map((it, i) => (
                <div
                  key={i}
                  className={`grid gap-8 border-t border-neutral200 py-9 sm:grid-cols-2 sm:gap-12 ${
                    i === EMPATHY.length - 1 ? "border-b" : ""
                  }`}
                >
                  <p className="text-2xl font-bold leading-snug tracking-tight text-brand800">{it.q}</p>
                  <p className="pt-1 text-base leading-loose text-neutral700">{it.a}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── ③ 사용 방법 : 벤토 2×2 (비대칭) ───────────────────── */}
        <section id="steps" className="mx-auto max-w-[1160px] px-6 py-20 lg:px-8 lg:py-24">
          <h2 className="text-3xl font-black tracking-tight text-ink">네 번이면 끝납니다.</h2>
          <p className="mt-3.5 text-[17px] text-neutral500">처음 쓰시는 분 기준으로 15분 정도 걸립니다.</p>

          <div className="mt-14 grid gap-5">
            <div className="grid gap-5 lg:grid-cols-[1fr_1.45fr]">
              <StepCard
                n={1}
                title="올립니다"
                tint
                slot="계약서 PDF 업로드"
                previewSrc="/contracts/new?preview=1"
              >
                대행사에서 받은 계약서 PDF를 그대로 올립니다. 사진으로 찍은 파일도 됩니다.
              </StepCard>
              <StepCard
                n={2}
                title="다섯 문항에 답합니다"
                slot="계약 이해도 설문 5문항"
                previewSrc="/contracts/new?phase=questions&preview=1"
              >
                총 얼마인지, 언제까지인지, 중간에 그만두면 어떻게 되는지. 모르시면 &lsquo;잘 모르겠다&rsquo;로
                답하셔도 됩니다. 오히려 그게 중요한 신호입니다.
              </StepCard>
            </div>
            <div className="grid gap-5 lg:grid-cols-[1.45fr_1fr]">
              <StepCard
                n={3}
                title="다른 곳을 짚어드립니다"
                slot="확인 필요 조항 강조 + 하단 트레이"
                previewSrc={`/contracts/${DEMO_CONTRACT_ID}?preview=1`}
              >
                사장님이 이해한 조건과 계약서에 적힌 조건을 나란히 놓고 비교합니다. 어긋난 곳마다
                확인 표시가 붙습니다.
              </StepCard>
              <StepCard
                n={4}
                title="요청서를 보냅니다"
                tint
                slot="대행사가 링크를 열면 보이는 화면"
                previewSrc={`/r/${DEMO_TOKEN}`}
              >
                조정 요청서를 만들어 링크로 드립니다. 대행사는 가입 없이 링크만 열면 되고, 보내는 것은
                사장님이 직접 하십니다.
              </StepCard>
            </div>
          </div>
        </section>

        {/* ── ④ 계약 흐름 : 가로 레일 ────────────────────────────── */}
        <section className="border-y border-neutral200 bg-subtle">
          <div className="mx-auto max-w-[1160px] px-6 py-20 lg:px-8 lg:py-24">
            <h2 className="text-3xl font-black tracking-tight text-ink">도장 찍는 날로 끝나지 않습니다.</h2>
            <p className="mt-3.5 max-w-2xl text-[17px] text-neutral500">
              계약이 시작되는 날부터 다시 결정해야 하는 날까지, 같은 자리에 쌓아둡니다.
            </p>

            <div className="mt-14 grid gap-x-0 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
              {FLOW.map((n, i) => (
                <div key={i} className="relative sm:pr-6">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-brand500 bg-white">
                    <span className="h-2 w-2 rounded-full bg-brand500" />
                  </span>
                  <h3 className="mt-5 text-lg font-black tracking-tight text-ink">{n.t}</h3>
                  <p className="mt-2 pr-3 text-[15px] leading-relaxed text-neutral500">{n.d}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── ⑤ 하지 않는 일 : 페이지 유일의 색 블록 ────────────── */}
        <section className="bg-brand900 py-24 text-white lg:py-28">
          <div className="mx-auto max-w-[1160px] px-6 lg:px-8">
            <h2 className="max-w-md text-3xl font-black tracking-tight">저희가 하지 않는 일</h2>
            <p className="mt-3.5 max-w-xl text-[17px] text-white/70">
              할 수 있는 일보다 이쪽을 먼저 말씀드리는 편이 맞다고 생각합니다.
            </p>

            <div className="mt-14">
              {NOTS.map((it, i) => (
                <div
                  key={i}
                  className={`grid gap-8 border-t border-white/15 py-8 sm:grid-cols-[0.9fr_1.4fr] sm:gap-12 ${
                    i === NOTS.length - 1 ? "border-b" : ""
                  }`}
                >
                  <h3 className="text-[22px] font-black tracking-tight text-brand300">{it.h}</h3>
                  <p className="text-base leading-loose text-white/80">{it.b}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── ⑥ 대행사 안내 : 비대칭 2단 ────────────────────────── */}
        <section className="mx-auto grid max-w-[1160px] items-center gap-12 px-6 py-20 lg:grid-cols-2 lg:gap-16 lg:px-8 lg:py-24">
          <div>
            <h2 className="text-3xl font-black tracking-tight text-ink">대행사이신가요?</h2>
            <p className="mt-3.5 max-w-md text-[17px] text-neutral500">
              가입하실 필요 없습니다. 사장님이 보내드린 링크를 열면 요청 내용이 바로 보입니다.
            </p>
          </div>
          <div className="rounded-2xl border border-brand200 bg-brand50 p-8">
            <h3 className="text-[17px] font-black text-ink">링크를 여시면</h3>
            <ul className="mt-4 grid gap-3">
              {AGENCY.map((t, i) => (
                <li key={i} className="relative pl-6 text-[15px] leading-relaxed text-neutral700">
                  <span className="absolute left-0 top-2.5 h-2 w-2 rounded-full bg-brand500" />
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ── ⑦ 자주 묻는 질문 ──────────────────────────────────── */}
        <section id="faq" className="border-t border-neutral200 bg-subtle">
          <div className="mx-auto max-w-[820px] px-6 py-20 lg:py-24">
            <h2 className="text-center text-3xl font-black tracking-tight text-ink">자주 묻는 질문</h2>
            <div className="mt-14">
              {FAQ.map((it, i) => (
                <details key={i} className="group border-t border-neutral200 last:border-b" open={i === 0}>
                  <summary className="flex cursor-pointer list-none items-center justify-between py-6 text-lg font-bold tracking-tight text-ink hover:text-brand700">
                    {it.q}
                    <span className="ml-4 text-2xl font-normal text-neutral400 transition group-open:rotate-45">+</span>
                  </summary>
                  <p className="pb-7 text-base leading-loose text-neutral700">{it.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* ── ⑧ 마무리 CTA ──────────────────────────────────────── */}
        <section className="border-t border-neutral200 bg-subtle">
          <div className="mx-auto max-w-[1160px] px-6 py-20 text-center lg:py-24">
            <h2 className="mx-auto max-w-xl text-3xl font-black tracking-tight text-ink">
              계약서 한 장이면 시작할 수 있습니다.
            </h2>
            <p className="mx-auto mt-3.5 max-w-lg text-[17px] text-neutral500">
              이메일과 비밀번호로 가입하면 계약서를 안전하게 관리할 수 있습니다.
            </p>
            <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
              {session ? (
                <Link href="/dashboard" className="flex h-14 items-center justify-center rounded-xl bg-ink px-7 text-[17px] font-bold text-white hover:bg-ink/90">
                  내 계약 보기
                </Link>
              ) : (
                <>
                  <Link href="/signup" className="flex h-14 items-center justify-center rounded-xl bg-ink px-7 text-[17px] font-bold text-white hover:bg-ink/90">
                    시작하기
                  </Link>
                  {isUsingMock && (
                    <button onClick={startGuest} className="flex h-14 items-center justify-center rounded-xl border border-neutral300 bg-white px-7 text-[17px] font-bold text-ink transition hover:border-brand200 hover:bg-brand50">
                      가입 없이 둘러보기
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </section>
      </main>

      {/* ── 푸터 ──────────────────────────────────────────────── */}
      <footer className="border-t border-neutral200">
        <div className="mx-auto max-w-[1160px] px-6 py-14 lg:px-8">
          <div className="flex flex-wrap items-start justify-between gap-10">
            <div>
              <Logo size={20} />
              <div className="mt-3 text-sm text-neutral500">소상공인 광고대행 계약 관리</div>
            </div>
            <div className="flex flex-wrap gap-6 text-sm text-neutral500">
              <a href="#empathy" className="hover:text-ink">무엇을 하나요</a>
              <a href="#steps" className="hover:text-ink">사용 방법</a>
              <a href="#faq" className="hover:text-ink">자주 묻는 질문</a>
              <Link href="/demo" className="hover:text-ink">화면 둘러보기</Link>
              <Link href="/terms" className="hover:text-ink">이용약관</Link>
              <Link href="/privacy" className="hover:text-ink">개인정보처리방침</Link>
            </div>
          </div>
          <p className="mt-9 max-w-3xl text-[13px] leading-loose text-neutral400">
            단디계약은 법률 자문을 제공하지 않으며, 계약의 위법 여부를 판정하지 않습니다.
            확인이 필요한 부분을 표시하고 사장님의 요청을 정리해 전달하는 것까지가 이 서비스의 역할입니다.
          </p>
        </div>
      </footer>
    </div>
  );
}

/* ── 서브 컴포넌트 ────────────────────────────────────────────── */

/** 예시 화면 자리 — 실제 캡처가 들어갈 위치. 발표용으로 '예시 화면'임을 명시한다. */
function ScreenPlaceholder({ label, className = "" }: { label: string; className?: string }) {
  return (
    <div className={`relative flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-brand300 bg-brand50 p-6 text-center ${className}`}>
      <span className="absolute left-3.5 top-3.5 inline-flex items-center gap-1.5 rounded-full bg-brand800 px-3 py-1 text-[11px] font-bold text-white">
        <span className="h-1.5 w-1.5 rounded-full bg-brand300" />
        예시 화면
      </span>
      <span className="mt-4 text-sm font-bold text-neutral700">{label}</span>
      <span className="text-xs text-neutral500">실제 화면이 이 자리에 들어갑니다</span>
    </div>
  );
}

/**
 * 실제 화면 미리보기 — mock 모드에서 실제 라우트를 iframe으로 축소해 보여준다.
 * iframe은 데스크탑 폭(w×h)으로 렌더한 뒤 컨테이너 폭에 맞춰 비율 축소한다.
 * 클릭은 막고(pointer-events-none) 안내용 배지를 얹는다.
 * mock이 아니거나 src가 없으면 정적 '예시 화면' 자리로 대체한다.
 */
function LivePreview({
  src,
  label,
  w,
  h,
}: {
  src: string;
  label: string;
  w: number;
  h: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setScale(el.clientWidth / w);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [w]);

  return (
    <div
      ref={ref}
      className="relative overflow-hidden rounded-2xl border border-neutral200 bg-white shadow-[0_1px_2px_rgba(16,54,90,0.04)]"
      style={{ aspectRatio: `${w} / ${h}` }}
    >
      <span className="absolute left-3.5 top-3.5 z-10 inline-flex items-center gap-1.5 rounded-full bg-brand800 px-3 py-1 text-[11px] font-bold text-white shadow-sm">
        <span className="h-1.5 w-1.5 rounded-full bg-brand300" />
        예시 화면
      </span>
      {scale > 0 && (
        <iframe
          src={src}
          title={label}
          aria-label={`예시 화면 · ${label}`}
          tabIndex={-1}
          scrolling="no"
          className="pointer-events-none absolute left-0 top-0 origin-top-left border-0"
          style={{ width: w, height: h, transform: `scale(${scale})` }}
        />
      )}
    </div>
  );
}

/** 미리보기 자리 — mock+src면 실제 화면 iframe, 아니면 정적 '예시 화면' */
function Preview({
  src,
  label,
  w,
  h,
  className = "",
}: {
  src: string;
  label: string;
  w: number;
  h: number;
  className?: string;
}) {
  if (isUsingMock) return <LivePreview src={src} label={label} w={w} h={h} />;
  return <ScreenPlaceholder label={label} className={className || "aspect-[4/3]"} />;
}

function StepCard({
  n,
  title,
  children,
  tint,
  slot,
  previewSrc,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
  tint?: boolean;
  slot?: string;
  previewSrc?: string;
}) {
  return (
    <div className={`flex flex-col rounded-2xl border p-8 ${tint ? "border-brand200 bg-brand50" : "border-neutral200 bg-white shadow-[0_1px_2px_rgba(16,54,90,0.04)]"}`}>
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand800 text-sm font-bold text-white">{n}</span>
      <h3 className="mt-4 text-xl font-black tracking-tight text-ink">{title}</h3>
      <p className="mt-2.5 text-[15px] leading-loose text-neutral700">{children}</p>
      {slot &&
        (previewSrc ? (
          <div className="mt-6 flex-1">
            <Preview src={previewSrc} label={slot} w={1440} h={960} />
          </div>
        ) : (
          <ScreenPlaceholder label={slot} className="mt-6 min-h-[200px] flex-1" />
        ))}
    </div>
  );
}

/* ── 콘텐츠 ───────────────────────────────────────────────────── */

const EMPATHY = [
  {
    q: "받아보긴 했는데, 무슨 말인지 모르겠어요.",
    a: "조항을 사장님 말로 풀어 보여드립니다. 금액, 기간, 해지, 자동 갱신처럼 확인이 필요한 곳에는 표시를 남깁니다.",
  },
  {
    q: "이건 좀 아닌 것 같은데, 어떻게 말하죠.",
    a: "바꾸고 싶은 조건을 고르면 요청 문장을 대신 써드립니다. 근거가 되는 조항 번호를 함께 붙여 보내실 수 있습니다.",
  },
  {
    q: "광고가 약속대로 돌아간 건지 모르겠어요.",
    a: "대행사가 보낸 월간 리포트를 올리면 숫자를 정리해 보관합니다. 계약서에 적힌 약속과 나란히 놓고 보실 수 있습니다.",
  },
];

const FLOW = [
  { t: "읽고 조정하기", d: "계약서를 읽고, 바꾸고 싶은 조건을 정리해 요청합니다." },
  { t: "합의하고 서명하기", d: "합의된 내용을 반영한 계약서에 전자서명으로 확정합니다." },
  { t: "기록하기", d: "매달 받은 광고 리포트를 올려두면 숫자가 쌓입니다." },
  { t: "다시 결정하기", d: "자동 갱신일 전에 알려드리고, 지난 기록을 근거로 보여드립니다." },
];

const NOTS = [
  {
    h: "판정하지 않습니다",
    b: "이 조항이 위법인지, 불공정한지 판단하지 않습니다. 확인이 필요해 보이는 곳을 짚어드릴 뿐이고, 결정은 사장님이 하십니다. 법률 자문이 필요하면 변호사를 만나셔야 합니다.",
  },
  {
    h: "측정하지 않습니다",
    b: "광고 성과를 저희가 직접 재지 않습니다. 대행사가 보고한 값을 사장님이 확인하고 고친 뒤에야 기록으로 남깁니다. 확인하지 않은 숫자는 저장하지 않습니다.",
  },
  {
    h: "대신 보내지 않습니다",
    b: "요청서와 링크는 만들어드리지만, 대행사에 전달하는 것은 사장님이 하십니다. 쓰시던 메일이나 메신저를 그대로 쓰시면 됩니다.",
  },
];

const AGENCY = [
  "어떤 조항을 어떻게 바꿔달라는 요청인지 조항별로 확인하실 수 있습니다.",
  "조항마다 수락, 거절, 다른 조건 제안 중에서 고르실 수 있습니다.",
  "회원가입, 앱 설치, 별도 계정 모두 필요하지 않습니다.",
];

const FAQ = [
  {
    q: "올린 계약서는 안전한가요?",
    a: "계약서는 사장님 계정에서만 열립니다. 대행사에게는 조정 요청서만 링크로 전달되고, 계약서 원본 전체가 넘어가지 않습니다. 대행사용 링크에는 만료 시각이 있습니다.",
  },
  {
    q: "변호사가 검토해주는 건가요?",
    a: "아닙니다. 단디계약은 법률 자문을 제공하지 않고, 위법 여부도 판정하지 않습니다. 계약서에서 확인이 필요해 보이는 곳을 짚어드리고, 물어보실 말을 정리해드리는 도구입니다.",
  },
  {
    q: "대행사도 가입해야 하나요?",
    a: "필요 없습니다. 사장님이 만든 링크만 열면 됩니다. 계약을 맺은 뒤의 리포트도 대행사는 하시던 대로 메일이나 메신저로 보내주시면 되고, 그 파일을 사장님이 올리시면 됩니다.",
  },
  {
    q: "계약서 원본을 고쳐주나요?",
    a: "단디계약이 임의로 문서를 고치지 않습니다. 사장님이 고른 조건으로 요청서를 만들고, 양쪽이 합의한 내용만 반영해 서명용 문서를 준비합니다.",
  },
  {
    q: "광고대행 계약이 아니어도 쓸 수 있나요?",
    a: "지금은 소상공인 광고대행 계약에 맞춰져 있습니다. 다른 종류의 계약서는 확인이 필요한 항목이 달라서, 순차적으로 넓혀갈 예정입니다.",
  },
];
