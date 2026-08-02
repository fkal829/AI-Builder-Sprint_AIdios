"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ProgressDots } from "@/components/Bits";
import { FileDropzone } from "@/components/FileDropzone";
import { UNDERSTOOD_QUESTIONS } from "@/lib/mock";
import { adapter } from "@/lib/adapter";
import { saveUnderstood, type UnderstoodKey } from "@/lib/understood";

/* ① 계약서 PDF 업로드 + ② 내가 안내받고 이해한 조건 5문항 (타이핑 없이 버튼 선택) */
export default function NewContractPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<"upload" | "questions">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [counterpartyName, setCounterpartyName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [qIndex, setQIndex] = useState(0);
  const [answers, setAnswers] = useState<Partial<Record<UnderstoodKey, string>>>({});
  const [customText, setCustomText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const uploaded = !!file;

  // 소개 페이지의 설문 미리보기 진입 — ?phase=questions 이면 바로 문항 화면부터.
  // URL을 마운트 시 한 번 반영하는 동기화라 초기값은 SSR/CSR 모두 upload로 같다.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("phase") === "questions") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPhase("questions");
    }
  }, []);

  // 특정 문항의 직접입력 칸에 채워둘 값(이전에 직접 입력한 값, 없으면 빈 문자열)
  const prefillFor = (i: number) => {
    const cur = UNDERSTOOD_QUESTIONS[i];
    const prev = cur ? answers[cur.key] : undefined;
    return prev && !cur.options.includes(prev) ? prev : "";
  };

  /** 드롭존이 통과시킨 파일 반영 — 계약 이름 기본값도 파일명에서 채운다 */
  const acceptFile = (f: File) => {
    setError(null);
    setFile(f);
    setTitle((current) => current || f.name.replace(/\.pdf$/i, ""));
  };

  const rejectFile = (message: string) => {
    setError(message);
    setFile(null);
  };

  if (phase === "upload") {
    return (
      <AppScreen
        title="계약서 업로드"
        step="1/2 단계"
        size="sm"
        backHref="/dashboard"
        footer={
          <CTAButton
            disabled={!uploaded || !title.trim() || !counterpartyName.trim()}
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

          <FileDropzone file={file} onFile={acceptFile} onError={rejectFile} />

          {error && (
            <p className="text-[12px] font-bold text-brand800">⚠ {error}</p>
          )}

          <label className="flex flex-col gap-1.5 text-xs font-bold text-neutral700">
            계약 이름
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={120}
              placeholder="예: SNS 광고대행 계약"
              className="h-11 rounded-lg border border-neutral300 bg-white px-3 text-sm text-ink outline-none focus:border-ink"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-xs font-bold text-neutral700">
            대행사 이름
            <input
              value={counterpartyName}
              onChange={(e) => setCounterpartyName(e.target.value)}
              maxLength={120}
              placeholder="계약 상대방 또는 대행사명"
              className="h-11 rounded-lg border border-neutral300 bg-white px-3 text-sm text-ink outline-none focus:border-ink"
            />
          </label>
        </div>
      </AppScreen>
    );
  }

  // ② 5문항
  const q = UNDERSTOOD_QUESTIONS[qIndex];
  const isLast = qIndex === UNDERSTOOD_QUESTIONS.length - 1;

  const choose = (opt: string) => {
    const next = { ...answers, [q.key]: opt };
    setAnswers(next);
    if (isLast) {
      void submitContract(next);
    } else {
      setQIndex(qIndex + 1);
      setCustomText(prefillFor(qIndex + 1));
    }
  };

  const submitContract = async (next: Partial<Record<UnderstoodKey, string>>) => {
    if (!file || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const contract = await adapter.createContract({ title, counterpartyName });
      const document = await adapter.uploadContractDocument(contract.id, file);
      await adapter.saveUnderstoodTerms(contract.id, {
        durationText: answer(next.durationText),
        monthlyAmount: parseKrw(answer(next.monthlyAmount)),
        totalAmount: parseKrw(answer(next.totalAmount)),
        refundText: answer(next.refundText),
        terminationText: answer(next.terminationText),
      });
      await adapter.startContractAnalysis(contract.id, document.id);
      // 목업 상세 화면의 기존 설문 요약도 계속 지원한다.
      saveUnderstood(contract.id, next);
      router.push(`/contracts/${contract.id}/analysis`);
    } catch (error) {
      setError(error instanceof Error ? error.message : "계약서 등록을 완료하지 못했습니다.");
      setSubmitting(false);
    }
  };

  const submitCustom = () => {
    const v = customText.trim();
    if (v) choose(v);
  };

  const goBack = () => {
    if (qIndex === 0) {
      setPhase("upload");
    } else {
      setQIndex(qIndex - 1);
      setCustomText(prefillFor(qIndex - 1));
    }
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
                disabled={submitting}
                className={`min-h-[52px] rounded-lg px-4 text-left text-sm font-bold transition ${
                  selected
                    ? "border-2 border-brand700 bg-brand200"
                    : isDontRemember
                      ? "border border-dashed border-neutral500 bg-white font-medium text-neutral500"
                      : "border-2 border-ink bg-white hover:bg-subtle"
                }`}
              >
                {opt}
              </button>
            );
          })}

          {/* 직접 입력 — 보기에 없는 답변을 회색 placeholder로 안내 */}
          {(() => {
            const answer = answers[q.key];
            const customSelected = !!answer && !q.options.includes(answer);
            return (
              <div
                className={`flex min-h-[52px] items-center rounded-lg pl-4 pr-2 transition ${
                  customSelected
                    ? "border-2 border-brand700 bg-brand200"
                    : "border-2 border-dashed border-neutral300 bg-white focus-within:border-ink"
                }`}
              >
                <input
                  value={customText}
                  onChange={(e) => setCustomText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitCustom();
                  }}
                  placeholder="직접 입력…"
                  className="min-w-0 flex-1 bg-transparent text-sm font-bold text-ink outline-none placeholder:font-medium placeholder:text-neutral400"
                />
                <button
                  type="button"
                  onClick={submitCustom}
                  disabled={!customText.trim() || submitting}
                  className="ml-2 flex-none rounded-md bg-ink px-3 py-1.5 text-xs font-bold text-white transition disabled:opacity-30"
                >
                  {isLast ? "완료" : "다음"}
                </button>
              </div>
            );
          })()}
        </div>

        <ProgressDots total={UNDERSTOOD_QUESTIONS.length} current={qIndex + 1} />

        <p className="text-[11px] leading-relaxed text-neutral500">
          여기 답하신 내용은 &lsquo;사용자가 기억하고 이해한 설명&rsquo;으로만 쓰여요.
          대행사가 다르게 말했다고 단정하지 않아요.
        </p>
        {error && <p className="text-center text-xs font-bold text-brand800">⚠ {error}</p>}
        {submitting && <p className="text-center text-xs text-neutral500">계약서를 등록하고 있어요…</p>}
      </div>
    </AppScreen>
  );
}

function answer(value: string | undefined): string {
  return value?.trim() || "잘 기억 안 나요";
}

function parseKrw(value: string): number | null {
  const normalized = value.replace(/[\s,]/g, "");
  if (/기억 안 나요|따로 안 들었어요/.test(normalized)) return null;
  const direct = Number(normalized);
  if (Number.isSafeInteger(direct) && direct >= 0) return direct;
  const match = normalized.match(/(\d+(?:\.\d+)?)만원/);
  if (match) return Math.round(Number(match[1]) * 10_000);
  return null;
}
