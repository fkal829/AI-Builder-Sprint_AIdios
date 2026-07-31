"use client";

import { useState } from "react";
import type { SourceRef } from "@/lib/types";

/* 근거 필수(설계 원칙 #4) — 원문 페이지·문장을 한 번의 클릭으로 확인.
   근거가 없으면(원문 없음) 확정값으로 표시하지 않고 안내 문구를 보여준다. */
export function SourceLink({ source }: { source: SourceRef | null }) {
  const [open, setOpen] = useState(false);

  if (!source) {
    return (
      <p className="text-[11px] text-neutral500">
        계약서에서 근거를 찾지 못했어요 — 확정된 내용으로 보지 마세요.
      </p>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] font-medium text-brand700 underline underline-offset-2"
      >
        원문 위치 보기 · {source.page}페이지 {open ? "▲" : "→"}
      </button>
      {open && (
        <blockquote className="mt-1.5 rounded-md border-l-2 border-brand400 bg-white px-3 py-2 text-[13px] leading-relaxed text-neutral700">
          “{source.text}”
          <span className="mt-1 block text-[10px] text-neutral500">
            계약서 {source.page}페이지
          </span>
        </blockquote>
      )}
    </div>
  );
}
