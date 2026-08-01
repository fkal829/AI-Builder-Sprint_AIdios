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

/* ⑥ 조정 요청서 미리보기 (주경로) — 선택한 문구 확인·발송 전 최종확인.
   톤완충 자유입력(P1)은 접힌 부가 경로로 분리. */
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
      const automaticItems = state.data.items.map((item) => {
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
          <CTAButton disabled={items.length === 0} onClick={() => setConfirm(true)}>
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

          {/* 톤 완충기 — P1 부가 경로 (접힘) */}
          {isUsingMock && <ToneBuffer />}

          <p className="text-[11px] leading-relaxed text-neutral500">
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

/* 톤 완충기 (P1) — 자유 입력은 허용하되 그대로 발송하지 않고 변환문 승인. */
function ToneBuffer() {
  const [raw, setRaw] = useState("");
  const [converted, setConverted] = useState<string | null>(null);

  const convert = () => {
    if (!raw.trim()) return;
    // 데모: 실제로는 Solar가 정중한 요청문으로 변환. 여기선 템플릿 예시.
    setConverted(
      `${raw.replace(/[ㅠㅜ!.]+$/g, "").trim()} — 조정을 정중히 제안드립니다.`,
    );
  };

  return (
    <details className="rounded-lg border border-neutral200 bg-white">
      <summary className="flex cursor-pointer items-center justify-between px-3.5 py-3 text-xs text-neutral500">
        <span>
          직접 문장을 써서 요청하고 싶다면
          <span className="ml-1.5 rounded bg-brand200 px-1.5 py-0.5 text-[10px] font-bold text-brand800">
            P1
          </span>
        </span>
        <span>펼치기</span>
      </summary>
      <div className="flex flex-col gap-2.5 border-t border-neutral200 px-3.5 py-3">
        <div className="rounded-md bg-neutral100 px-2.5 py-2 text-[12px] text-neutral700">
          직접 써주셔도 좋아요 (선택). 그대로 보내지 않고 정중하게 바꿔드려요.
        </div>
        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder="예) 5년은 너무 길어요 ㅠㅠ"
          className="min-h-16 rounded-lg border-2 border-ink px-3 py-2 text-[13px] outline-none"
        />
        <button
          onClick={convert}
          className="h-10 rounded-lg border-2 border-ink bg-white text-[13px] font-bold text-ink"
        >
          ↓ AI가 정중하게 바꿔드려요
        </button>
        {converted && (
          <>
            <div className="rounded-lg border-2 border-brand700 bg-brand50 px-3 py-2.5 text-[13px] leading-relaxed text-ink">
              “{converted}”
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setConverted(null)}
                className="h-10 flex-1 rounded-lg border border-neutral300 bg-white text-[12px] font-bold text-neutral700"
              >
                다시 쓸게요
              </button>
              <button className="h-10 flex-1 rounded-lg bg-ink text-[12px] font-bold text-white">
                이대로 승인
              </button>
            </div>
          </>
        )}
      </div>
    </details>
  );
}
