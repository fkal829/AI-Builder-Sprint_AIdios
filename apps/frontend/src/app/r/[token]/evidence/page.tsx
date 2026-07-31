"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useParams } from "next/navigation";
import { AgencyShell } from "@/components/AgencyShell";
import { adapter, PublicApiError } from "@/lib/adapter";

/* 대행사 ④ 산출물 URL 제출 — 무가입 토큰 접근. */
export default function AgencyEvidencePage() {
  const { token } = useParams<{ token: string }>();
  const [url, setUrl] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [expired, setExpired] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const evidenceUrl = url.trim();
    if (!evidenceUrl || submitting || expired) return;

    setSubmitting(true);
    setSubmitError(null);
    try {
      await adapter.submitObligationEvidence(token, evidenceUrl);
      setUrl(evidenceUrl);
      setSubmitted(true);
    } catch (error) {
      if (error instanceof PublicApiError) {
        if (error.status === 410 || error.code === "OBLIGATION_LINK_EXPIRED") {
          setExpired(true);
          return;
        }
        if (error.status === 404) {
          setSubmitError("유효하지 않은 제출 링크입니다. 링크를 다시 확인해 주세요.");
          return;
        }
        if (error.status === 409) {
          setSubmitError("이미 증빙이 제출되었거나 현재 제출할 수 없는 상태입니다.");
          return;
        }
        if (error.status === 422) {
          setSubmitError("http:// 또는 https://로 시작하는 올바른 URL을 입력해 주세요.");
          return;
        }
      }
      setSubmitError(
        error instanceof Error
          ? error.message
          : "증빙을 제출하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AgencyShell>
      <div className="rounded-xl border-2 border-ink bg-white p-6">
        {expired ? (
          <>
            <h1 className="text-base font-black text-ink">
              제출 링크가 만료됐어요
            </h1>
            <p className="mt-2 text-[13px] leading-relaxed text-gray700">
              계약 요청자에게 새 증빙 제출 링크를 요청해 주세요.
            </p>
          </>
        ) : submitted ? (
          <>
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-amber50 text-2xl text-amber700">
              ✓
            </div>
            <h1 className="text-base font-black text-ink">
              증빙을 제출했어요
            </h1>
            <p className="mt-2 text-[13px] leading-relaxed text-gray700">
              사장님이 승인하면 &lsquo;지급 조건 충족&rsquo;으로 표시돼요. 실제
              송금·결제는 이 화면에서 진행되지 않습니다.
            </p>
            <div className="mt-3 break-all rounded-lg bg-paper px-3 py-2 text-[12px] text-gray700">
              {url}
            </div>
          </>
        ) : (
          <form onSubmit={submit}>
            <h1 className="text-base font-black text-ink">
              산출물 증빙을 등록해주세요
            </h1>
            <p className="mt-1 text-[12px] text-gray500">
              요청받은 대표 산출물의 증빙 URL을 등록해 주세요.
            </p>
            <input
              type="url"
              inputMode="url"
              autoComplete="url"
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                setSubmitError(null);
              }}
              placeholder="증빙 URL 입력 (예: https://example.com/result)"
              className="mt-3 w-full rounded-lg border border-gray300 px-3 py-2.5 text-[13px] outline-none focus:border-ink"
            />
            <button
              type="submit"
              disabled={!url.trim() || submitting}
              className="mt-3 h-12 w-full rounded-lg bg-ink text-[14px] font-bold text-white disabled:opacity-40"
            >
              {submitting ? "제출 중…" : "제출하기"}
            </button>
            {submitError && (
              <p className="mt-3 text-[12px] text-amber800" role="alert">
                {submitError}
              </p>
            )}
          </form>
        )}
      </div>
    </AgencyShell>
  );
}
