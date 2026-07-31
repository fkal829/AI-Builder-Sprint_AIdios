"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { adapter, type RevisedContractReview } from "@/lib/adapter";

export default function RevisedContractPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [review, setReview] = useState<RevisedContractReview | null>(null);
  const [confirmedIds, setConfirmedIds] = useState<Set<string>>(new Set());
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const uploadAndCompare = async () => {
    if (!file || working) return;
    setWorking(true);
    setError(null);
    try {
      const adjustmentId =
        window.localStorage.getItem(`dandi:last-adjustment:${id}`) ?? "mock-adjustment";
      const document = await adapter.uploadRevisedContract(id, file);
      const nextReview = await adapter.createRevisedContractReview(
        id,
        adjustmentId,
        document.id,
      );
      setReview(nextReview);
      setConfirmedIds(
        new Set(
          nextReview.items
            .filter((item) => item.matchStatus === "MATCHED")
            .map((item) => item.reviewItemId),
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "수정 계약서를 대조하지 못했습니다.");
    } finally {
      setWorking(false);
    }
  };

  const confirmReview = async () => {
    if (!review || confirmedIds.size !== review.items.length || working) return;
    setWorking(true);
    setError(null);
    try {
      const confirmed = await adapter.confirmRevisedContractReview(
        id,
        review.id,
        [...confirmedIds],
      );
      window.localStorage.setItem(`dandi:confirmed-revision:${id}`, confirmed.id);
      router.push(`/contracts/${id}/signature`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "수정 계약서를 확정하지 못했습니다.");
    } finally {
      setWorking(false);
    }
  };

  const toggle = (reviewItemId: string) => {
    setConfirmedIds((current) => {
      const next = new Set(current);
      if (next.has(reviewItemId)) next.delete(reviewItemId);
      else next.add(reviewItemId);
      return next;
    });
  };

  const allConfirmed = review !== null && confirmedIds.size === review.items.length;

  return (
    <AppScreen
      title="수정 계약서 확인"
      backHref={`/contracts/${id}/responses`}
      footer={
        review ? (
          <CTAButton onClick={confirmReview} disabled={!allConfirmed || working}>
            {working ? "확인 중…" : "이 수정 계약서로 서명 준비하기"}
          </CTAButton>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-4">
        <div className="rounded-xl border border-gray200 bg-white p-4">
          <h2 className="text-sm font-black text-ink">대행사가 다시 보낸 PDF를 올려주세요</h2>
          <p className="mt-1.5 text-[12px] leading-relaxed text-gray500">
            대행사는 이메일이나 메신저로 수정 계약서를 전달합니다. 단디계약은 계약서를
            대신 만들지 않고, 확정한 조정 내용이 수정본에 들어갔는지 대조합니다.
          </p>
          <input
            type="file"
            accept="application/pdf,.pdf"
            className="mt-3 block w-full text-xs text-gray700"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            disabled={!file || working}
            onClick={uploadAndCompare}
            className="mt-3 h-10 w-full rounded-lg bg-ink text-[13px] font-bold text-white disabled:opacity-40"
          >
            {working && !review ? "대조 중…" : "업로드하고 합의 내용 대조하기"}
          </button>
        </div>

        {review && (
          <section className="flex flex-col gap-2.5">
            <div>
              <h2 className="text-sm font-black text-ink">조항별 반영 결과</h2>
              <p className="mt-1 text-[11px] leading-relaxed text-gray500">
                정확히 찾은 문구도 직접 확인해주세요. 표현이 다른 항목은 자동으로
                합의됐다고 판단하지 않습니다.
              </p>
            </div>
            {review.items.map((item) => (
              <label
                key={item.reviewItemId}
                className="flex cursor-pointer gap-3 rounded-xl border border-gray200 bg-white p-4"
              >
                <input
                  type="checkbox"
                  checked={confirmedIds.has(item.reviewItemId)}
                  onChange={() => toggle(item.reviewItemId)}
                  className="mt-1 h-4 w-4 accent-ink"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <b className="text-[12px] text-ink">최종 합의 문구</b>
                    <span
                      className={`rounded px-2 py-1 text-[10px] font-bold ${
                        item.matchStatus === "MATCHED"
                          ? "bg-amber50 text-amber700"
                          : "bg-gray100 text-gray700"
                      }`}
                    >
                      {item.matchStatus === "MATCHED" ? "문구 확인" : "직접 확인 필요"}
                    </span>
                  </span>
                  <span className="mt-1 block text-[13px] font-bold leading-relaxed text-ink">
                    “{item.expectedText}”
                  </span>
                  {item.sourceText ? (
                    <span className="mt-2 block rounded-md bg-paper px-3 py-2 text-[11px] leading-relaxed text-gray700">
                      수정본 {item.sourcePage}쪽: “{item.sourceText}”
                    </span>
                  ) : (
                    <span className="mt-2 block text-[11px] text-gray500">
                      같은 문구를 찾지 못했습니다. PDF 원문을 직접 확인한 뒤 체크해주세요.
                    </span>
                  )}
                </span>
              </label>
            ))}
          </section>
        )}

        {error && <p className="text-xs font-bold text-red-700">{error}</p>}
      </div>
    </AppScreen>
  );
}
