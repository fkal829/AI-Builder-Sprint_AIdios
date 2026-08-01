"use client";

/* 대행사 전달 링크 카드 — 자동 발송이 아니므로 사용자가 복사해 직접 보낸다.
   요청서 미리보기(생성 직후)와 응답 대기 화면(다시 보기) 양쪽에서 쓴다. */
import { useEffect, useState } from "react";
import {
  absolutePublicUrl,
  loadPublicLink,
  type PublicLink,
} from "@/lib/publicLink";

export function PublicLinkCard({
  link,
  title,
  note,
}: {
  link: PublicLink;
  title: string;
  note: string;
}) {
  const [copied, setCopied] = useState(false);
  const url = absolutePublicUrl(link.publicUrl);

  const copy = () => {
    navigator.clipboard?.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="rounded-xl border-2 border-brand700 bg-brand50 p-4">
      <h2 className="text-sm font-black text-ink">{title}</h2>
      <p className="mt-1 text-[11px] leading-relaxed text-neutral700">{note}</p>
      <div className="mt-3 flex items-stretch gap-2">
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="min-w-0 flex-1 break-all rounded-lg bg-white p-3 text-xs text-brand700 underline"
        >
          {url}
        </a>
        {/* 링크 바로 옆 복사 아이콘 — 긴 URL을 드래그하지 않고 바로 복사 */}
        <button
          type="button"
          onClick={copy}
          aria-label="링크 복사"
          className="flex w-11 flex-none items-center justify-center rounded-lg bg-white text-neutral500 transition hover:text-ink"
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
        </button>
      </div>
      {/* 눌렀는지 확실히 보이도록 복사 후 잠시 검정 → 회색으로 바뀐다 */}
      <button
        type="button"
        onClick={copy}
        className={`mt-2 h-10 w-full rounded-lg text-[13px] font-bold text-white transition ${
          copied ? "bg-neutral500" : "bg-ink hover:bg-ink/90"
        }`}
      >
        {copied ? "✓ 복사됐어요" : "링크 복사하기"}
      </button>
      <p className="mt-2 text-[10px] text-neutral500">
        {link.expiresAt.slice(0, 16).replace("T", " ")}까지 유효
      </p>
    </div>
  );
}

/** 복사 아이콘 — 네모 두 개가 겹친 형태 */
function CopyIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

/** 복사 직후 잠시 아이콘 자리를 대신하는 체크 */
function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

/** 이 브라우저에 저장된 전달 링크가 있으면 보여준다. 없으면 아무것도 렌더하지 않는다. */
export function SavedPublicLink({
  contractId,
  title,
  note,
}: {
  contractId: string;
  title: string;
  note: string;
}) {
  const [link, setLink] = useState<PublicLink | null>(null);
  useEffect(() => {
    // localStorage는 클라이언트 전용이라 마운트 후 1회 읽는다
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLink(loadPublicLink(contractId));
  }, [contractId]);

  if (!link) return null;
  return <PublicLinkCard link={link} title={title} note={note} />;
}
