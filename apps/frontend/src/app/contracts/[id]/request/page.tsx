"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { ConfirmModal } from "@/components/ConfirmModal";
import { useAsync } from "@/lib/hooks";
import { adapter } from "@/lib/adapter";

/* ⑥ 조정 요청서 미리보기 (주경로) — 선택한 문구 확인·발송 전 최종확인.
   톤완충 자유입력(P1)은 접힌 부가 경로로 분리. */
export default function RequestPreviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const state = useAsync(() => adapter.getContract(id), [id]);
  const [confirm, setConfirm] = useState(false);

  const items = useMemo(() => {
    if (state.status !== "ready") return [];
    return state.data.clauses
      .filter((c) => c.userChoice === "REQUEST" || c.userChoice === "COMPROMISE")
      .map((c) => {
        const s = c.suggestions.find((x) => x.choice === c.userChoice)!;
        return { id: c.id, title: c.title, text: s.text };
      });
  }, [state]);

  return (
    <AppScreen
      title="조정 요청서 미리보기"
      backHref={`/contracts/${id}`}
      footer={
        <CTAButton onClick={() => setConfirm(true)}>대행사에 발송하기</CTAButton>
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
                className="rounded-lg bg-paper px-3.5 py-3 text-[13px]"
              >
                <span className="font-bold text-ink">{it.title}</span>
                <span className="text-gray500"> → </span>
                <span className="text-gray700">“{it.text}”</span>
              </div>
            ))}
          </div>

          {/* 톤 완충기 — P1 부가 경로 (접힘) */}
          <ToneBuffer />

          <p className="text-[11px] leading-relaxed text-gray500">
            발송 전 미리보기예요. 대행사는 회원가입 없이 토큰 링크로 이 요청서를
            열람합니다.
          </p>
        </div>
      )}

      <ConfirmModal
        open={confirm}
        title="이대로 대행사에 보낼까요?"
        body={
          <>
            조항 {items.length}건의 조정 요청이 대행사에게 전달됩니다. 발송 후에는
            같은 요청서를 다시 수정할 수 없어요.
          </>
        }
        confirmLabel="네, 발송할게요"
        cancelLabel="다시 볼게요"
        onCancel={() => setConfirm(false)}
        onConfirm={() => router.push(`/contracts/${id}/responses`)}
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
