"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { Card, Disclaimer, SectionTitle } from "@/components/Bits";
import { StatTile } from "@/components/StatTile";
import { LayerBlock } from "@/components/LayerBlock";

/* ⑪ 광고효과 관리 — 화면 목업(기능 미구현).
   대행사에게 받은 리포트를 사장님이 올리면 → 지표를 뽑아 대시보드로 모으고 →
   계약 조건과 어긋나는 부분을 짚어 문의 문안까지 만들어주는 흐름을 보여준다.
   실제 추출은 백엔드(이행/증빙 API + 문서 추출) 연동 후 붙는다.
   데모 전용 데이터라 mock.ts(실 API 응답 모델)와 분리해 이 파일에 둔다. */

const MONTHS = [
  { label: "5월", impressions: 12400, reactions: 486, posts: 4, rate: 3.9 },
  { label: "6월", impressions: 15200, reactions: 612, posts: 4, rate: 4.0 },
  { label: "7월", impressions: 8300, reactions: 240, posts: 2, rate: 2.9 },
];

const TOTAL = { impressions: 35900, reactions: 1338, rate: 3.7, posts: 10 };

const JULY_POSTS = [
  {
    kind: "릴스",
    title: "여름 신메뉴 자몽에이드",
    date: "07-08",
    impressions: 5100,
    likes: 128,
    comments: 14,
    saves: 31,
  },
  {
    kind: "피드",
    title: "테라스 리뉴얼 안내",
    date: "07-19",
    impressions: 3200,
    likes: 52,
    comments: 6,
    saves: 9,
  },
];

/** AI가 리포트에서 읽어낸 값 — 사장님이 확인·수정하는 대상 */
const EXTRACTED = [
  { label: "보고 기간", value: "2026년 7월", confidence: 98 },
  { label: "게시물 수", value: "2건", confidence: 95 },
  { label: "총 노출", value: "8,300", confidence: 92 },
  { label: "총 반응(좋아요+댓글+저장)", value: "240", confidence: 90 },
];

const FINDINGS = [
  {
    title: "약속한 게시물 수보다 적어요",
    body: "계약서 제3조(서비스의 범위)에는 월 4건 게시로 되어 있는데, 7월 리포트에는 2건만 담겨 있어요.",
  },
  {
    title: "반응률이 눈에 띄게 떨어졌어요",
    body: "6월 4.0% → 7월 2.9%로 낮아졌어요. 게시물이 줄어든 것과 관련이 있는지 확인해보면 좋아요.",
  },
];

const INQUIRY =
  "안녕하세요, 7월 광고 리포트 잘 받았습니다. 계약서 제3조에 월 4건 게시로 되어 있는데 이번 달 리포트에는 2건으로 확인되어 문의드립니다. 남은 2건의 진행 일정을 알려주시면 감사하겠습니다.";

type Stage = "idle" | "parsing" | "done";

export default function PerformancePage() {
  const { id } = useParams<{ id: string }>();
  const [stage, setStage] = useState<Stage>("idle");

  const runDemo = () => {
    setStage("parsing");
    window.setTimeout(() => setStage("done"), 900);
  };

  return (
    <AppScreen
      title="광고효과 관리"
      size="wide"
      backHref={`/contracts/${id}/obligations`}
      right={
        <span className="rounded bg-amber200 px-1.5 py-0.5 text-[10px] font-bold text-amber800">
          화면 목업 · 개발 예정
        </span>
      }
      footer={
        <CTAButton href={`/contracts/${id}/renewal`} variant="secondary">
          만료·재계약 검토로
        </CTAButton>
      }
    >
      <div className="flex flex-col gap-5">
        <p className="text-[13px] leading-relaxed text-gray700">
          대행사에게 받은 광고 리포트를 올려두면, 계약에서 약속한 조건대로
          진행되고 있는지 한눈에 확인할 수 있어요.
        </p>

        {/* 계약 단계 ↔ 관리 단계 연결 — 무엇을 근거로 대조하는지 밝힌다 */}
        <Card>
          <p className="text-[12px] leading-relaxed text-gray700">
            <b className="text-ink">계약서를 기준으로 확인해요.</b> 제3조(서비스의
            범위)에 적힌 <b className="text-ink">월 4건 게시</b> 약정과 리포트를
            대조합니다.
          </p>
          <p className="mt-1.5 text-[11px] leading-relaxed text-gray500">
            이 계약에는 성과 보고 조항이 따로 없어요. 조정 요청에 &lsquo;월 1회 성과
            보고&rsquo;를 넣어두면, 다음부터는 받을 지표와 주기가 계약으로 정해져요.
          </p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <a
              href={`/contracts/${id}`}
              className="rounded-lg border border-gray300 bg-white px-3 py-1.5 text-[12px] font-bold text-ink hover:bg-paper"
            >
              계약서에서 보기 →
            </a>
            <a
              href={`/contracts/${id}#req`}
              className="rounded-lg border border-amber400 bg-amber50 px-3 py-1.5 text-[12px] font-bold text-amber700 hover:bg-amber100"
            >
              성과 보고 조항 추가 요청 →
            </a>
          </div>
        </Card>

        <StepFlow stage={stage} />

        {/* ① 리포트 올리기 */}
        <section className="flex flex-col gap-2">
          <SectionTitle>① 대행사 리포트 올리기</SectionTitle>
          <Card>
            {stage === "idle" ? (
              <div className="flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-gray300 bg-paper px-6 py-8 text-center">
                <span className="text-3xl">📄</span>
                <div>
                  <div className="text-[13px] font-bold text-ink">
                    월간 리포트나 인사이트 화면을 올려주세요
                  </div>
                  <div className="mt-1 text-[11px] text-gray500">
                    PDF · 이미지 캡처 모두 괜찮아요
                  </div>
                </div>
                <button
                  onClick={runDemo}
                  className="h-10 rounded-lg bg-ink px-4 text-[13px] font-bold text-white hover:bg-ink/90"
                >
                  샘플 리포트로 살펴보기
                </button>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">📄</span>
                  <div>
                    <div className="text-[13px] font-bold text-ink">
                      브릿지웨이브_7월_광고리포트.pdf
                    </div>
                    <div className="text-[11px] text-gray500">
                      2026-07-31 업로드 · 대행사 제공
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setStage("idle")}
                  className="flex-none rounded-lg border border-gray300 bg-white px-3 py-1.5 text-[12px] font-bold text-gray700 hover:bg-paper"
                >
                  다시 올리기
                </button>
              </div>
            )}
          </Card>
        </section>

        {stage === "parsing" && (
          <p className="py-8 text-center text-sm text-gray500">
            리포트에서 숫자를 읽는 중…
          </p>
        )}

        {stage === "done" && (
          <>
            {/* ② 읽은 내용 확인 */}
            <section className="flex flex-col gap-2">
              <SectionTitle>② 이렇게 읽었어요 — 맞는지 확인해주세요</SectionTitle>
              <Card>
                <LayerBlock layer="ai" label="리포트에서 읽어낸 값 · 추정">
                  <div className="flex flex-col gap-1.5">
                    {EXTRACTED.map((f) => (
                      <div
                        key={f.label}
                        className="flex items-center justify-between gap-3 text-[13px]"
                      >
                        <span className="text-gray700">{f.label}</span>
                        <span className="flex items-center gap-2">
                          <b className="text-ink">{f.value}</b>
                          <span className="text-[10px] font-bold text-amber700">
                            확신도 {f.confidence}%
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                </LayerBlock>
                <div className="mt-3 flex gap-2">
                  <button className="h-10 flex-1 rounded-lg bg-ink text-[13px] font-bold text-white">
                    맞아요, 저장할게요
                  </button>
                  <button className="h-10 flex-1 rounded-lg border border-gray300 bg-white text-[13px] font-bold text-gray700">
                    숫자를 고칠게요
                  </button>
                </div>
                <p className="mt-2 text-[11px] text-gray500">
                  잘못 읽은 숫자가 있으면 직접 고칠 수 있어요. 확인한 값만
                  대시보드에 쌓여요.
                </p>
              </Card>
            </section>

            {/* ③ 대시보드 */}
            <section className="flex flex-col gap-2">
              <SectionTitle>③ 광고효과 한눈에 보기</SectionTitle>

              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                <StatTile
                  size="lg"
                  value={TOTAL.impressions.toLocaleString()}
                  label="총 노출"
                />
                <StatTile
                  size="lg"
                  value={TOTAL.reactions.toLocaleString()}
                  label="총 반응"
                />
                <StatTile size="lg" value={`${TOTAL.rate}%`} label="평균 반응률" />
                <StatTile size="lg" value={`${TOTAL.posts}건`} label="누적 게시물" />
              </div>

              <div className="mt-1 grid gap-2.5 lg:grid-cols-2">
                <Card>
                  <div className="mb-3 text-[12px] font-bold text-gray700">
                    월별 노출 추이
                  </div>
                  <MonthlyChart />
                </Card>

                <Card>
                  <div className="mb-2.5 text-[12px] font-bold text-gray700">
                    7월 게시물별 성과
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[360px] text-[12px]">
                      <thead>
                        <tr className="border-b border-gray200 text-left text-gray500">
                          <th className="pb-2 font-medium">게시물</th>
                          <th className="pb-2 text-right font-medium">노출</th>
                          <th className="pb-2 text-right font-medium">좋아요</th>
                          <th className="pb-2 text-right font-medium">댓글</th>
                          <th className="pb-2 text-right font-medium">저장</th>
                        </tr>
                      </thead>
                      <tbody>
                        {JULY_POSTS.map((p) => (
                          <tr key={p.title} className="border-b border-gray100">
                            <td className="py-2.5">
                              <span className="mr-1.5 rounded bg-gray100 px-1.5 py-0.5 text-[10px] font-bold text-gray700">
                                {p.kind}
                              </span>
                              <span className="font-bold text-ink">{p.title}</span>
                              <span className="ml-1.5 text-gray500">{p.date}</span>
                            </td>
                            <td className="py-2.5 text-right font-bold text-ink">
                              {p.impressions.toLocaleString()}
                            </td>
                            <td className="py-2.5 text-right text-gray700">{p.likes}</td>
                            <td className="py-2.5 text-right text-gray700">
                              {p.comments}
                            </td>
                            <td className="py-2.5 text-right text-gray700">{p.saves}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
            </section>

            {/* ④ 짚어볼 점 + 문의 */}
            <section className="flex flex-col gap-2">
              <SectionTitle>④ 짚어볼 점 · 대행사에 문의하기</SectionTitle>
              <InquiryPanel />
            </section>
          </>
        )}

        <Disclaimer>
          지금은 화면 구성을 보여주는 목업이에요. 리포트에서 숫자를 읽어오는
          기능은 준비 중이며, 확인한 숫자만 기록으로 남습니다. 문의 문안은
          사장님이 직접 대행사에 보내는 참고 문구예요.
        </Disclaimer>
      </div>
    </AppScreen>
  );
}

/** 상단 4단계 흐름 표시 */
function StepFlow({ stage }: { stage: Stage }) {
  const steps = ["리포트 올리기", "읽은 내용 확인", "대시보드", "문의하기"];
  const reached = stage === "done" ? 4 : stage === "parsing" ? 1 : 0;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {steps.map((s, i) => (
        <span key={s} className="flex items-center gap-1.5">
          <span
            className={`rounded-lg px-2.5 py-1 text-[11px] font-bold ${
              i < reached
                ? "bg-amber100 text-amber800"
                : "bg-gray100 text-gray500"
            }`}
          >
            {i + 1}. {s}
          </span>
          {i < steps.length - 1 && <span className="text-gray300">›</span>}
        </span>
      ))}
    </div>
  );
}

/** 월별 노출 막대 — 라이브러리 없이 비율 막대로 표시 */
function MonthlyChart() {
  const max = Math.max(...MONTHS.map((m) => m.impressions));
  return (
    <div className="flex items-end gap-4">
      {MONTHS.map((m, i) => {
        const last = i === MONTHS.length - 1;
        return (
          <div key={m.label} className="flex flex-1 flex-col items-center gap-1.5">
            <span className="text-[11px] font-bold text-ink">
              {m.impressions.toLocaleString()}
            </span>
            <div className="flex h-28 w-full items-end">
              <div
                className={`w-full rounded-t-lg ${last ? "bg-amber400" : "bg-gray200"}`}
                style={{ height: `${(m.impressions / max) * 100}%` }}
              />
            </div>
            <span className="text-[11px] font-medium text-gray700">{m.label}</span>
            <span className="text-[10px] text-gray500">
              게시 {m.posts}건 · 반응률 {m.rate.toFixed(1)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** 계약 조건과 어긋나는 점 + 보낼 문안 */
function InquiryPanel() {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard?.writeText(INQUIRY);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Card>
      <div className="flex flex-col gap-2">
        {FINDINGS.map((f) => (
          <div
            key={f.title}
            className="rounded-lg border border-amber400 bg-amber50 px-3.5 py-2.5"
          >
            <div className="text-[13px] font-bold text-amber800">! {f.title}</div>
            <p className="mt-1 text-[12px] leading-relaxed text-gray700">{f.body}</p>
          </div>
        ))}
      </div>

      <div className="mt-3">
        <LayerBlock layer="request" label="대행사에 보낼 문의 문안 · 미발송">
          {INQUIRY}
        </LayerBlock>
      </div>

      <div className="mt-2.5 flex gap-2">
        <button
          onClick={copy}
          className="h-10 flex-1 rounded-lg bg-ink text-[13px] font-bold text-white hover:bg-ink/90"
        >
          {copied ? "복사됐어요" : "문안 복사하기"}
        </button>
        <button className="h-10 flex-1 rounded-lg border border-gray300 bg-white text-[13px] font-bold text-gray700">
          이상 있음으로 기록
        </button>
      </div>
      <p className="mt-2 text-[11px] text-gray500">
        기록해두면 날짜와 함께 남아, 나중에 재계약을 검토할 때 근거로 볼 수 있어요.
      </p>
    </Card>
  );
}
