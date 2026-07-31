/* ===========================================================================
   상태 → 쉬운 한국어 매핑 (기획안 §6.9, §11, UX원칙)
   외부/내부 enum은 types.ts에 그대로 두고, 여기서만 표시 문구·색을 매핑.

   색 규칙: 경고색·빨강 없음. 색조가 아니라 무게로 구분한다.
     윤곽·점선 = 아직 확정 아님 (미검토·대기·내 선택)
     채움      = 확정됐거나 내가 볼 차례 (원안유지·역제안 도착·합의)
   같은 규칙이 LayerBlock의 층위 구분에도 그대로 적용된다.
   =========================================================================== */
import type {
  ClauseCardState,
  ContractStatus,
  ModusignStatus,
  ObligationStatus,
  ReviewSignalType,
  AdjustmentRequestStatus,
} from "./types";

/** 배지 톤 — Tailwind 유틸 클래스 묶음. red 계열 없음.
    앞의 넷은 윤곽(미확정), 뒤의 셋은 채움(확정·내 차례). */
export type BadgeTone =
  | "unseen"
  | "waiting"
  | "pick"
  | "pickStrong"
  | "neutral"
  | "active"
  | "done";

export interface BadgeStyle {
  /** 배지 자체(text/bg) */
  chip: string;
  /** 카드 컨테이너(bg/border) */
  card: string;
}

/* chip은 전부 1px 테두리를 가진다. 채움 배지의 테두리를 transparent로 두어야
   한 줄에 섞여 놓였을 때 높이가 어긋나지 않는다. */
const TONES: Record<BadgeTone, BadgeStyle> = {
  // 미검토 — 점선. 아직 시작조차 안 했다는 뜻.
  unseen: {
    chip: "border border-dashed border-neutral300 text-neutral500",
    card: "border-dashed bg-white border-neutral300",
  },
  // 발송됨·대기 — 실선 윤곽. 공이 상대에게 있음.
  waiting: {
    chip: "border border-neutral300 text-neutral700",
    card: "bg-white border-neutral400",
  },
  // 원안 수용·절충안 선택 — 내 선택이지만 아직 보내지 않음.
  pick: {
    chip: "border border-brand400 bg-brand600/5 text-brand700",
    card: "bg-brand50 border-brand300",
  },
  // 요청안 선택 — 가장 강한 요청. 테두리를 겹쳐 굵게 보이게 한다.
  pickStrong: {
    chip: "border border-brand600 bg-brand600/10 text-brand800 ring-1 ring-inset ring-brand600",
    card: "bg-brand50 border-brand600",
  },
  // 진행 중·원안 유지 — 확정이지만 내가 움직인 결과는 아님.
  neutral: {
    chip: "border border-transparent bg-neutral200 text-neutral700",
    card: "bg-neutral100 border-neutral400",
  },
  // 역제안 도착·만료 임박 — 내가 볼 차례. 목록에서 눈에 띄어야 함.
  // brand600은 흰 글자 대비가 4.45:1로 AA에 못 미쳐 brand700을 쓴다.
  active: {
    chip: "border border-transparent bg-brand700 text-white",
    card: "bg-brand100 border-brand600",
  },
  // 합의 — 최종 확정. 가장 짙은 채움.
  // brand800은 로고 색이라 워드마크 전용으로 두고, 배지는 brand900을 쓴다.
  done: {
    chip: "border border-transparent bg-brand900 text-white",
    card: "bg-brand200 border-brand800",
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
  UNREVIEWED: { label: "미검토", tone: "unseen" },
  ACCEPT_SELECTED: { label: "원안 수용 선택", tone: "pick" },
  COMPROMISE_SELECTED: { label: "절충안 선택", tone: "pick" },
  REQUEST_SELECTED: { label: "요청안 선택", tone: "pickStrong" },
  SENT_WAITING: { label: "발송됨 · 대기", tone: "waiting" },
  AGREED: { label: "합의", tone: "done", icon: "✓" },
  COUNTER_RECEIVED: { label: "역제안 도착", tone: "active", icon: "↩" },
  KEPT_ORIGINAL: { label: "원안 유지", tone: "neutral" },
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
