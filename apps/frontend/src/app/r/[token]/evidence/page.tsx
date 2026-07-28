"use client";

import { useState } from "react";
import { AgencyShell } from "@/components/AgencyShell";

/* 대행사 ④ 산출물 URL 제출 — 무가입 토큰 접근. */
export default function AgencyEvidencePage() {
  const [url, setUrl] = useState("");
  const [submitted, setSubmitted] = useState(false);

  return (
    <AgencyShell>
      <div className="rounded-xl border-2 border-ink bg-white p-6">
        {submitted ? (
          <>
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-amber50 text-2xl text-amber700">
              ✓
            </div>
            <h1 className="text-base font-black text-ink">
              증빙을 제출했어요
            </h1>
            <p className="mt-2 text-[13px] leading-relaxed text-gray700">
              사장님이 확인하면 &lsquo;지급 조건 충족&rsquo;으로 표시돼요. 실제
              송금·결제는 이 화면에서 진행되지 않습니다.
            </p>
            <div className="mt-3 break-all rounded-lg bg-paper px-3 py-2 text-[12px] text-gray700">
              {url}
            </div>
          </>
        ) : (
          <>
            <h1 className="text-base font-black text-ink">
              산출물 증빙을 등록해주세요
            </h1>
            <p className="mt-1 text-[12px] text-gray500">
              인스타그램 게시물 4건 · 기한 2026-08-20
            </p>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="게시물 URL 입력 (예: instagram.com/p/...)"
              className="mt-3 w-full rounded-lg border border-gray300 px-3 py-2.5 text-[13px] outline-none focus:border-ink"
            />
            <button
              disabled={!url.trim()}
              onClick={() => setSubmitted(true)}
              className="mt-3 h-12 w-full rounded-lg bg-ink text-[14px] font-bold text-white disabled:opacity-40"
            >
              제출하기
            </button>
          </>
        )}
      </div>
    </AgencyShell>
  );
}
