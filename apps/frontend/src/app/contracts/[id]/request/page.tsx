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
      // 브라우저에서 확정한 초안이 있으면 그 항목만 발송 대상으로 삼아
      // 사용자가 마지막으로 본 미리보기와 어긋나지 않게 한다.
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
            disabled={items.length === 0}
            onClick={() => setConfirm(true)}
          >
            대행사 전달 링크 만들기
          </CTAButton>
        )
      }
    >
      {state.status === "loading" && <PreviewSkeleton />}

      {/* 요청서를 못 불러왔거나 담긴 항목이 하나도 없으면 빈 화면만 남는다.
          이럴 때만 새로고침을 안내하고, 정상 표시될 때는 나타나지 않는다. */}
      {(state.status === "error"
        || (state.status === "ready" && items.length === 0)) && <ReloadNotice />}

      {state.status === "ready" && items.length > 0 && (
        <div className="flex flex-col gap-5">
          <div>
            <div className="text-[15px] font-black text-ink">
              대행사에 보낼 요청 {items.length}건
            </div>
            <p className="mt-1 text-[13px] text-neutral500">
              아래 문장 그대로 대행사에게 전달됩니다. 내용을 한 번 더 확인해주세요.
            </p>
          </div>

          <ol className="flex flex-col gap-3">
            {items.map((it, index) => (
              <li
                key={it.id}
                className="rounded-xl border border-neutral200 bg-white p-4 shadow-[0_1px_2px_rgba(16,54,90,0.04)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-2.5">
                    <span className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full bg-brand800 text-[11px] font-bold text-white">
                      {index + 1}
                    </span>
                    {/* 실 API에서는 조항 제목 자리에 AI 설명 문장이 통째로 들어온다.
                        줄임표로 자르지 않고 전문이 보이도록 줄바꿈시킨다. */}
                    <span className="min-w-0 flex-1 text-[14px] font-black leading-relaxed text-ink">
                      {it.title}
                    </span>
                  </div>
                  {it.manual && (
                    <button
                      type="button"
                      onClick={() => removeManualItem(it.id)}
                      className="flex-none rounded-md px-1.5 py-0.5 text-[12px] font-bold text-neutral500 hover:bg-subtle hover:text-brand700"
                    >
                      ✕ 삭제
                    </button>
                  )}
                </div>
                <p className="mt-3 border-l-2 border-brand300 pl-3.5 text-[15px] leading-loose text-neutral700">
                  {it.text}
                </p>
              </li>
            ))}
          </ol>

          <p className="text-[13px] leading-loose text-neutral500">
            링크 생성 전 미리보기예요. 링크를 만든 뒤 기존 이메일이나 메신저로 직접
            전달해주세요. 대행사는 회원가입 없이 요청서를 열람합니다.
          </p>
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

/** 요청서가 비어 보일 때만 뜨는 안내 — 새로고침으로 대부분 해결된다. */
function ReloadNotice() {
  return (
    <div className="rounded-xl border border-brand300 bg-brand50 px-5 py-6 text-center">
      <p className="text-[15px] font-black text-ink">요청서를 불러오지 못했어요</p>
      <p className="mt-2 text-[13px] leading-loose text-neutral700">
        잠시 연결이 끊겼을 수 있어요. 새로고침을 해주세요.
        <br />
        계속 비어 있으면 계약서 화면에서 조정할 조항을 먼저 확인해주세요.
      </p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="mt-4 h-11 rounded-lg bg-ink px-6 text-[13px] font-bold text-white"
      >
        새로고침
      </button>
    </div>
  );
}

/** 요청서를 불러오는 동안 보여줄 자리 — '불러오는 중…' 문구 대신 최종 레이아웃을 그대로 흉내낸다. */
function PreviewSkeleton() {
  return (
    <div className="flex animate-pulse flex-col gap-5" aria-hidden="true">
      <div>
        <div className="h-4 w-44 rounded bg-neutral200" />
        <div className="mt-2.5 h-3 w-72 rounded bg-neutral100" />
      </div>
      <div className="flex flex-col gap-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-xl border border-neutral200 bg-white p-4">
            <div className="flex items-center gap-2.5">
              <div className="h-6 w-6 flex-none rounded-full bg-neutral200" />
              <div className="h-3.5 w-32 rounded bg-neutral200" />
            </div>
            <div className="mt-4 flex flex-col gap-2 pl-3.5">
              <div className="h-3 w-full rounded bg-neutral100" />
              <div className="h-3 w-4/5 rounded bg-neutral100" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
