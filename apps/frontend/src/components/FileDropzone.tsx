"use client";

import { useRef, useState } from "react";

/** 바이트를 사람이 읽기 쉬운 크기로 변환 */
function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* PDF 드롭존 — 계약서 업로드(신규)와 수정 계약서 업로드에서 함께 쓴다.
   기본 / 마우스 올림 / 끌어다 놓는 중 세 상태를 다른 강도로 구분해 보여준다.
   마우스만 올렸을 때는 문구를 바꾸지 않는다. 바꾸면 이미 놓은 것으로 오인한다. */
export function FileDropzone({
  file,
  onFile,
  onError,
}: {
  file: File | null;
  onFile: (file: File) => void;
  onError: (message: string) => void;
}) {
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  /** 파일 검증 후 상위로 전달 — 파일 선택/드롭 공통 진입점 */
  const acceptFile = (f: File | undefined | null) => {
    if (!f) return;
    const isPdf =
      f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      onError("PDF 파일만 올릴 수 있어요.");
      return;
    }
    onFile(f);
  };

  return (
    <>
      {/* 숨겨진 실제 파일 입력 — 드롭존 클릭 시 열림 */}
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(e) => {
          acceptFile(e.target.files?.[0]);
          // 같은 파일 재선택도 감지되도록 초기화
          e.target.value = "";
        }}
      />

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          setDragActive(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          acceptFile(e.dataTransfer.files?.[0]);
        }}
        className={`flex h-32 w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed text-sm transition ${
          dragActive
            ? "border-brand700 bg-brand100 text-brand800"
            : file
              ? "border-brand400 bg-brand50 text-brand700"
              : "border-neutral300 text-neutral500 hover:border-brand400 hover:bg-subtle hover:text-neutral700"
        }`}
      >
        {dragActive ? (
          <>
            <span className="text-2xl">⤓</span>
            <span className="font-bold">여기에 놓으면 업로드돼요</span>
          </>
        ) : file ? (
          <>
            <span className="text-2xl">✓</span>
            <span className="font-bold">{file.name}</span>
            <span className="text-[11px]">
              {formatBytes(file.size)} · 다시 선택하려면 클릭
            </span>
          </>
        ) : (
          <>
            <span className="text-2xl">＋</span>
            <span>PDF를 클릭해서 선택하거나 여기로 끌어다 놓으세요</span>
          </>
        )}
      </button>
    </>
  );
}
