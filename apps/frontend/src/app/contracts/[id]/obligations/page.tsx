"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { Disclaimer } from "@/components/Bits";
import { EmptyState } from "@/components/EmptyState";
import { useAsync } from "@/lib/hooks";
import { adapter, type LiveObligation } from "@/lib/adapter";

/* ⑩ 산출물 증빙 링크 생성·조회·승인/이의를 실제 API에 연결한다. */
export default function ObligationsPage() {
  const { id } = useParams<{ id: string }>();
  const state = useAsync(() => adapter.getObligation(id), [id]);
  const [updated, setUpdated] = useState<LiveObligation | null>(null);
  const [publicLink, setPublicLink] = useState<{ url: string; expiresAt: string } | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const obligation = updated ?? (state.status === "ready" ? state.data : null);

  const createEvidenceLink = async () => {
    if (!obligation || working) return;
    setWorking(true);
    setError(null);
    try {
      const link = await adapter.createObligationEvidenceLink(id, obligation.id);
      setPublicLink({ url: link.publicUrl, expiresAt: link.expiresAt });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "증빙 제출 링크를 만들지 못했습니다.");
    } finally {
      setWorking(false);
    }
  };

  const review = async (decision: "APPROVED" | "DISPUTED") => {
    if (!obligation || working) return;
    setWorking(true);
    setError(null);
    try {
      setUpdated(await adapter.reviewObligation(id, obligation.id, decision));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "증빙 검토 결과를 저장하지 못했습니다.");
    } finally {
      setWorking(false);
    }
  };

  return (
    <AppScreen
      title="산출물 증빙 확인"
      size="sm"
      backHref="/dashboard"
      footer={
        <CTAButton href={`/contracts/${id}/renewal`} variant="secondary">
          만료·재계약 검토로
        </CTAButton>
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>
      )}
      {state.status === "error" && (
        <p className="py-10 text-center text-sm font-bold text-brand800">⚠ {state.error}</p>
      )}
      {state.status === "ready" && !obligation && (
        <EmptyState
          title="확인할 대표 산출물이 없어요"
          body="원문 근거로 확인된 대표 산출물이 생성되면 이곳에서 증빙을 요청할 수 있어요."
        />
      )}
      {obligation && (
        <div className="flex flex-col gap-4">
          <h2 className="text-base font-black text-ink">{obligation.title}</h2>
          <div className="rounded-lg bg-subtle p-3.5">
            <div className="text-[11px] text-neutral500">기한 {obligation.dueDate}</div>
            <p className="mt-2 text-[12px] leading-relaxed text-neutral700">
              계약서 {obligation.sourcePage}쪽: “{obligation.sourceText}”
            </p>
            <div className="mt-1 text-[10px] text-neutral500">
              원문 근거 확신도 {Math.round(obligation.confidence * 100)}%
            </div>
            {obligation.evidenceUrl && (
              <a
                href={obligation.evidenceUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-[11px] text-brand700 underline underline-offset-2"
              >
                제출된 증빙 URL 보기 →
              </a>
            )}
          </div>

          {obligation.status === "PENDING" && (
            <div className="rounded-xl border border-neutral200 bg-white p-4">
              <h3 className="text-sm font-black text-ink">대행사 증빙 제출 링크</h3>
              <p className="mt-1 text-[11px] leading-relaxed text-neutral500">
                링크를 만든 뒤 복사해 기존 이메일이나 메신저로 직접 전달해주세요.
              </p>
              {publicLink ? (
                <div className="mt-3 rounded-lg bg-subtle p-3">
                  <a href={publicLink.url} className="break-all text-xs text-brand700 underline">
                    {publicLink.url}
                  </a>
                  <p className="mt-1 text-[10px] text-neutral500">
                    {publicLink.expiresAt.slice(0, 16).replace("T", " ")}까지 유효
                  </p>
                </div>
              ) : (
                <CTAButton onClick={createEvidenceLink} disabled={working}>
                  {working ? "링크 만드는 중…" : "증빙 제출 링크 만들기"}
                </CTAButton>
              )}
            </div>
          )}

          {obligation.status === "SUBMITTED" && (
            <div className="flex flex-col gap-2">
              <CTAButton onClick={() => review("APPROVED")} disabled={working}>
                {working ? "저장 중…" : "확인 완료"}
              </CTAButton>
              <button
                type="button"
                disabled={working}
                onClick={() => review("DISPUTED")}
                className="h-11 rounded-lg border border-neutral300 bg-white text-[13px] font-bold text-neutral500 disabled:opacity-40"
              >
                이의 있어요
              </button>
            </div>
          )}

          {obligation.status === "APPROVED" && (
            <div className="rounded-lg border-2 border-brand700 bg-brand50 px-4 py-3 text-center">
              <div className="text-sm font-black text-brand700">지급 조건 충족으로 표시됨</div>
            </div>
          )}
          {obligation.status === "DISPUTED" && (
            <div className="rounded-lg border border-neutral500 bg-neutral100 px-4 py-3 text-center">
              <div className="text-sm font-bold text-neutral700">이의 있음으로 기록됐어요</div>
            </div>
          )}

          <a
            href={`/contracts/${id}/performance`}
            className="flex items-center justify-between rounded-lg border border-neutral300 bg-white px-3.5 py-3 text-[13px] font-bold text-ink hover:bg-subtle"
          >
            광고효과 관리 보기 <span className="text-neutral500">›</span>
          </a>

          {error && <p className="text-xs font-bold text-red-700">{error}</p>}
          <Disclaimer>
            확인 완료는 계약상 지급 조건 충족 표시이며 실제 송금·결제를 실행하지 않습니다.
          </Disclaimer>
        </div>
      )}
    </AppScreen>
  );
}
