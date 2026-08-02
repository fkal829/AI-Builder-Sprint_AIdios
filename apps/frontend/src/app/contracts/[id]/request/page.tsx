"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ConfirmModal } from "@/components/ConfirmModal";
import { PublicLinkCard } from "@/components/PublicLinkCard";
import { useAsync } from "@/lib/hooks";
import { adapter, isUsingMock } from "@/lib/adapter";
import {
  loadRequestDraft,
  saveRequestDraft,
  type RequestDraft,
} from "@/lib/requestDraft";
import { loadPublicLink, savePublicLink, type PublicLink } from "@/lib/publicLink";

/* ⑥ 조정 요청서 미리보기 (주경로) — 선택한 문구 확인·발송 전 최종확인. */
export default function RequestPreviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getAdjustmentPreview(id), [id]);
  const [confirm, setConfirm] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sentLink, setSentLink] = useState<PublicLink | null>(null);

  // 뷰어에서 인라인으로 작성한 초안이 있으면 우선 사용(없으면 목업 userChoice로 폴백)
  const [draft, setDraft] = useState<RequestDraft | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(loadRequestDraft(id));
  }, [id]);

  // 이미 만든 링크가 있으면 복원 — 새로고침·재진입해도 링크를 다시 볼 수 있고,
  // 같은 요청서로 링크를 또 만드는 일을 막는다.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSentLink(loadPublicLink(id));
  }, [id]);

  const items = useMemo(() => {
    if (state.status !== "ready") return [];
    const manualItems = Object.entries(draft ?? {})
      .filter(([, item]) => item.origin === "manual" && item.text.trim() !== "")
      .map(([clauseId, item]) => ({
        id: clauseId,
        title: item.title ?? "추가한 조항",
        text: item.text,
        manual: true,
      }));
    if (!isUsingMock) {
      // 서버에는 이전 브라우저/세션에서 선택했던 항목이 남아 있을 수 있다. 현재
      // 브라우저에서 확정한 초안이 있으면 그 항목만 발송 대상으로 삼아 1~4건 제한과
      // 사용자가 마지막으로 본 미리보기가 어긋나지 않게 한다.
      const automaticItems = state.data.items
        .filter((item) => {
          if (draft === null) return true;
          const saved = draft[item.id];
          return saved?.origin !== "manual"
            && (saved?.choice === "REQUEST" || saved?.choice === "COMPROMISE");
        })
        .map((item) => {
          const saved = draft?.[item.id];
          return {
            ...item,
            text: saved && saved.origin !== "manual" ? saved.text : item.text,
            manual: false,
          };
        });
      return [...automaticItems, ...manualItems];
    }

    const previewById = new Map(state.data.items.map((item) => [item.id, item]));
    const autoItems = Object.entries(draft ?? {})
      .filter(([, item]) =>
        item.origin !== "manual"
        && (item.choice === "REQUEST" || item.choice === "COMPROMISE"),
      )
      .map(([itemId, item]) => ({
        id: itemId,
        title: previewById.get(itemId)?.title ?? "확인한 조항",
        text: item.text,
        manual: false,
      }));

    return [...autoItems, ...manualItems];
  }, [state, draft]);

  // 추가 조항 삭제 — draft에서 제거하고 즉시 localStorage 갱신
  const removeManualItem = (clauseId: string) => {
    if (!draft) return;
    const next = { ...draft };
    delete next[clauseId];
    setDraft(next);
    saveRequestDraft(id, next);
  };

  const sendRequest = async () => {
    if (sending || items.length === 0) return;
    if (items.length > 4) {
      setSendError("한 요청서에는 조정 항목을 최대 4건까지 담을 수 있습니다.");
      return;
    }
    setSending(true);
    setSendError(null);
    try {
      const adjustment = await adapter.createAdjustmentDraft(
        id,
        items.filter((item) => !item.manual).map((item) => item.id),
        Object.fromEntries(
          items
            .filter((item) => !item.manual)
            .map((item) => [item.id, item.text]),
        ),
        items
          .filter((item) => item.manual)
          .map((item) => ({ documentClauseId: item.id, requestText: item.text })),
      );
      const link = await adapter.sendAdjustmentDraft(id, adjustment.id);
      window.localStorage.setItem(`dandi:last-adjustment:${id}`, adjustment.id);
      savePublicLink(id, link);
      setSentLink(link);
      setConfirm(false);
    } catch (error) {
      setSendError(
        error instanceof Error ? error.message : "조정 요청을 발송하지 못했습니다.",
      );
      setConfirm(false);
    } finally {
      setSending(false);
    }
  };

  return (
    <AppScreen
      title="조정 요청서 미리보기"
      backHref={`/contracts/${id}`}
      footer={
        sentLink ? (
          <CTAButton onClick={() => router.push(`/contracts/${id}/responses`)}>
            응답 대기 화면으로
          </CTAButton>
        ) : (
          <CTAButton
            disabled={items.length === 0 || items.length > 4}
            onClick={() => setConfirm(true)}
          >
            대행사 전달 링크 만들기
          </CTAButton>
        )
      }
    >
      {state.status === "loading" && (
        <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>
      )}

      {state.status === "ready" && (
        <div className="flex flex-col gap-4">
          <div className="text-sm font-black text-ink">
            요청서 미리보기 — 조항 {items.length}건
          </div>

          <div className="flex flex-col gap-2">
            {items.map((it) => (
              <div
                key={it.id}
                className="flex items-start justify-between gap-2 rounded-lg bg-subtle px-3.5 py-3 text-[13px]"
              >
                <div>
                  <span className="font-bold text-ink">{it.title}</span>
                  <span className="text-neutral500"> → </span>
                  <span className="text-neutral700">“{it.text}”</span>
                </div>
                {it.manual && (
                  <button
                    type="button"
                    onClick={() => removeManualItem(it.id)}
                    className="flex-none text-[11px] font-bold text-neutral500 hover:text-brand700"
                  >
                    ✕ 삭제
                  </button>
                )}
              </div>
            ))}
          </div>

          <p className="text-[11px] leading-relaxed text-neutral500">
            링크 생성 전 미리보기예요. 링크를 만든 뒤 기존 이메일이나 메신저로 직접
            전달해주세요. 대행사는 회원가입 없이 요청서를 열람합니다.
          </p>
          {items.length > 4 && (
            <p className="text-xs font-bold text-red-700">
              한 요청서에는 최대 4건만 담을 수 있어요. 이전 화면에서 요청 항목을 줄여주세요.
            </p>
          )}
          {sentLink && (
            <PublicLinkCard
              link={sentLink}
              title="대행사 전달 링크가 준비됐어요"
              note="아직 자동 발송되지 않았습니다. 아래 링크를 복사해 대행사에 직접 보내주세요."
            />
          )}
          {sendError && <p className="text-xs font-bold text-red-700">{sendError}</p>}
        </div>
      )}

      <ConfirmModal
        open={confirm}
        title="대행사 전달 링크를 만들까요?"
        body={
          <>
            조항 {items.length}건의 조정 요청 링크를 생성합니다. 링크 생성 후에는 같은
            요청서를 다시 수정할 수 없고, 대행사 전달은 직접 진행해야 합니다.
          </>
        }
        confirmLabel={sending ? "링크 만드는 중…" : "네, 링크를 만들게요"}
        cancelLabel="다시 볼게요"
        onCancel={() => setConfirm(false)}
        onConfirm={sendRequest}
      />
    </AppScreen>
  );
}
