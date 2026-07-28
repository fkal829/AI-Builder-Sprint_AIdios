"use client";

/* 비가역 행동 전 확인 (설계 원칙 #5) — 발송/서명 전 최종 확인 모달. */
import type { ReactNode } from "react";

export function ConfirmModal({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel = "다시 볼게요",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-4 md:items-center"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-[400px] animate-fade-up rounded-2xl border-2 border-ink bg-white p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 text-xs font-medium text-gray500">
          서명 전 최종 확인
        </div>
        <h2 className="text-base font-black text-ink">{title}</h2>
        <div className="mt-2 text-[13px] leading-relaxed text-gray700">{body}</div>
        <div className="mt-4 flex gap-2">
          <button
            onClick={onCancel}
            className="h-11 flex-1 rounded-lg border-2 border-ink bg-white text-[13px] font-bold text-ink"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className="h-11 flex-1 rounded-lg bg-ink text-[13px] font-bold text-white"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
