"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { AppScreen, CTAButton } from "@/components/AppScreen";
import { Timeline } from "@/components/Timeline";
import { useAsync } from "@/lib/hooks";
import { adapter, isUsingMock, type LiveSignature } from "@/lib/adapter";
import { MODUSIGN_STATUS_LABEL, modusignStep } from "@/lib/status";

type SignerFields = {
  ownerName: string;
  ownerEmail: string;
  agencyName: string;
  agencyEmail: string;
};

const EMPTY_SIGNERS: SignerFields = {
  ownerName: "",
  ownerEmail: "",
  agencyName: "",
  agencyEmail: "",
};

/* ⑨ 수정 계약서 확정본으로 모두싸인 초안을 만들고 서명 상태를 확인한다(§6.9).
   초안 생성만으로 발송되지 않으며, 사용자가 모두싸인 편집기에서 다시 확인하고 보낸다. */
export default function SignaturePage() {
  const { id } = useParams<{ id: string }>();
  const state = useAsync(() => adapter.getSignatureView(id), [id]);
  const [signers, setSigners] = useState<SignerFields>(EMPTY_SIGNERS);
  const [creating, setCreating] = useState(false);
  const [editorUrl, setEditorUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isComplete =
    signers.ownerName.trim().length >= 2 &&
    signers.agencyName.trim().length >= 2 &&
    signers.ownerEmail.includes("@") &&
    signers.agencyEmail.includes("@") &&
    signers.ownerEmail.trim() !== signers.agencyEmail.trim();
  const canCreateDraft = isUsingMock || (state.status === "ready"
    && (
      state.data.signature === null
      || state.data.signature.status === "FAILED"
      || state.data.signature.status === "ABORTED"
    ));

  const createDraft = async () => {
    if (!isComplete || creating) return;
    setCreating(true);
    setError(null);
    try {
      const storedReviewId = window.localStorage.getItem(`dandi:confirmed-revision:${id}`);
      const latestReview = storedReviewId
        ? null
        : await adapter.getLatestRevisedContractReview(id);
      if (latestReview && latestReview.status !== "CONFIRMED") {
        throw new Error("수정 계약서 대조를 모두 확인한 뒤 서명을 준비해주세요.");
      }
      const confirmedReviewId = storedReviewId ?? latestReview?.id;
      if (!confirmedReviewId) {
        throw new Error("확정한 수정 계약서를 찾지 못했습니다.");
      }
      const draft = await adapter.createSignatureDraft(id, confirmedReviewId, [
        {
          role: "OWNER",
          name: signers.ownerName,
          email: signers.ownerEmail,
        },
        {
          role: "AGENCY",
          name: signers.agencyName,
          email: signers.agencyEmail,
        },
      ]);
      setEditorUrl(draft.editorUrl);
      window.localStorage.removeItem(`dandi:confirmed-revision:${id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "모두싸인 초안을 만들지 못했습니다.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <AppScreen
      title="서명 준비 · 상태"
      backHref="/dashboard"
      footer={
        state.status === "ready" && state.data.signature?.modusignStatus === "COMPLETED" ? (
          <CTAButton href={`/contracts/${id}/performance`}>
            리포트 올리고 이행 확인하기
          </CTAButton>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-5">
        {canCreateDraft && !editorUrl && (
          <SignatureDraftForm
            signers={signers}
            onChange={setSigners}
            onCreate={createDraft}
            disabled={!isComplete || creating}
            creating={creating}
          />
        )}

        {editorUrl && (
          <div className="rounded-xl border border-brand400 bg-brand50 p-4">
            <h2 className="text-sm font-black text-ink">모두싸인 초안을 만들었습니다</h2>
            <p className="mt-1.5 text-[12px] leading-relaxed text-neutral700">
              아직 상대방에게 발송되지 않았습니다. 편집기에서 수정 계약서와 서명 위치를
              다시 확인한 뒤 직접 발송해주세요.
            </p>
            {isUsingMock ? (
              <p className="mt-3 text-xs font-bold text-brand800">
                목업 모드에서는 실제 모두싸인 편집기를 열지 않습니다.
              </p>
            ) : (
              <a
                href={editorUrl}
                className="mt-3 flex h-11 items-center justify-center rounded-lg bg-ink text-sm font-bold text-white"
              >
                모두싸인 편집기 열기
              </a>
            )}
          </div>
        )}

        {error && <p className="text-xs font-bold text-red-700">{error}</p>}

        {state.status === "loading" && (
          <p className="py-10 text-center text-sm text-neutral500">불러오는 중…</p>
        )}
        {state.status === "error" && (
          <p className="py-10 text-center text-sm font-bold text-brand800">⚠ {state.error}</p>
        )}

        {state.status === "ready" && (
          <>
            {state.data.signature ? (
              <SignatureStatus sig={state.data.signature} />
            ) : (
              <div className="rounded-xl border border-neutral200 bg-white p-4 text-sm text-neutral500">
                아직 생성된 모두싸인 초안이 없습니다.
              </div>
            )}
            <div>
              <h3 className="mb-3 text-[13px] font-bold text-neutral700">감사 타임라인</h3>
              <Timeline events={state.data.timeline} />
            </div>
          </>
        )}
      </div>
    </AppScreen>
  );
}

function SignatureDraftForm({
  signers,
  onChange,
  onCreate,
  disabled,
  creating,
}: {
  signers: SignerFields;
  onChange: (value: SignerFields) => void;
  onCreate: () => void;
  disabled: boolean;
  creating: boolean;
}) {
  const fields: { key: keyof SignerFields; label: string; type: "text" | "email" }[] = [
    { key: "ownerName", label: "사장님 이름", type: "text" },
    { key: "ownerEmail", label: "사장님 이메일", type: "email" },
    { key: "agencyName", label: "대행사 서명자 이름", type: "text" },
    { key: "agencyEmail", label: "대행사 이메일", type: "email" },
  ];

  return (
    <section className="rounded-xl border border-neutral200 bg-white p-4">
      <h2 className="text-sm font-black text-ink">수정 계약서로 서명 준비</h2>
      <p className="mt-1.5 text-[12px] leading-relaxed text-neutral500">
        방금 확인한 수정 PDF 원본이 그대로 모두싸인 초안에 들어갑니다. 연락처는 초안 생성
        요청에만 사용하며 브라우저에 저장하지 않습니다.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {fields.map((field) => (
          <label key={field.key} className="flex flex-col gap-1.5 text-xs font-bold text-neutral700">
            {field.label}
            <input
              type={field.type}
              value={signers[field.key]}
              onChange={(event) => onChange({ ...signers, [field.key]: event.target.value })}
              autoComplete="off"
              maxLength={field.type === "email" ? 254 : 30}
              className="h-11 rounded-lg border border-neutral300 bg-white px-3 text-sm text-ink outline-none focus:border-ink"
            />
          </label>
        ))}
      </div>
      <button
        type="button"
        onClick={onCreate}
        disabled={disabled}
        className="mt-4 h-11 w-full rounded-lg bg-ink text-sm font-bold text-white disabled:opacity-40"
      >
        {creating ? "초안 만드는 중…" : "수정 계약서로 모두싸인 초안 만들기"}
      </button>
      <p className="mt-2 text-[10px] leading-relaxed text-neutral500">
        이 버튼은 서명 요청을 자동 발송하지 않습니다.
      </p>
    </section>
  );
}

function SignatureStatus({ sig }: { sig: LiveSignature }) {
  const externalStatus = sig.modusignStatus ?? "DRAFT";
  const step = modusignStep(externalStatus);
  const labels = ["처리 중", "서명 진행 중", "서명 완료"];

  return (
    <div className="rounded-xl border border-neutral200 bg-white p-4">
      <div className="text-sm font-black text-ink">{MODUSIGN_STATUS_LABEL[externalStatus]}</div>
      <div className="mt-3 flex gap-1.5">
        {[0, 1, 2].map((index) => (
          <div
            key={index}
            className={`h-1.5 flex-1 rounded-full ${
              index < step ? "bg-brand700" : index === step ? "bg-brand400" : "bg-neutral200"
            }`}
          />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-neutral500">
        {labels.map((label, index) => (
          <span key={label} className={index === step ? "font-bold text-brand700" : ""}>
            {label}
          </span>
        ))}
      </div>
      <div className="mt-3 text-xs text-neutral700">내부 처리 상태: {signatureStatusLabel(sig.status)}</div>
      {sig.documentId && (
        <div className="mt-1 text-[10px] text-neutral500">모두싸인 문서 ID: {sig.documentId}</div>
      )}
    </div>
  );
}

function signatureStatusLabel(status: LiveSignature["status"]): string {
  const labels: Record<LiveSignature["status"], string> = {
    REQUEST_READY: "초안 생성 대기",
    REQUESTING: "초안 생성 중",
    EDITING: "편집기 확인 중",
    SIGNING: "양측 서명 진행 중",
    COMPLETED: "양측 서명 완료",
    ABORTED: "서명 중단",
    FAILED: "처리 실패",
  };
  return labels[status];
}
