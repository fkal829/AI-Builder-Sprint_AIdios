/* ===========================================================================
   단디계약 — 도메인 타입 (기획안 §10 데이터 모델 · §11 상태 머신)
   내부 enum은 원문 그대로 유지하고, 사용자 표시는 status.ts에서 매핑.
   =========================================================================== */

/* ---------------------------------- 상태 머신 (§11) ---------------------------------- */

/** 계약: DRAFT → ANALYZING → REVIEW_REQUIRED → NEGOTIATING → READY_TO_SIGN
 *        → SIGNING → SIGNED → IN_PROGRESS → COMPLETED / RENEWAL_DUE */
export type ContractStatus =
  | "DRAFT"
  | "ANALYZING"
  | "REVIEW_REQUIRED"
  | "NEGOTIATING"
  | "READY_TO_SIGN"
  | "SIGNING"
  | "SIGNED"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "RENEWAL_DUE";

/** 조정 요청: DRAFT → SENT → OPENED → RESPONDED → CONFIRMED / EXPIRED */
export type AdjustmentRequestStatus =
  | "DRAFT"
  | "SENT"
  | "OPENED"
  | "RESPONDED"
  | "CONFIRMED"
  | "EXPIRED";

/** 모두싸인 외부 상태 (§6.9) */
export type ModusignStatus =
  | "DRAFT"
  | "SCHEDULED"
  | "ON_PROCESSING"
  | "ON_GOING"
  | "COMPLETED"
  | "ABORTED"
  | "PROCESSING_FAILED";

/** 이행 항목: PENDING → SUBMITTED → APPROVED / DISPUTED */
export type ObligationStatus = "PENDING" | "SUBMITTED" | "APPROVED" | "DISPUTED";

/* ---------------------------------- 조항 카드 (§6.5) ---------------------------------- */

/** 조항 카드 목록 행 8상태 (와이어프레임 2-1) */
export type ClauseCardState =
  | "UNREVIEWED" // 미검토
  | "ACCEPT_SELECTED" // 원안 수용 선택
  | "COMPROMISE_SELECTED" // 절충안 선택
  | "REQUEST_SELECTED" // 요청안 선택
  | "SENT_WAITING" // 발송됨·대기
  | "AGREED" // 합의
  | "COUNTER_RECEIVED" // 역제안 도착
  | "KEPT_ORIGINAL"; // 원안 유지

/** 확인 신호 유형 (§6.4) — 판정이 아닌 "확인 신호" */
export type ReviewSignalType =
  | "MISMATCH" // 설명과 계약서가 다름
  | "NO_BASIS" // 계약서에서 근거를 찾지 못함
  | "UNCLEAR" // 조건이 명확하지 않음
  | "MISSING" // 빈칸·누락
  | "NEEDS_CHECK"; // 추가 확인이 필요함

/** 문구 선택지 3종 (§6.5) */
export type SuggestionChoice = "ACCEPT" | "COMPROMISE" | "REQUEST";

/** 대행사 응답 (§6.7) */
export type AgencyDecision = "ACCEPT" | "REJECT" | "COUNTER";

/* ---------------------------------- 근거 (§6.2) ---------------------------------- */

export interface SourceRef {
  page: number;
  text: string;
}

/* ---------------------------------- 엔티티 ---------------------------------- */

export interface UnderstoodTerm {
  durationText: string; // 이해한 계약기간
  monthlyAmount: string; // 이해한 월 납부액
  totalAmount: string; // 이해한 총 계약금액
  refundText: string; // 이해한 환불조건
  terminationText: string; // 이해한 중도해지 가능 여부
  sourceType: "USER_MEMORY"; // 사용자가 기억하고 이해한 설명
}

/** 5문항 정의 — 타이핑 없이 버튼 선택 (§6.1) */
export interface UnderstoodQuestion {
  key: keyof Omit<UnderstoodTerm, "sourceType">;
  title: string;
  options: string[];
}

export interface ExtractedField {
  field: string;
  label: string;
  value: string;
  source: SourceRef | null; // null = 원문 근거 없음(확정값으로 표시하지 않음)
  confidence: number; // 0~1
}

/* ---------------------------------- 계약서 원문 뷰어 (분석 결과 화면 좌측) ---------------------------------- */

/** 조항 주의 수준 — 이미지 레퍼런스의 고/중/저위험 3단계 */
export type ClauseRisk = "high" | "mid" | "low";

/** 원문 뷰어용 조항 하나 (제N조 단위) */
export interface DocClause {
  id: string; // "c1" … 페이지 내 앵커
  no: string; // "제1조"
  title: string; // "계약의 목적"
  body: string; // 조항 원문
  risk: ClauseRisk;
  note?: string; // 설문·계약 대조 기반 쉬운 코멘트 (고/중위험에만)
}

/** 계약서 원문 문서 전체 */
export interface ContractDocument {
  title: string; // "광고/마케팅 계약서"
  parties: string; // "파도담 카페 × 주식회사 브릿지웨이브"
  pageCount: number;
  pdfUrl: string; // 다운로드·미리보기 경로
  clauses: DocClause[];
}

export interface ClauseSuggestion {
  choice: SuggestionChoice;
  label: string;
  text: string; // 실제 발송 문구
}

export interface AgencyResponse {
  decision: AgencyDecision;
  counterText?: string; // 역제안 문구
  reason?: string; // 거절·역제안 사유 (공식 기준/근거 포함 가능)
}

/** 조항 카드 — 재사용 컴포넌트 핵심 데이터 (상세 패널 6구성 §6.5) */
export interface ClauseCard {
  id: string;
  title: string; // 조항 제목
  state: ClauseCardState;
  signal: ReviewSignalType;
  /** ① 계약서 원문 + 페이지 (사실) */
  original: SourceRef;
  /** ② 내가 이해한 조건 (사용자 기억) */
  understood: string | null;
  /** ③ 무엇이 다른지 쉬운 설명 (AI 추정) */
  aiExplanation: string;
  confidence: number; // 확신도
  /** ④ 공식 기준·내부 검토 규칙 (참고) */
  officialBasis: string | null;
  /** ⑤ 선택 가능한 문구 3종 */
  suggestions: ClauseSuggestion[];
  /** 사용자가 고른 문구 */
  userChoice: SuggestionChoice | null;
  /** 대행사 응답 (발송 후) */
  agencyResponse: AgencyResponse | null;
  /** 원문 뷰어(document.clauses)에서 대응하는 조항 id — 좌우 연동용 */
  docClauseId?: string;
}

export interface ContractSummary {
  id: string;
  title: string;
  counterpartyName: string;
  status: ContractStatus;
  totalAmount: number | null;
  /** 체결·업로드 일자 표시용 (예: 2026.07.20) */
  date?: string;
  /** 목록 중앙 단계 라벨 (예: 조정 요청 3건) */
  stage?: string;
  /** 응답 대기 등 대시보드 상태 배지 문구 */
  hint?: string;
  /** 만료 임박 등 D-day (양수면 표시) */
  dDay?: number;
}

export interface AuditEvent {
  id: string;
  label: string;
  date: string; // YYYY-MM-DD 또는 표시용
  state: "done" | "current" | "upcoming";
}

export interface Obligation {
  id: string;
  title: string; // 인스타그램 게시물 4건
  dueDate: string;
  assignee: "AGENCY" | "OWNER";
  evidenceType: "URL";
  evidenceUrl: string | null;
  status: ObligationStatus;
  submittedAt: string | null;
}

export interface AgreementClause {
  title: string;
  outcome: "AGREED" | "KEPT_ORIGINAL"; // 합의 / 원안 유지 — 거절된 것도 남긴다(§4.6)
  before: string;
  after: string; // KEPT_ORIGINAL이면 before와 사실상 동일
  reason?: string; // 원안 유지 사유
}

export interface SignatureState {
  modusign: ModusignStatus;
  ownerSigned: boolean;
  agencySigned: boolean;
  documentId: string | null;
}

/** 만료·재계약 D-day 3단계 (§6.12) */
export interface RenewalState {
  expiryDday: number; // D-30
  noticeDday: number; // D-14 해지 통보기한
  autoRenewDday: number; // D-7 자동갱신 임박
  previouslyKeptClause: string | null; // 지난번 원안 유지된 조항
}

/** 대시보드 집계 (§6.13) */
export interface DashboardStats {
  total: number;
  signing: number;
  inProgress: number;
  completed: number;
  expiringSoon: number;
  unresolvedSignals: number;
  obligationPending: number;
  obligationSubmitted: number;
  obligationApproved: number;
  totalCommitted: number; // 총 약정액
  paymentConditionMet: number; // 지급 조건 충족 금액 (실제 송금 아님)
  mostCommonSignalLabel: string;
}

/** 대행사 공개 화면용 조정 요청 (토큰 접근) */
export interface AdjustmentRequestPublic {
  token: string;
  contractTitle: string;
  /** 목업에서만 제공되는 보조 표시 정보. 공개 API에는 포함하지 않는다. */
  ownerLabel?: string;
  estimatedMinutes?: number;
  status: AdjustmentRequestStatus;
  items: {
    clauseId: string;
    requestText: string;
    officialBasis: string | null;
  }[];
}

/** 하나의 계약에 대한 전체 상세 번들 (목업 편의) */
export interface ContractDetail {
  summary: ContractSummary;
  understood: UnderstoodTerm;
  /** 원문 뷰어용 문서 (분석 결과 화면 좌측) */
  document: ContractDocument;
  extracted: ExtractedField[];
  clauses: ClauseCard[];
  signalCounts: { mismatch: number; noBasis: number; unclear: number };
  timeline: AuditEvent[];
  signature: SignatureState;
  obligation: Obligation;
  agreement: AgreementClause[];
  renewal: RenewalState;
}
