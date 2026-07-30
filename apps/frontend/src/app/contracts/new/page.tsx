"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ProgressDots } from "@/components/Bits";
import { DEMO_CONTRACT_ID, UNDERSTOOD_QUESTIONS } from "@/lib/mock";
import { saveUnderstood, type UnderstoodKey } from "@/lib/understood";

/** 바이트를 사람이 읽기 쉬운 크기로 변환 */
function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ① 계약서 PDF 업로드 + ② 내가 안내받고 이해한 조건 5문항 (타이핑 없이 버튼 선택) */
export default function NewContractPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<"upload" | "questions">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [qIndex, setQIndex] = useState(0);
  const [answers, setAnswers] = useState<Partial<Record<UnderstoodKey, string>>>({});
  const [customText, setCustomText] = useState("");

  const uploaded = !!file;

  // 특정 문항의 직접입력 칸에 채워둘 값(이전에 직접 입력한 값, 없으면 빈 문자열)
  const prefillFor = (i: number) => {
    const cur = UNDERSTOOD_QUESTIONS[i];
    const prev = cur ? answers[cur.key] : undefined;
    return prev && !cur.options.includes(prev) ? prev : "";
  };

  /** 파일 검증 후 상태 반영 — 파일 선택/드롭 공통 진입점 */
  const acceptFile = (f: File | undefined | null) => {
    if (!f) return;
    const isPdf =
      f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      setError("PDF 파일만 올릴 수 있어요.");
      setFile(null);
      return;
    }
    setError(null);
    setFile(f);
  };

  const onDrop = (e: React.DragEvent<HTMLElement>) => {
    e.preventDefault();
    setDragActive(false);
    acceptFile(e.dataTransfer.files?.[0]);
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

          {/* 숨겨진 실제 파일 입력 — 드롭존 클릭 시 열림 */}
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(e) => {
              acceptFile(e.target.files?.[0]);
              // 같은 파일 재선택도 감지되도록 초기화
              e.target.value = "";
            }}
          />

          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setDragActive(false);
            }}
            onDrop={onDrop}
            className={`flex h-32 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed text-sm transition ${
              dragActive
                ? "border-amber700 bg-amber100 text-amber800"
                : uploaded
                  ? "border-amber400 bg-amber50 text-amber700"
                  : "border-gray300 text-gray500 hover:bg-paper"
            }`}
          >
            {dragActive ? (
              <>
                <span className="text-2xl">⤓</span>
                <span className="font-bold">여기에 놓으면 업로드돼요</span>
              </>
            ) : uploaded ? (
              <>
                <span className="text-2xl">✓</span>
                <span className="font-bold">{file!.name}</span>
                <span className="text-[11px]">
                  {formatBytes(file!.size)} · 다시 선택하려면 클릭
                </span>
              </>
            ) : (
              <>
                <span className="text-2xl">＋</span>
                <span>PDF를 클릭해서 선택하거나 여기로 끌어다 놓으세요</span>
              </>
            )}
          </button>

          {error && (
            <p className="text-[12px] font-bold text-amber800">⚠ {error}</p>
          )}

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
    const next = { ...answers, [q.key]: opt };
    setAnswers(next);
    if (isLast) {
      // 설문 응답 저장 → 분석 결과의 '내가 이해한 조건 요약'에서 사용
      saveUnderstood(DEMO_CONTRACT_ID, next);
      router.push(`/contracts/${DEMO_CONTRACT_ID}/analysis`);
    } else {
      setQIndex(qIndex + 1);
      setCustomText(prefillFor(qIndex + 1));
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

          {/* 직접 입력 — 보기에 없는 답변을 회색 placeholder로 안내 */}
          {(() => {
            const answer = answers[q.key];
            const customSelected = !!answer && !q.options.includes(answer);
            return (
              <div
                className={`flex min-h-[52px] items-center rounded-lg pl-4 pr-2 transition ${
                  customSelected
                    ? "border-2 border-amber700 bg-amber200"
                    : "border-2 border-dashed border-gray300 bg-white focus-within:border-ink"
                }`}
              >
                <input
                  value={customText}
                  onChange={(e) => setCustomText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitCustom();
                  }}
                  placeholder="직접 입력…"
                  className="min-w-0 flex-1 bg-transparent text-sm font-bold text-ink outline-none placeholder:font-medium placeholder:text-gray400"
                />
                <button
                  type="button"
                  onClick={submitCustom}
                  disabled={!customText.trim()}
                  className="ml-2 flex-none rounded-md bg-ink px-3 py-1.5 text-xs font-bold text-white transition disabled:opacity-30"
                >
                  {isLast ? "완료" : "다음"}
                </button>
              </div>
            );
          })()}
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
