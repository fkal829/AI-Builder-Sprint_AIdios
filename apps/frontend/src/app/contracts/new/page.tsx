"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ProgressDots } from "@/components/Bits";
import { DEMO_CONTRACT_ID, UNDERSTOOD_QUESTIONS } from "@/lib/mock";

/* ① 계약서 PDF 업로드 + ② 내가 안내받고 이해한 조건 5문항 (타이핑 없이 버튼 선택) */
export default function NewContractPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<"upload" | "questions">("upload");
  const [uploaded, setUploaded] = useState(false);
  const [qIndex, setQIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  if (phase === "upload") {
    return (
      <AppScreen
        title="계약서 업로드"
        step="1/2 단계"
        size="sm"
        backHref="/dashboard"
        footer={
          <CTAButton
            disabled={!uploaded}
            onClick={() => setPhase("questions")}
          >
            다음
          </CTAButton>
        }
      >
        <div className="flex flex-col gap-4">
          <h2 className="text-lg font-black leading-snug text-ink">
            계약서 PDF를 올려주세요
          </h2>

          <button
            onClick={() => setUploaded(true)}
            className={`flex h-32 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed text-sm transition ${
              uploaded
                ? "border-amber400 bg-amber50 text-amber700"
                : "border-gray300 text-gray500 hover:bg-paper"
            }`}
          >
            {uploaded ? (
              <>
                <span className="text-2xl">✓</span>
                <span className="font-bold">광고대행_계약서.pdf</span>
                <span className="text-[11px]">업로드됨 · 다시 선택하려면 탭</span>
              </>
            ) : (
              <>
                <span className="text-2xl">＋</span>
                <span>PDF 업로드</span>
              </>
            )}
          </button>

          <a
            href="/sample-contract.pdf"
            target="_blank"
            rel="noreferrer"
            className="text-center text-[11px] text-amber700 underline underline-offset-2"
          >
            예시 계약서(광안리 카페 SNS광고) 미리보기 →
          </a>

          {/* 선택 첨부 — P1 부가 경로 (접힘) */}
          <details className="rounded-lg bg-paper px-3.5 py-3">
            <summary className="flex cursor-pointer items-center justify-between text-xs text-gray500">
              <span>
                제안서·견적서 / 메시지 첨부
                <span className="ml-1.5 rounded bg-amber200 px-1.5 py-0.5 text-[10px] font-bold text-amber800">
                  P1
                </span>
              </span>
              <span>펼치기</span>
            </summary>
            <div className="mt-3 flex h-20 items-center justify-center rounded-lg border border-dashed border-gray300 text-[11px] text-gray500">
              문서로 확인된 설명이 있으면 근거로 함께 대조해요 (선택)
            </div>
          </details>
        </div>
      </AppScreen>
    );
  }

  // ② 5문항
  const q = UNDERSTOOD_QUESTIONS[qIndex];
  const isLast = qIndex === UNDERSTOOD_QUESTIONS.length - 1;

  const choose = (opt: string) => {
    setAnswers((a) => ({ ...a, [q.key]: opt }));
    if (isLast) {
      router.push(`/contracts/${DEMO_CONTRACT_ID}/analysis`);
    } else {
      setQIndex((i) => i + 1);
    }
  };

  const goBack = () => {
    if (qIndex === 0) setPhase("upload");
    else setQIndex((i) => i - 1);
  };

  return (
    <AppScreen
      title="내가 안내받고 이해한 조건"
      step={`${qIndex + 1}/${UNDERSTOOD_QUESTIONS.length}`}
      size="sm"
      onBack={goBack}
    >
      <div className="flex flex-col gap-5">
        <h2 className="whitespace-pre-line text-lg font-black leading-snug text-ink">
          {q.title}
        </h2>

        <div className="flex flex-col gap-2">
          {q.options.map((opt) => {
            const selected = answers[q.key] === opt;
            const isDontRemember = opt === "잘 기억 안 나요";
            return (
              <button
                key={opt}
                onClick={() => choose(opt)}
                className={`min-h-[52px] rounded-lg px-4 text-left text-sm font-bold transition ${
                  selected
                    ? "border-2 border-amber700 bg-amber200"
                    : isDontRemember
                      ? "border border-dashed border-gray500 bg-white font-medium text-gray500"
                      : "border-2 border-ink bg-white hover:bg-paper"
                }`}
              >
                {opt}
              </button>
            );
          })}
        </div>

        <ProgressDots total={UNDERSTOOD_QUESTIONS.length} current={qIndex + 1} />

        <p className="text-[11px] leading-relaxed text-gray500">
          여기 답하신 내용은 &lsquo;사용자가 기억하고 이해한 설명&rsquo;으로만 쓰여요.
          대행사가 다르게 말했다고 단정하지 않아요.
        </p>
      </div>
    </AppScreen>
  );
}
