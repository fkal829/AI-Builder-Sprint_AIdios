/* ===========================================================================
   상태 → 쉬운 한국어 매핑 (기획안 §6.9, §11, UX원칙)
   외부/내부 enum은 types.ts에 그대로 두고, 여기서만 표시 문구·색을 매핑.
   색 규칙: 경고색·빨강 없음. 거절/원안유지/대기는 gray, 진행/합의는 amber.
   =========================================================================== */
import type {
  ClauseCardState,
  ContractStatus,
  ModusignStatus,
  ObligationStatus,
  ReviewSignalType,
  AdjustmentRequestStatus,
} from "./types";

/** 배지 톤 — Tailwind 유틸 클래스 묶음. red 계열 없음. */
export type BadgeTone = "gray" | "amberSoft" | "amberMid" | "amberStrong";

export interface BadgeStyle {
  /** 배지 자체(text/bg) */
  chip: string;
  /** 카드 컨테이너(bg/border) */
  card: string;
}

const TONES: Record<BadgeTone, BadgeStyle> = {
  // 미검토·발송대기·거절·원안유지 — 중립 회색
  gray: {
    chip: "text-gray700 bg-gray300",
    card: "bg-gray100 border-gray500",
  },
  // 원안 수용 선택 — 옅은 앰버
  amberSoft: {
    chip: "text-amber700 bg-amber100",
    card: "bg-amber50 border-amber200",
  },
  // 절충안·역제안 도착 — 중간 앰버
  amberMid: {
    chip: "text-amber800 bg-amber200",
    card: "bg-amber100 border-amber400",
  },
  // 요청안·합의 — 진한 앰버(채워짐)
  amberStrong: {
    chip: "text-white bg-amber700",
    card: "bg-amber200 border-amber600",
  },
};

export function toneStyle(tone: BadgeTone): BadgeStyle {
  return TONES[tone];
}

/* ------------------------- 조항 카드 8상태 (와이어프레임 2-1) ------------------------- */
export const CLAUSE_STATE_META: Record<
  ClauseCardState,
  { label: string; tone: BadgeTone; icon?: string }
> = {
  UNREVIEWED: { label: "미검토", tone: "gray" },
  ACCEPT_SELECTED: { label: "원안 수용 선택", tone: "amberSoft" },
  COMPROMISE_SELECTED: { label: "절충안 선택", tone: "amberMid" },
  REQUEST_SELECTED: { label: "요청안 선택", tone: "amberStrong" },
  SENT_WAITING: { label: "발송됨 · 대기", tone: "gray" },
  AGREED: { label: "합의", tone: "amberStrong", icon: "✓" },
  COUNTER_RECEIVED: { label: "역제안 도착", tone: "amberMid", icon: "↩" },
  KEPT_ORIGINAL: { label: "원안 유지", tone: "gray" },
};

/* ------------------------- 확인 신호 유형 (§6.4) ------------------------- */
export const SIGNAL_META: Record<ReviewSignalType, string> = {
  MISMATCH: "다름",
  NO_BASIS: "근거 없음",
  UNCLEAR: "명확하지 않음",
  MISSING: "빈칸",
  NEEDS_CHECK: "확인 필요",
};

/* ------------------------- 계약 내부 상태 → 표시 문구 (§11) ------------------------- */
export const CONTRACT_STATUS_LABEL: Record<ContractStatus, string> = {
  DRAFT: "작성 중",
  ANALYZING: "분석 중",
  REVIEW_REQUIRED: "검토 필요",
  NEGOTIATING: "조율 중",
  READY_TO_SIGN: "서명 준비",
  SIGNING: "서명 진행 중",
  SIGNED: "서명 완료",
  IN_PROGRESS: "진행중",
  COMPLETED: "완료",
  RENEWAL_DUE: "만료 임박",
};

/* ------------------------- 모두싸인 외부 상태 → 쉬운 한국어 (§6.9) ------------------------- */
export const MODUSIGN_STATUS_LABEL: Record<ModusignStatus, string> = {
  DRAFT: "준비 중",
  SCHEDULED: "예약됨",
  ON_PROCESSING: "처리 중",
  ON_GOING: "서명 진행 중",
  COMPLETED: "서명 완료",
  ABORTED: "중단",
  PROCESSING_FAILED: "처리 실패",
};

/** 모두싸인 3단계 진행 바 인덱스 (처리 중 / 서명 진행 중 / 서명 완료) */
export function modusignStep(status: ModusignStatus): 0 | 1 | 2 {
  if (status === "COMPLETED") return 2;
  if (status === "ON_GOING") return 1;
  return 0;
}

/* ------------------------- 이행 항목 상태 (§6.11) ------------------------- */
export const OBLIGATION_STATUS_LABEL: Record<ObligationStatus, string> = {
  PENDING: "대기",
  SUBMITTED: "제출됨",
  APPROVED: "확인 완료",
  DISPUTED: "이의 있음",
};

/* ------------------------- 조정 요청 상태 (§11) ------------------------- */
export const ADJUSTMENT_STATUS_LABEL: Record<AdjustmentRequestStatus, string> = {
  DRAFT: "작성 중",
  SENT: "발송됨",
  OPENED: "열람됨",
  RESPONDED: "응답 완료",
  CONFIRMED: "확정",
  EXPIRED: "만료됨",
};
