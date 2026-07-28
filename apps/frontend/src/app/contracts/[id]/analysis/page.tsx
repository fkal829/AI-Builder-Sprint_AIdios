"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen } from "@/components/AppScreen";

/* ③ AI 분석 진행 — Evaluator Loop(최대 2회 재시도) 단계 표시.
   "검토 중"처럼 중립적으로. 판정 느낌 없이. */
const STEPS = [
  "계약서를 읽고 있어요",
  "조건을 뽑고 있어요",
  "이해하신 내용과 대조 중",
];

export default function AnalysisPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (step >= STEPS.length) {
      const t = setTimeout(() => router.replace(`/contracts/${id}`), 500);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setStep((s) => s + 1), 1100);
    return () => clearTimeout(t);
  }, [step, id, router]);

  return (
    <AppScreen size="sm">
      <div className="flex flex-col items-center gap-6 py-10">
        <div className="h-16 w-16 animate-acc-spin rounded-full border-4 border-amber200 border-t-amber700" />
        <h2 className="text-center text-base font-black text-ink">
          계약서를 살펴보고 있어요
        </h2>

        <div className="flex w-full flex-col gap-3">
          {STEPS.map((label, i) => {
            const done = i < step;
            const active = i === step;
            return (
              <div
                key={label}
                className={`flex items-center gap-2.5 text-[13px] ${
                  done
                    ? "text-gray500"
                    : active
                      ? "font-bold text-ink"
                      : "text-gray400"
                }`}
              >
                <span
                  className={`flex h-4 w-4 flex-none items-center justify-center rounded-full text-[10px] ${
                    done
                      ? "bg-amber700 text-white"
                      : active
                        ? "border-2 border-amber700"
                        : "border-2 border-gray300"
                  }`}
                >
                  {done ? "✓" : ""}
                </span>
                {label}
              </div>
            );
          })}
        </div>

        <p className="text-center text-[11px] text-gray500">보통 30초 정도 걸려요</p>
      </div>
    </AppScreen>
  );
}
