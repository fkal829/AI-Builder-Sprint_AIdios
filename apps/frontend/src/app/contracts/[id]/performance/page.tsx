"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { AppScreen } from "@/components/AppScreen";
import { Card, Disclaimer, SectionTitle } from "@/components/Bits";
import { StatTile } from "@/components/StatTile";
import { LayerBlock } from "@/components/LayerBlock";
import { ConfirmModal } from "@/components/ConfirmModal";
import { useAsync } from "@/lib/hooks";
import { adapter, type LiveObligation } from "@/lib/adapter";
import {
  clearSavedReport,
  useSavedReport,
  writeSavedReport,
} from "@/lib/reportDemo";

/* ⑩⑪ 이행·광고효과 관리 — 체결 후 사장님이 들어오는 관리 단계 단일 화면.
   대행사에게 받은 리포트를 사장님이 올리면 → 지표를 뽑아 대시보드로 모으고 →
   계약 조건과 대조해 어긋나는 부분을 짚고 → 그 숫자를 근거로 산출물 증빙을
   확인 완료(지급 조건 충족)하거나 이의로 기록한다.
   ①~④는 화면 목업(문서 추출 연동 후 실제 값이 붙는다), ⑤만 실 API 연동.
   데모 전용 데이터라 mock.ts(실 API 응답 모델)와 분리해 이 파일에 둔다. */

const MONTHS = [
  { label: "5월", impressions: 12400, reactions: 486, posts: 4, rate: 3.9 },
  { label: "6월", impressions: 15200, reactions: 612, posts: 4, rate: 4.0 },
  { label: "7월", impressions: 8300, reactions: 240, posts: 2, rate: 2.9 },
];

/** 이번에 올린 리포트가 담은 달 — 저장하면 이 값이 모아보기에 더해진다 */
const JULY = { period: "2026년 7월", impressions: 8300, reactions: 240, posts: 2 };

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

/* idle 업로드 전 · parsing 추출 중 · review 읽은 값 확인 대기 · saved 확인 완료
   review와 saved를 나눠야 "확인한 값만 대시보드에 쌓여요"가 실제 동작과 맞는다. */
type Stage = "idle" | "parsing" | "review" | "saved";

export default function PerformancePage() {
  const { id } = useParams<{ id: string }>();
  const [localStage, setLocalStage] = useState<Stage>("idle");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  // 저장은 세션에 남으므로, 모아보기에서 돌아와도 저장 상태를 잃지 않는다
  const saved = useSavedReport();
  const stage: Stage = saved?.contractId === id ? "saved" : localStage;

  const runDemo = () => {
    setLocalStage("parsing");
    window.setTimeout(() => setLocalStage("review"), 900);
  };

  const save = () =>
    writeSavedReport({
      contractId: id,
      period: JULY.period,
      impressions: JULY.impressions,
      reactions: JULY.reactions,
      posts: JULY.posts,
      savedAt: "2026-07-31",
    });

  /* 저장 후 삭제는 이 계약과 전체 모아보기 합계에서 값을 빼는 동작이라
     확인을 받는다. 실제 구현에서는 저장된 지표를 백엔드에서 지운다. */
  const reset = () => {
    clearSavedReport();
    setLocalStage("idle");
    setConfirmingDelete(false);
  };

  return (
    <AppScreen
      title="이행·광고효과 관리"
      size="wide"
      backHref="/dashboard"
      right={
        <span className="rounded bg-brand200 px-1.5 py-0.5 text-[10px] font-bold text-brand800">
          화면 목업 · 개발 예정
        </span>
      }
    >
      <div className="flex flex-col gap-5">
        <p className="text-[13px] leading-relaxed text-neutral700">
          대행사에게 받은 광고 리포트를 올려두면, 계약에서 약속한 조건대로
          진행되고 있는지 한눈에 확인하고 산출물 증빙까지 마무리할 수 있어요.
        </p>

        {/* 계약 단계 ↔ 관리 단계 연결 — 무엇을 근거로 대조하는지 밝힌다 */}
        <Card>
          <p className="text-[12px] leading-relaxed text-neutral700">
            <b className="text-ink">계약서를 기준으로 확인해요.</b> 제3조(서비스의
            범위)에 적힌 <b className="text-ink">월 4건 게시</b> 약정과 리포트를
            대조합니다.
          </p>
          <p className="mt-1.5 text-[11px] leading-relaxed text-neutral500">
            이 계약에는 성과 보고 조항이 따로 없어요. 다음 재계약 때 &lsquo;월 1회 성과
            보고&rsquo;를 넣어두면, 받을 지표와 주기가 계약으로 정해져요.
          </p>
          <div className="mt-2.5">
            <a
              href={`/contracts/${id}`}
              className="rounded-lg border border-neutral300 bg-white px-3 py-1.5 text-[12px] font-bold text-ink hover:bg-subtle"
            >
              계약서에서 보기 →
            </a>
          </div>
        </Card>

        <StepFlow stage={stage} />

        {/* ① 리포트 올리기 */}
        <section className="flex flex-col gap-2">
          <SectionTitle>① 대행사 리포트 올리기</SectionTitle>
          <Card>
            {stage === "idle" ? (
              <div className="flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-neutral300 bg-subtle px-6 py-8 text-center">
                <span className="text-3xl">📄</span>
                <div>
                  <div className="text-[13px] font-bold text-ink">
                    월간 리포트나 인사이트 화면을 올려주세요
                  </div>
                  <div className="mt-1 text-[11px] text-neutral500">
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
                    <div className="text-[11px] text-neutral500">
                      2026-07-31 업로드 · 대행사 제공
                    </div>
                  </div>
                </div>
                {stage === "saved" ? (
                  <button
                    onClick={() => setConfirmingDelete(true)}
                    className="flex-none rounded-lg border border-neutral300 bg-white px-3 py-1.5 text-[12px] font-bold text-neutral700 hover:bg-subtle"
                  >
                    리포트 삭제
                  </button>
                ) : (
                  <button
                    onClick={reset}
                    className="flex-none rounded-lg border border-neutral300 bg-white px-3 py-1.5 text-[12px] font-bold text-neutral700 hover:bg-subtle"
                  >
                    다시 올리기
                  </button>
                )}
              </div>
            )}
          </Card>
        </section>

        {stage === "parsing" && (
          <p className="py-8 text-center text-sm text-neutral500">
            리포트에서 숫자를 읽는 중…
          </p>
        )}

        {(stage === "review" || stage === "saved") && (
          /* ② 읽은 내용 확인 — 저장 전에는 여기서 멈춘다 */
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
                      <span className="text-neutral700">{f.label}</span>
                      <span className="flex items-center gap-2">
                        <b className="text-ink">{f.value}</b>
                        <span className="text-[10px] font-bold text-brand700">
                          확신도 {f.confidence}%
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              </LayerBlock>
              {stage === "review" ? (
                <>
                  <button
                    onClick={save}
                    className="mt-3 h-11 w-full rounded-lg bg-ink text-[13px] font-bold text-white hover:bg-ink/90"
                  >
                    맞아요, 저장할게요
                  </button>
                  <p className="mt-2 text-[11px] text-neutral500">
                    저장해야 아래 대시보드와 전체 광고효과 모아보기에 쌓여요.{" "}
                    <button className="font-bold text-brand700 underline underline-offset-2">
                      숫자를 고칠게요
                    </button>
                  </p>
                </>
              ) : (
                <p className="mt-3 text-[12px] font-bold text-brand700">
                  ✓ 사장님이 확인한 값으로 저장했어요
                </p>
              )}
            </Card>
          </section>
        )}

        {stage === "saved" && (
          <>
            {/* 저장이 어디에 반영됐는지 곧바로 보여준다 */}
            <div className="flex flex-col gap-2 rounded-xl border border-brand400 bg-brand50 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-[13px] font-bold text-brand800">
                  ✓ {JULY.period} 리포트가 저장됐어요
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-neutral700">
                  노출 {JULY.impressions.toLocaleString()} · 반응{" "}
                  {JULY.reactions.toLocaleString()} · 게시물 {JULY.posts}건이 이
                  계약과 전체 광고효과 모아보기에 함께 더해졌어요.
                </p>
              </div>
              <a
                href="/performance"
                className="flex-none rounded-lg border border-brand400 bg-white px-3 py-2 text-center text-[12px] font-bold text-brand700 hover:bg-brand100"
              >
                모아보기에서 확인 →
              </a>
            </div>

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
                  <div className="mb-3 text-[12px] font-bold text-neutral700">
                    월별 노출 추이
                  </div>
                  <MonthlyChart />
                </Card>

                <Card>
                  <div className="mb-2.5 text-[12px] font-bold text-neutral700">
                    7월 게시물별 성과
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[360px] text-[12px]">
                      <thead>
                        <tr className="border-b border-neutral200 text-left text-neutral500">
                          <th className="pb-2 font-medium">게시물</th>
                          <th className="pb-2 text-right font-medium">노출</th>
                          <th className="pb-2 text-right font-medium">좋아요</th>
                          <th className="pb-2 text-right font-medium">댓글</th>
                          <th className="pb-2 text-right font-medium">저장</th>
                        </tr>
                      </thead>
                      <tbody>
                        {JULY_POSTS.map((p) => (
                          <tr key={p.title} className="border-b border-neutral100">
                            <td className="py-2.5">
                              <span className="mr-1.5 rounded bg-neutral100 px-1.5 py-0.5 text-[10px] font-bold text-neutral700">
                                {p.kind}
                              </span>
                              <span className="font-bold text-ink">{p.title}</span>
                              <span className="ml-1.5 text-neutral500">{p.date}</span>
                            </td>
                            <td className="py-2.5 text-right font-bold text-ink">
                              {p.impressions.toLocaleString()}
                            </td>
                            <td className="py-2.5 text-right text-neutral700">{p.likes}</td>
                            <td className="py-2.5 text-right text-neutral700">
                              {p.comments}
                            </td>
                            <td className="py-2.5 text-right text-neutral700">{p.saves}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
            </section>

            {/* ④ 계약과 대조 + 문의 */}
            <section className="flex flex-col gap-2">
              <SectionTitle>④ 계약과 대조해봤어요 · 대행사에 문의하기</SectionTitle>
              <InquiryPanel />
            </section>

            {/* ⑤ 위 숫자를 근거로 산출물 증빙을 마무리한다 */}
            <section className="flex flex-col gap-2">
              <SectionTitle>⑤ 산출물 증빙 확인</SectionTitle>
              <ObligationPanel contractId={id} />
            </section>
          </>
        )}

        <Disclaimer>
          ①~④는 화면 구성을 보여주는 목업이에요. 리포트에서 숫자를 읽어오는
          기능은 준비 중이며, 확인한 숫자만 기록으로 남습니다. 문의 문안은
          사장님이 직접 대행사에 보내는 참고 문구예요.
        </Disclaimer>

        <ConfirmModal
          open={confirmingDelete}
          eyebrow="삭제 전 확인"
          title={`${JULY.period} 리포트를 삭제할까요?`}
          body={
            <>
              <p>
                노출 {JULY.impressions.toLocaleString()} · 반응{" "}
                {JULY.reactions.toLocaleString()} · 게시물 {JULY.posts}건이 이
                계약과 전체 광고효과 모아보기 합계에서 빠져요.
              </p>
              <p className="mt-2 text-neutral500">
                ⑤에서 확인한 증빙 기록은 그대로 남아요. 리포트를 다시 올리면
                숫자는 새로 쌓입니다.
              </p>
            </>
          }
          confirmLabel="삭제할게요"
          cancelLabel="그대로 둘게요"
          onConfirm={reset}
          onCancel={() => setConfirmingDelete(false)}
        />
      </div>
    </AppScreen>
  );
}

/** 상단 5단계 흐름 표시 — 저장 전에는 ②에서 멈춰 있다는 걸 보여준다 */
function StepFlow({ stage }: { stage: Stage }) {
  const steps = [
    "리포트 올리기",
    "읽은 내용 확인",
    "대시보드",
    "계약과 대조",
    "증빙 확인",
  ];
  const reached =
    stage === "saved" ? 5 : stage === "review" ? 2 : stage === "parsing" ? 1 : 0;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {steps.map((s, i) => (
        <span key={s} className="flex items-center gap-1.5">
          <span
            className={`rounded-lg px-2.5 py-1 text-[11px] font-bold ${
              i < reached
                ? "bg-brand100 text-brand800"
                : "bg-neutral100 text-neutral500"
            }`}
          >
            {i + 1}. {s}
          </span>
          {i < steps.length - 1 && <span className="text-neutral300">›</span>}
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
                className={`w-full rounded-t-lg ${last ? "bg-brand400" : "bg-neutral200"}`}
                style={{ height: `${(m.impressions / max) * 100}%` }}
              />
            </div>
            <span className="text-[11px] font-medium text-neutral700">
              {m.label}
              {last && (
                <span className="ml-1 rounded bg-brand200 px-1 py-0.5 text-[9px] font-bold text-brand800">
                  방금 추가
                </span>
              )}
            </span>
            <span className="text-[10px] text-neutral500">
              게시 {m.posts}건 · 반응률 {m.rate.toFixed(1)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** 대표 산출물 증빙 확인 — 위에서 확인한 숫자를 근거로 지급 조건 충족/이의를 기록한다.
    화면 안에서 유일하게 실 API에 연결된 부분. */
function ObligationPanel({ contractId }: { contractId: string }) {
  const state = useAsync(() => adapter.getObligation(contractId), [contractId]);
  const [updated, setUpdated] = useState<LiveObligation | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const obligation = updated ?? (state.status === "ready" ? state.data : null);

  const review = async (decision: "APPROVED" | "DISPUTED") => {
    if (!obligation || working) return;
    setWorking(true);
    setError(null);
    try {
      setUpdated(await adapter.reviewObligation(contractId, obligation.id, decision));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "증빙 검토 결과를 저장하지 못했습니다.");
    } finally {
      setWorking(false);
    }
  };

  if (state.status === "loading") {
    return <p className="py-6 text-center text-sm text-neutral500">불러오는 중…</p>;
  }
  if (state.status === "error") {
    return (
      <p className="py-6 text-center text-sm font-bold text-brand800">⚠ {state.error}</p>
    );
  }
  if (!obligation) {
    return (
      <Card>
        <p className="text-[12px] leading-relaxed text-neutral500">
          원문 근거로 확인된 대표 산출물이 아직 없어요. 계약서 분석이 끝나면
          이곳에서 증빙을 확인할 수 있어요.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <div className="text-[13px] font-black text-ink">{obligation.title}</div>
      <div className="mt-2 rounded-lg bg-subtle p-3.5">
        <div className="text-[11px] text-neutral500">기한 {obligation.dueDate}</div>
        <p className="mt-2 text-[12px] leading-relaxed text-neutral700">
          계약서 {obligation.sourcePage}쪽: “{obligation.sourceText}”
        </p>
        <div className="mt-1 text-[10px] text-neutral500">
          원문 근거 확신도 {Math.round(obligation.confidence * 100)}%
        </div>
      </div>

      {(obligation.status === "PENDING" || obligation.status === "SUBMITTED") && (
        <>
          <p className="mt-3 text-[12px] leading-relaxed text-neutral700">
            위 리포트에서 확인한 <b className="text-ink">게시물 2건</b>을 근거로
            판단해주세요.
          </p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={working}
              onClick={() => review("APPROVED")}
              className="h-11 flex-1 rounded-lg bg-ink text-[13px] font-bold text-white disabled:opacity-40"
            >
              {working ? "저장 중…" : "확인 완료"}
            </button>
            <button
              type="button"
              disabled={working}
              onClick={() => review("DISPUTED")}
              className="h-11 flex-1 rounded-lg border border-neutral300 bg-white text-[13px] font-bold text-neutral500 disabled:opacity-40"
            >
              이의 있어요
            </button>
          </div>
        </>
      )}

      {obligation.status === "APPROVED" && (
        <p className="mt-3 text-[13px] font-bold text-brand700">
          ✓ 지급 조건 충족으로 표시했어요
        </p>
      )}
      {obligation.status === "DISPUTED" && (
        <p className="mt-3 text-[13px] font-bold text-neutral700">
          ! 이의 있음으로 기록했어요
        </p>
      )}

      {error && <p className="mt-2 text-xs font-bold text-red-700">{error}</p>}
      <p className="mt-2 text-[11px] leading-relaxed text-neutral500">
        확인 완료는 계약상 지급 조건 충족 표시이며 실제 송금·결제를 실행하지
        않습니다.
      </p>
    </Card>
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
            className="rounded-lg border border-brand400 bg-brand50 px-3.5 py-2.5"
          >
            <div className="text-[13px] font-bold text-brand800">! {f.title}</div>
            <p className="mt-1 text-[12px] leading-relaxed text-neutral700">{f.body}</p>
          </div>
        ))}
      </div>

      <div className="mt-3">
        <LayerBlock layer="request" label="대행사에 보낼 문의 문안 · 미발송">
          {INQUIRY}
        </LayerBlock>
      </div>

      <button
        onClick={copy}
        className="mt-2.5 h-11 w-full rounded-lg bg-ink text-[13px] font-bold text-white hover:bg-ink/90"
      >
        {copied ? "복사됐어요" : "문안 복사하기"}
      </button>
      <p className="mt-2 text-[11px] leading-relaxed text-neutral500">
        복사해서 기존 이메일이나 메신저로 보내주세요. 이상이 있다면 아래 ⑤에서
        &lsquo;이의 있어요&rsquo;로 기록해두면 재계약을 검토할 때 근거가 돼요.
      </p>
    </Card>
  );
}
