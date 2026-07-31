"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ConfirmModal } from "@/components/ConfirmModal";
import { useAsync } from "@/lib/hooks";
import { adapter, isUsingMock } from "@/lib/adapter";
import {
  loadRequestDraft,
  saveRequestDraft,
  type RequestDraft,
} from "@/lib/requestDraft";

/* ⑥ 조정 요청서 미리보기 (주경로) — 선택한 문구 확인·발송 전 최종확인.
   톤완충 자유입력(P1)은 접힌 부가 경로로 분리. */
export default function RequestPreviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getAdjustmentPreview(id), [id]);
  const [confirm, setConfirm] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sentLink, setSentLink] = useState<{ publicUrl: string; expiresAt: string } | null>(null);

  // 뷰어에서 인라인으로 작성한 초안이 있으면 우선 사용(없으면 목업 userChoice로 폴백)
  const [draft, setDraft] = useState<RequestDraft | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(loadRequestDraft(id));
  }, [id]);

  const items = useMemo(() => {
    if (state.status !== "ready") return [];
    if (!isUsingMock) {
      return state.data.items.map((item) => ({ ...item, manual: false }));
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

    const manualItems = Object.entries(draft ?? {})
      .filter(([, d]) => d.origin === "manual" && d.text.trim() !== "")
      .map(([clauseId, d]) => ({
        id: clauseId,
        title: d.title ?? "추가한 조항",
        text: d.text,
        manual: true,
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
        items.map((item) => item.id),
      );
      const link = await adapter.sendAdjustmentDraft(id, adjustment.id);
      window.localStorage.setItem(`dandi:last-adjustment:${id}`, adjustment.id);
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
        <p className="py-10 text-center text-sm text-gray500">불러오는 중…</p>
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
                className="flex items-start justify-between gap-2 rounded-lg bg-paper px-3.5 py-3 text-[13px]"
              >
                <div>
                  <span className="font-bold text-ink">{it.title}</span>
                  <span className="text-gray500"> → </span>
                  <span className="text-gray700">“{it.text}”</span>
                </div>
                {it.manual && (
                  <button
                    type="button"
                    onClick={() => removeManualItem(it.id)}
                    className="flex-none text-[11px] font-bold text-gray500 hover:text-amber700"
                  >
                    ✕ 삭제
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* 톤 완충기 — P1 부가 경로 (접힘) */}
          {isUsingMock && <ToneBuffer />}

          <p className="text-[11px] leading-relaxed text-gray500">
            링크 생성 전 미리보기예요. 링크를 만든 뒤 기존 이메일이나 메신저로 직접
            전달해주세요. 대행사는 회원가입 없이 요청서를 열람합니다.
          </p>
          {sentLink && (
            <div className="rounded-xl border-2 border-amber700 bg-amber50 p-4">
              <h2 className="text-sm font-black text-ink">대행사 전달 링크가 준비됐어요</h2>
              <p className="mt-1 text-[11px] leading-relaxed text-gray700">
                아직 자동 발송되지 않았습니다. 아래 링크를 복사해 대행사에 직접 보내주세요.
              </p>
              <a
                href={sentLink.publicUrl}
                className="mt-3 block break-all rounded-lg bg-white p-3 text-xs text-amber700 underline"
              >
                {sentLink.publicUrl}
              </a>
              <p className="mt-1 text-[10px] text-gray500">
                {sentLink.expiresAt.slice(0, 16).replace("T", " ")}까지 유효
              </p>
            </div>
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
    <details className="rounded-lg border border-gray200 bg-white">
      <summary className="flex cursor-pointer items-center justify-between px-3.5 py-3 text-xs text-gray500">
        <span>
          직접 문장을 써서 요청하고 싶다면
          <span className="ml-1.5 rounded bg-amber200 px-1.5 py-0.5 text-[10px] font-bold text-amber800">
            P1
          </span>
        </span>
        <span>펼치기</span>
      </summary>
      <div className="flex flex-col gap-2.5 border-t border-gray200 px-3.5 py-3">
        <div className="rounded-md bg-gray100 px-2.5 py-2 text-[12px] text-gray700">
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
            <div className="rounded-lg border-2 border-amber700 bg-amber50 px-3 py-2.5 text-[13px] leading-relaxed text-ink">
              “{converted}”
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setConverted(null)}
                className="h-10 flex-1 rounded-lg border border-gray300 bg-white text-[12px] font-bold text-gray700"
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
