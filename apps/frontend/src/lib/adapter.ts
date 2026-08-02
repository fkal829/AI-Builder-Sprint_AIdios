/* ===========================================================================
   데이터 Adapter (기획안 §9) — 외부 API는 Adapter 뒤에 두어 Mock↔실 API 전환.
   실제 API 연동 시 RealAdapter만 구현해 교체. 화면 코드는 그대로 유지.
   엔드포인트 매핑은 §12 최소 API 명세 참고.
   =========================================================================== */
import {
  DEMO_ADJUSTMENT_REQUEST,
  DEMO_CONTRACT,
  DASHBOARD_CONTRACTS,
  DASHBOARD_STATS,
} from "./mock";
import { getOwnerAccessToken } from "./supabase/client";
import { politen } from "./tone";
import type {
  AuditEvent,
  AgencyDecision,
  AdjustmentRequestPublic,
  ContractDetail,
  ContractSummary,
  DashboardStats,
  SuggestionChoice,
} from "./types";

type PublicResponseInput = {
  itemId: string;
  decision: AgencyDecision;
  counterText?: string;
  reason?: string;
};

type ApiEnvelope<T> = {
  data: T | null;
  error: { code: string; message: string } | null;
  requestId: string;
};

type ApiPublicAdjustment = {
  contract_title: string;
  status: AdjustmentRequestPublic["status"];
  items: {
    item_id: string;
    before_text: string | null;
    source_page: number | null;
    request_text: string;
  }[];
};

type ApiOwnerAdjustmentDetail = {
  request: {
    id: string;
    status: AdjustmentRequestPublic["status"];
    expires_at: string | null;
    items: {
      review_item_id: string;
      request_text: string;
    }[];
  };
  responses: {
    review_item_id: string;
    decision: AgencyDecision;
    counter_text: string | null;
    reason: string | null;
  }[];
  comparisons: {
    review_item_id: string;
    changed_summary: string;
    remaining_checks: string[];
    final_confirmation: string;
  }[];
};

type ApiDashboard = {
  total: number;
  signing: number;
  in_progress: number;
  completed: number;
  expiring_soon: number;
  unresolved_signals: number;
  obligation_pending: number;
  obligation_submitted: number;
  obligation_approved: number;
  total_committed: number;
  payment_condition_met_amount: number;
  most_common_signal: string | null;
};

type ApiContractListItem = {
  id: string;
  title: string;
  counterparty_name: string;
  status: ContractSummary["status"];
  total_amount: number | null;
  end_date: string | null;
  expiry_d_day: number | null;
  termination_notice_d_day: number | null;
  auto_renewal_d_day: number | null;
};

type ContractCreateInput = {
  title: string;
  counterpartyName: string;
};

type UnderstoodTermInput = {
  durationText: string;
  monthlyAmount: number | null;
  totalAmount: number | null;
  refundText: string;
  terminationText: string;
};

export type SignatureSignerInput = {
  role: "OWNER" | "AGENCY";
  name: string;
  email: string;
};

type ApiContract = {
  id: string;
  title: string;
  counterparty_name: string;
  status: ContractSummary["status"];
  signed_date: string | null;
  start_date: string | null;
  end_date: string | null;
  termination_notice_date: string | null;
  renewal_type: string | null;
  total_amount: number | null;
  modusign_document_id: string | null;
  renewal_decision: {
    decision: LiveRenewalView["currentDecision"];
    revisit_review_item_ids: string[];
  } | null;
};
type ApiDocument = { id: string };
type ApiAuditEvent = {
  id: string;
  event_type: string;
  summary: string | null;
  created_at: string;
};
type ApiSignature = {
  status: LiveSignature["status"];
  modusign_status: LiveSignature["modusignStatus"];
  modusign_document_id: string | null;
};
type ApiObligation = {
  id: string;
  title: string;
  due_date: string;
  source_page: number;
  source_text: string;
  confidence: number;
  evidence_url: string | null;
  status: LiveObligation["status"];
  submitted_at: string | null;
  reviewed_at: string | null;
  payment_condition_met: boolean;
};
type ApiRevisedContractReview = {
  id: string;
  document_id: string;
  status: RevisedContractReview["status"];
  items: {
    review_item_id: string;
    expected_text: string;
    match_status: RevisedContractReview["items"][number]["matchStatus"];
    source_page: number | null;
    source_text: string | null;
    confidence: number | null;
    owner_confirmed: boolean;
  }[];
};
type ApiReviewItem = {
  id: string; type: LiveReviewItem["type"]; severity: LiveReviewItem["severity"];
  plain_explanation: string; source_page: number | null;
  source_text: string | null; source_confidence: number | null; basis_text: string;
  suggestion_accept: string; suggestion_compromise: string; suggestion_request: string;
  related_extracted_term_ids: string[];
  user_choice: SuggestionChoice | null;
};

type ApiAnalysisExtractedTerm = {
  id: string;
  field: string;
};

type ApiDocumentClause = {
  id: string;
  document_id: string;
  ordinal: number;
  heading: string;
  title: string;
  source_page: number;
  source_text: string;
  confidence: number | null;
};

type ApiAnalysisTask = {
  document_id: string;
  supporting_document_ids: string[];
  status: "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";
  error_code: string | null;
  result: {
    document_clauses?: ApiDocumentClause[];
    extracted_terms: ApiAnalysisExtractedTerm[];
    review_items: ApiReviewItem[];
  } | null;
};

type ApiPerformanceMetricCandidate = {
  value: number | null;
  source_page: number | null;
  source_text: string | null;
  confidence: number;
  verification_status: PerformanceMetricVerificationStatus;
};

type ApiPerformanceExtractedPayload = {
  ad_spend?: ApiPerformanceMetricCandidate;
  impressions: ApiPerformanceMetricCandidate;
  clicks?: ApiPerformanceMetricCandidate;
  likes: ApiPerformanceMetricCandidate;
  comments: ApiPerformanceMetricCandidate;
  reach: ApiPerformanceMetricCandidate;
  saves: ApiPerformanceMetricCandidate;
  shares: ApiPerformanceMetricCandidate;
  follower_net_change: ApiPerformanceMetricCandidate;
  published_content_count: ApiPerformanceMetricCandidate;
};

type ApiPerformanceMetricItem = {
  key: string;
  label: string;
  value: number | null;
  unit: PerformanceMetricUnit;
};

type ApiPerformanceConfirmedPayload = {
  impressions: number;
  likes: number;
  comments: number;
  reach: number | null;
  saves: number | null;
  shares: number | null;
  follower_net_change: number | null;
  published_content_count: number | null;
  inquiries: number | null;
  reservations: number | null;
  purchases: number | null;
  metric_items?: ApiPerformanceMetricItem[];
};

type ApiPerformanceFlag = {
  id: string;
  flag_type: PerformanceFlag["flagType"];
  expected_content_count: number | null;
  actual_content_count: number | null;
  previous_engagement_rate: number | null;
  current_engagement_rate: number | null;
  issue_note: string | null;
  basis_snapshots: {
    source_page: number;
    source_text: string;
    confidence: number;
  }[];
};

type ApiPerformanceInquiryDraft = {
  id: string;
  flag_id: string;
  text: string;
};

type ApiPerformanceRevision = {
  id: string;
  version: number;
  status: "CONFIRMED" | "FLAGGED";
  confirmed_payload: ApiPerformanceConfirmedPayload;
  engagement_rate: number | null;
  correction_reason: string | null;
  confirmed_at: string;
  flags: ApiPerformanceFlag[];
  inquiry_drafts: ApiPerformanceInquiryDraft[];
};

type ApiPerformanceReport = {
  id: string;
  period: string;
  status: PerformanceReportStatus;
  extracted_payload: ApiPerformanceExtractedPayload | null;
  current_revision: ApiPerformanceRevision | null;
  revision_count: number;
  revisions: ApiPerformanceRevision[];
  created_at: string;
};

type ApiContractPerformance = {
  contract_id: string;
  reports: ApiPerformanceReport[];
  confirmed_series: {
    report_id: string;
    period: string;
    version: number;
    status: "CONFIRMED" | "FLAGGED";
    confirmed_payload: ApiPerformanceConfirmedPayload;
    engagement_rate: number | null;
    confirmed_at: string;
  }[];
  flags: ApiPerformanceFlag[];
  inquiry_drafts: ApiPerformanceInquiryDraft[];
};

export type LiveReviewItem = {
  id: string;
  type: "MISMATCH" | "NO_BASIS" | "UNCLEAR" | "MISSING" | "NEEDS_CHECK";
  severity: "INFO" | "CHECK" | "IMPORTANT";
  plainExplanation: string;
  sourcePage: number | null;
  sourceText: string | null;
  sourceConfidence: number | null;
  basisText: string;
  suggestionAccept: string;
  suggestionCompromise: string;
  suggestionRequest: string;
  relatedExtractedFields: string[];
  userChoice: SuggestionChoice | null;
};

export type LiveDocumentClause = {
  id: string;
  documentId: string;
  ordinal: number;
  heading: string;
  title: string;
  sourcePage: number;
  sourceText: string;
  confidence: number | null;
};

export type LiveContractReview = {
  title: string;
  counterpartyName: string;
  status: ContractSummary["status"];
  documentAccessUrl: string | null;
  documentClauses: LiveDocumentClause[];
  understood: UnderstoodTermInput | null;
  items: LiveReviewItem[];
};

export type LiveAdjustmentDraft = {
  id: string;
  items: { reviewItemId: string; requestText: string }[];
};

export type ManualAdjustmentDraftInput = {
  documentClauseId: string;
  requestText: string;
};

export type RevisedContractReview = {
  id: string;
  documentId: string;
  status: "REVIEW_REQUIRED" | "CONFIRMED";
  items: {
    reviewItemId: string;
    expectedText: string;
    matchStatus: "MATCHED" | "NEEDS_CONFIRMATION";
    sourcePage: number | null;
    sourceText: string | null;
    confidence: number | null;
    ownerConfirmed: boolean;
  }[];
};

export type LiveAdjustmentDetail = {
  id: string;
  status: AdjustmentRequestPublic["status"];
  expiresAt: string | null;
  items: {
    reviewItemId: string;
    requestText: string;
    decision: AgencyDecision | null;
    counterText: string | null;
    reason: string | null;
    comparison: {
      changedSummary: string;
      remainingChecks: string[];
      finalConfirmation: string;
    } | null;
  }[];
};

export type AdjustmentPreview = {
  items: {
    id: string;
    title: string;
    text: string;
  }[];
};

export type AdjustmentResolutionInput = {
  reviewItemId: string;
  resolution: "ACCEPT_REQUEST" | "ACCEPT_COUNTERPROPOSAL" | "KEEP_ORIGINAL";
};

export type LiveSignature = {
  status:
    | "REQUEST_READY"
    | "REQUESTING"
    | "EDITING"
    | "SIGNING"
    | "COMPLETED"
    | "ABORTED"
    | "FAILED";
  modusignStatus:
    | "DRAFT"
    | "SCHEDULED"
    | "ON_PROCESSING"
    | "ON_GOING"
    | "COMPLETED"
    | "ABORTED"
    | "PROCESSING_FAILED"
    | null;
  documentId: string | null;
};

export type LiveSignatureView = {
  signature: LiveSignature | null;
  timeline: AuditEvent[];
};

export type LiveObligation = {
  id: string;
  title: string;
  dueDate: string;
  sourcePage: number;
  sourceText: string;
  confidence: number;
  evidenceUrl: string | null;
  status: "PENDING" | "SUBMITTED" | "APPROVED" | "DISPUTED";
  submittedAt: string | null;
  reviewedAt: string | null;
  paymentConditionMet: boolean;
};

export type LiveRenewalView = {
  title: string;
  expiryDday: number | null;
  noticeDday: number | null;
  autoRenewalDday: number | null;
  currentDecision: "RENEW_SAME_TERMS" | "RENEW_WITH_CHANGES" | "TERMINATE" | null;
  revisitReviewItemIds: string[];
};

export type PerformanceReportStatus = "UPLOADED" | "EXTRACTED" | "CONFIRMED" | "FLAGGED";
export type PerformanceMetricVerificationStatus = "VERIFIED" | "NOT_FOUND" | "NEEDS_CHECK";
export type PerformanceMetricKey =
  | "adSpend"
  | "impressions"
  | "clicks"
  | "likes"
  | "comments"
  | "reach"
  | "saves"
  | "shares"
  | "followerNetChange"
  | "publishedContentCount";

export type PerformanceMetricCandidate = {
  value: number | null;
  sourcePage: number | null;
  sourceText: string | null;
  confidence: number;
  verificationStatus: PerformanceMetricVerificationStatus;
};

export type PerformanceExtractedPayload = Record<PerformanceMetricKey, PerformanceMetricCandidate>;

export type PerformanceMetricUnit = "KRW" | "COUNT" | "PERCENT" | "NUMBER";
export type PerformanceCanonicalMetricKey =
  | "ad_spend"
  | "impressions"
  | "clicks"
  | "ctr"
  | "cpc"
  | "published_content_count";

export type PerformanceMetricItem = {
  key: string;
  label: string;
  value: number | null;
  unit: PerformanceMetricUnit;
};

export const PERFORMANCE_BASE_METRICS = [
  { key: "ad_spend", label: "집행 광고비", unit: "KRW" },
  { key: "impressions", label: "노출 수", unit: "COUNT" },
  { key: "clicks", label: "클릭 수", unit: "COUNT" },
  { key: "ctr", label: "CTR", unit: "PERCENT" },
  { key: "cpc", label: "CPC", unit: "KRW" },
  { key: "published_content_count", label: "게시물 수", unit: "COUNT" },
] as const satisfies readonly {
  key: PerformanceCanonicalMetricKey;
  label: string;
  unit: PerformanceMetricUnit;
}[];

export function calculatePerformanceCtr(
  clicks: number | null,
  impressions: number | null,
): number | null {
  if (clicks === null || impressions === null || impressions <= 0) return null;
  return Math.round((clicks / impressions) * 10_000) / 100;
}

export function calculatePerformanceCpc(
  adSpend: number | null,
  clicks: number | null,
): number | null {
  if (adSpend === null || clicks === null || clicks <= 0) return null;
  return Math.round(adSpend / clicks);
}

export function createPerformanceBaseMetricItems(
  values: Partial<Record<PerformanceCanonicalMetricKey, number | null>> = {},
): PerformanceMetricItem[] {
  const ctr = calculatePerformanceCtr(values.clicks ?? null, values.impressions ?? null);
  const cpc = calculatePerformanceCpc(values.ad_spend ?? null, values.clicks ?? null);
  return PERFORMANCE_BASE_METRICS.map((definition): PerformanceMetricItem => ({
    ...definition,
    value: definition.key === "ctr"
      ? ctr
      : definition.key === "cpc"
        ? cpc
        : values[definition.key] ?? null,
  }));
}

export function performanceMetricValue(
  items: readonly PerformanceMetricItem[],
  key: PerformanceCanonicalMetricKey,
): number | null {
  return items.find((item) => item.key === key)?.value ?? null;
}

export type PerformanceConfirmedPayload = {
  impressions: number;
  likes: number;
  comments: number;
  reach: number | null;
  saves: number | null;
  shares: number | null;
  followerNetChange: number | null;
  publishedContentCount: number | null;
  inquiries: number | null;
  reservations: number | null;
  purchases: number | null;
  metricItems: PerformanceMetricItem[];
};

export type PerformanceFlag = {
  id: string;
  flagType: "DELIVERABLE_COUNT_SHORTFALL" | "ENGAGEMENT_RATE_DROP" | "OWNER_REPORTED_ISSUE";
  expectedContentCount: number | null;
  actualContentCount: number | null;
  previousEngagementRate: number | null;
  currentEngagementRate: number | null;
  issueNote: string | null;
  basisSnapshots: {
    sourcePage: number;
    sourceText: string;
    confidence: number;
  }[];
};

export type PerformanceInquiryDraft = {
  id: string;
  flagId: string;
  text: string;
};

export type PerformanceReportRevision = {
  id: string;
  version: number;
  status: "CONFIRMED" | "FLAGGED";
  confirmedPayload: PerformanceConfirmedPayload;
  engagementRate: number | null;
  correctionReason: string | null;
  confirmedAt: string;
  flags: PerformanceFlag[];
  inquiryDrafts: PerformanceInquiryDraft[];
};

export type PerformanceReport = {
  id: string;
  period: string;
  status: PerformanceReportStatus;
  extractedPayload: PerformanceExtractedPayload | null;
  currentRevision: PerformanceReportRevision | null;
  revisionCount: number;
  revisions: PerformanceReportRevision[];
  createdAt: string;
};

export type ContractPerformance = {
  contractId: string;
  reports: PerformanceReport[];
  confirmedSeries: {
    reportId: string;
    period: string;
    version: number;
    status: "CONFIRMED" | "FLAGGED";
    confirmedPayload: PerformanceConfirmedPayload;
    engagementRate: number | null;
    confirmedAt: string;
  }[];
  flags: PerformanceFlag[];
  inquiryDrafts: PerformanceInquiryDraft[];
};

export type PerformanceConfirmationInput = {
  expectedRevision: number;
  confirmedPayload: PerformanceConfirmedPayload;
  hasIssue: boolean;
  issueNote: string | null;
  correctionReason: string | null;
};

export class PublicApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** 조항 하나에 대한 AI 설명 — 원문 뷰어의 "AI 설명 더 보기" 버튼 응답 형태 */
export interface ClauseExplanation {
  summary: string;
  officialBasis: string | null;
  confidence: number | null;
}

export interface DataAdapter {
  /** GET /api/v1/dashboard */
  getDashboard(): Promise<{ stats: DashboardStats; contracts: ContractSummary[] }>;
  /** GET /api/v1/contracts/{contractId} (+ analysis). 미존재 시 reject(404). */
  getContract(contractId: string): Promise<ContractDetail>;
  createContract(input: ContractCreateInput): Promise<{ id: string }>;
  uploadContractDocument(contractId: string, file: File): Promise<{ id: string }>;
  uploadRevisedContract(contractId: string, file: File): Promise<{ id: string }>;
  saveUnderstoodTerms(contractId: string, input: UnderstoodTermInput): Promise<void>;
  startContractAnalysis(
    contractId: string,
    documentId: string,
    supportingDocumentIds?: string[],
  ): Promise<void>;
  getContractAnalysis(contractId: string): Promise<ApiAnalysisTask>;
  getLiveContractReview(contractId: string): Promise<LiveContractReview>;
  selectReviewItem(contractId: string, itemId: string, choice: SuggestionChoice): Promise<void>;
  /** POST /api/v1/contracts/{contractId}/adjustment-copy/polish */
  polishAdjustmentCopy(contractId: string, text: string): Promise<string>;
  createAdjustmentDraft(
    contractId: string,
    reviewItemIds: string[],
    requestTextOverrides?: Record<string, string>,
    manualItems?: ManualAdjustmentDraftInput[],
  ): Promise<LiveAdjustmentDraft>;
  getAdjustmentPreview(contractId: string): Promise<AdjustmentPreview>;
  sendAdjustmentDraft(
    contractId: string,
    adjustmentId: string,
  ): Promise<{ publicUrl: string; expiresAt: string }>;
  getAdjustmentDetail(
    contractId: string,
    adjustmentId: string,
  ): Promise<LiveAdjustmentDetail>;
  confirmAdjustmentResult(
    contractId: string,
    adjustmentId: string,
    resolutions: AdjustmentResolutionInput[],
  ): Promise<void>;
  createRevisedContractReview(
    contractId: string,
    adjustmentId: string,
    documentId: string,
  ): Promise<RevisedContractReview>;
  getLatestRevisedContractReview(contractId: string): Promise<RevisedContractReview>;
  confirmRevisedContractReview(
    contractId: string,
    reviewId: string,
    reviewItemIds: string[],
  ): Promise<RevisedContractReview>;
  createSignatureDraft(
    contractId: string,
    reviewId: string,
    signers: SignatureSignerInput[],
  ): Promise<{ editorUrl: string; expiresAt: string }>;
  getSignatureView(contractId: string): Promise<LiveSignatureView>;
  getObligation(contractId: string): Promise<LiveObligation | null>;
  createObligationEvidenceLink(
    contractId: string,
    obligationId: string,
  ): Promise<{ publicUrl: string; expiresAt: string }>;
  reviewObligation(
    contractId: string,
    obligationId: string,
    decision: "APPROVED" | "DISPUTED",
    evidenceUrl?: string | null,
  ): Promise<LiveObligation>;
  getRenewalView(contractId: string): Promise<LiveRenewalView>;
  saveRenewalDecision(
    contractId: string,
    decision: "RENEW_SAME_TERMS" | "RENEW_WITH_CHANGES" | "TERMINATE",
  ): Promise<LiveRenewalView>;
  getContractPerformance(contractId: string): Promise<ContractPerformance>;
  uploadPerformanceReport(
    contractId: string,
    period: string,
    file: File,
  ): Promise<PerformanceReport>;
  extractPerformanceReport(contractId: string, reportId: string): Promise<PerformanceReport>;
  confirmPerformanceReport(
    contractId: string,
    reportId: string,
    input: PerformanceConfirmationInput,
  ): Promise<PerformanceReport>;
  /** GET /api/v1/public/adjustment-requests/{token} */
  getAdjustmentRequest(token: string): Promise<AdjustmentRequestPublic | null>;
  /** POST /api/v1/public/adjustment-requests/{token}/open */
  openAdjustmentRequest(token: string): Promise<void>;
  /** POST /api/v1/public/adjustment-requests/{token}/responses */
  submitAdjustmentResponses(token: string, responses: PublicResponseInput[]): Promise<void>;
  /** POST /api/v1/public/obligations/{token}/evidence */
  submitObligationEvidence(token: string, evidenceUrl: string): Promise<void>;
  /** GET /api/v1/contracts/{contractId}/clauses/{clauseId}/explain — 조항 AI 설명(온디맨드) */
  explainClause(contractId: string, clauseId: string): Promise<ClauseExplanation>;
}

/** 네트워크 지연 흉내 (분석 진행 화면 등에서 사용) */
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

function mockRevisedContractReview(documentId: string): RevisedContractReview {
  const requested = DEMO_CONTRACT.clauses
    .filter((clause) => clause.userChoice === "REQUEST" || clause.userChoice === "COMPROMISE");
  return {
    id: "mock-revised-contract-review",
    documentId,
    status: "REVIEW_REQUIRED",
    items: requested.map((clause, index) => ({
      reviewItemId: clause.id,
      expectedText: clause.agencyResponse?.counterText ?? clause.understood ?? clause.title,
      matchStatus: index === requested.length - 1 ? "NEEDS_CONFIRMATION" : "MATCHED",
      sourcePage: index === requested.length - 1 ? null : 1,
      sourceText: index === requested.length - 1 ? null : clause.understood,
      confidence: index === requested.length - 1 ? null : 1,
      ownerConfirmed: false,
    })),
  };
}

function mapRevisedContractReview(data: ApiRevisedContractReview): RevisedContractReview {
  return {
    id: data.id,
    documentId: data.document_id,
    status: data.status,
    items: data.items.map((item) => ({
      reviewItemId: item.review_item_id,
      expectedText: item.expected_text,
      matchStatus: item.match_status,
      sourcePage: item.source_page,
      sourceText: item.source_text,
      confidence: item.confidence,
      ownerConfirmed: item.owner_confirmed,
    })),
  };
}

function mapObligation(data: ApiObligation): LiveObligation {
  return {
    id: data.id,
    title: data.title,
    dueDate: data.due_date,
    sourcePage: data.source_page,
    sourceText: data.source_text,
    confidence: data.confidence,
    evidenceUrl: data.evidence_url,
    status: data.status,
    submittedAt: data.submitted_at,
    reviewedAt: data.reviewed_at,
    paymentConditionMet: data.payment_condition_met,
  };
}

function mapTimeline(events: ApiAuditEvent[]): AuditEvent[] {
  return events.map((event, index) => ({
    id: event.id,
    // 화면 문구는 event_type에서 만든다. 저장된 summary는 이벤트를 기록한 계층마다
    // 문체와 언어가 달라서(일부는 영어) 그대로 쓰면 사용자에게 섞여 보이고, 특히
    // 서명 동기화는 진행/완료/중단을 한 문장으로 기록해 상태 구분이 사라진다.
    // event_type은 상태마다 값이 다르므로 구분이 항상 보장된다.
    label: auditEventLabel(event.event_type) ?? event.summary?.trim() ?? event.event_type,
    date: event.created_at.slice(5, 10).replace("-", "/"),
    state: index === events.length - 1 ? "current" : "done",
  }));
}

/* 계약 생애 전체의 감사 이벤트 문구(기획안 §6.10).
   원칙 #1에 따라 판정하지 않고 일어난 사실만 서술한다. */
const AUDIT_EVENT_LABELS: Record<string, string> = {
  CONTRACT_CREATED: "계약을 생성했습니다.",
  CONTRACT_STARTED: "계약이 시작되었습니다.",
  CONTRACT_COMPLETED: "계약이 완료되었습니다.",
  CONTRACT_RENEWAL_DUE: "재계약 검토 시점이 되었습니다.",
  DOCUMENT_UPLOADED: "계약 문서가 업로드되었습니다.",
  UNDERSTOOD_TERMS_SAVED: "사용자가 이해한 계약 조건이 저장되었습니다.",
  ANALYSIS_STARTED: "계약 분석을 시작했습니다.",
  ANALYSIS_RESTARTED: "계약 분석을 다시 시작했습니다.",
  ANALYSIS_COMPLETED: "계약 분석을 완료했습니다.",
  ANALYSIS_FAILED: "계약 분석을 완료하지 못했습니다.",
  REVIEW_ITEM_SELECTION_UPDATED: "검토 항목 선택을 변경했습니다.",
  ADJUSTMENT_DRAFT_CREATED: "조정 요청 초안을 생성했습니다.",
  ADJUSTMENT_SENT: "조정 요청을 발송했습니다.",
  ADJUSTMENT_OPENED: "대행사가 조정 요청을 열람했습니다.",
  ADJUSTMENT_RESPONDED: "대행사가 조정 요청에 응답했습니다.",
  ADJUSTMENT_CONFIRMED: "조정 결과를 확정했습니다.",
  ADJUSTMENT_EXPIRED: "조정 요청 링크가 만료되었습니다.",
  AGREEMENT_CREATED: "합의서를 생성했습니다.",
  REVISED_CONTRACT_REVIEW_CREATED: "수정 계약서 대조를 생성했습니다.",
  REVISED_CONTRACT_CONFIRMED: "수정 계약서 대조 결과를 확인했습니다.",
  SIGNATURE_DRAFT_CREATED: "모두싸인 서명 초안을 만들었습니다.",
  SIGNATURE_REQUESTED: "서명을 요청했습니다.",
  SIGNATURE_STARTED: "양측 서명이 진행 중입니다.",
  SIGNATURE_COMPLETED: "양측 서명이 완료되었습니다.",
  SIGNATURE_ABORTED: "서명이 중단되었습니다.",
  SIGNATURE_FAILED: "서명을 완료하지 못했습니다.",
  OBLIGATION_CREATED: "산출물 확인 항목을 만들었습니다.",
  EVIDENCE_LINK_CREATED: "산출물 증빙 제출 링크를 만들었습니다.",
  EVIDENCE_SUBMITTED: "산출물 증빙이 제출되었습니다.",
  EVIDENCE_APPROVED: "산출물 증빙을 승인했습니다.",
  EVIDENCE_DISPUTED: "산출물 증빙에 이의를 남겼습니다.",
  RENEWAL_DECISION_SAVED: "재계약 의사를 저장했습니다.",
  PERFORMANCE_REPORT_UPLOADED: "광고효과 리포트를 업로드했습니다.",
  PERFORMANCE_REPORT_EXTRACTED: "광고효과 리포트에서 지표를 추출했습니다.",
  PERFORMANCE_REPORT_CONFIRMED: "광고효과 리포트를 확정했습니다.",
  PERFORMANCE_REPORT_FLAGGED: "광고효과 리포트에 확인이 필요한 항목이 있습니다.",
  PERFORMANCE_REPORT_CORRECTED: "광고효과 리포트를 정정했습니다.",
  PERFORMANCE_REPORT_EXTRACTION_RECOVERED: "광고효과 리포트 추출을 다시 시도했습니다.",
};

function auditEventLabel(eventType: string): string | undefined {
  return AUDIT_EVENT_LABELS[eventType];
}

function mapPerformanceCandidate(data: ApiPerformanceMetricCandidate): PerformanceMetricCandidate {
  return {
    value: data.value,
    sourcePage: data.source_page,
    sourceText: data.source_text,
    confidence: data.confidence,
    verificationStatus: data.verification_status,
  };
}

function mapPerformanceExtractedPayload(
  data: ApiPerformanceExtractedPayload,
): PerformanceExtractedPayload {
  return {
    adSpend: data.ad_spend
      ? mapPerformanceCandidate(data.ad_spend)
      : missingPerformanceCandidate(),
    impressions: mapPerformanceCandidate(data.impressions),
    clicks: data.clicks
      ? mapPerformanceCandidate(data.clicks)
      : missingPerformanceCandidate(),
    likes: mapPerformanceCandidate(data.likes),
    comments: mapPerformanceCandidate(data.comments),
    reach: mapPerformanceCandidate(data.reach),
    saves: mapPerformanceCandidate(data.saves),
    shares: mapPerformanceCandidate(data.shares),
    followerNetChange: mapPerformanceCandidate(data.follower_net_change),
    publishedContentCount: mapPerformanceCandidate(data.published_content_count),
  };
}

function mapPerformanceConfirmedPayload(
  data: ApiPerformanceConfirmedPayload,
): PerformanceConfirmedPayload {
  const metricItems = Array.isArray(data.metric_items) && data.metric_items.length > 0
    ? data.metric_items.map((item) => ({ ...item }))
    : createPerformanceBaseMetricItems({
        impressions: data.impressions,
        published_content_count: data.published_content_count,
      });
  return {
    impressions: data.impressions,
    likes: data.likes,
    comments: data.comments,
    reach: data.reach,
    saves: data.saves,
    shares: data.shares,
    followerNetChange: data.follower_net_change,
    publishedContentCount: data.published_content_count,
    inquiries: data.inquiries,
    reservations: data.reservations,
    purchases: data.purchases,
    metricItems,
  };
}

function missingPerformanceCandidate(): PerformanceMetricCandidate {
  return {
    value: null,
    sourcePage: null,
    sourceText: null,
    confidence: 0,
    verificationStatus: "NOT_FOUND",
  };
}

function performanceConfirmedPayloadToApi(
  data: PerformanceConfirmedPayload,
): ApiPerformanceConfirmedPayload {
  return {
    impressions: data.impressions,
    likes: data.likes,
    comments: data.comments,
    reach: data.reach,
    saves: data.saves,
    shares: data.shares,
    follower_net_change: data.followerNetChange,
    published_content_count: data.publishedContentCount,
    inquiries: data.inquiries,
    reservations: data.reservations,
    purchases: data.purchases,
    metric_items: data.metricItems.map((item) => ({ ...item })),
  };
}

function mapPerformanceFlag(data: ApiPerformanceFlag): PerformanceFlag {
  return {
    id: data.id,
    flagType: data.flag_type,
    expectedContentCount: data.expected_content_count,
    actualContentCount: data.actual_content_count,
    previousEngagementRate: data.previous_engagement_rate,
    currentEngagementRate: data.current_engagement_rate,
    issueNote: data.issue_note,
    basisSnapshots: data.basis_snapshots.map((basis) => ({
      sourcePage: basis.source_page,
      sourceText: basis.source_text,
      confidence: basis.confidence,
    })),
  };
}

function mapPerformanceInquiryDraft(
  data: ApiPerformanceInquiryDraft,
): PerformanceInquiryDraft {
  return { id: data.id, flagId: data.flag_id, text: data.text };
}

function mapPerformanceRevision(data: ApiPerformanceRevision): PerformanceReportRevision {
  return {
    id: data.id,
    version: data.version,
    status: data.status,
    confirmedPayload: mapPerformanceConfirmedPayload(data.confirmed_payload),
    engagementRate: data.engagement_rate,
    correctionReason: data.correction_reason,
    confirmedAt: data.confirmed_at,
    flags: data.flags.map(mapPerformanceFlag),
    inquiryDrafts: data.inquiry_drafts.map(mapPerformanceInquiryDraft),
  };
}

function mapPerformanceReport(data: ApiPerformanceReport): PerformanceReport {
  return {
    id: data.id,
    period: data.period,
    status: data.status,
    extractedPayload: data.extracted_payload
      ? mapPerformanceExtractedPayload(data.extracted_payload)
      : null,
    currentRevision: data.current_revision
      ? mapPerformanceRevision(data.current_revision)
      : null,
    revisionCount: data.revision_count,
    revisions: data.revisions.map(mapPerformanceRevision),
    createdAt: data.created_at,
  };
}

function mapContractPerformance(data: ApiContractPerformance): ContractPerformance {
  return {
    contractId: data.contract_id,
    reports: data.reports.map(mapPerformanceReport),
    confirmedSeries: data.confirmed_series.map((point) => ({
      reportId: point.report_id,
      period: point.period,
      version: point.version,
      status: point.status,
      confirmedPayload: mapPerformanceConfirmedPayload(point.confirmed_payload),
      engagementRate: point.engagement_rate,
      confirmedAt: point.confirmed_at,
    })),
    flags: data.flags.map(mapPerformanceFlag),
    inquiryDrafts: data.inquiry_drafts.map(mapPerformanceInquiryDraft),
  };
}

function mockConfirmedPayload(
  adSpend: number,
  impressions: number,
  clicks: number,
  publishedContentCount: number,
): PerformanceConfirmedPayload {
  return {
    impressions,
    likes: 0,
    comments: 0,
    reach: null,
    saves: null,
    shares: null,
    followerNetChange: null,
    publishedContentCount,
    inquiries: null,
    reservations: null,
    purchases: null,
    metricItems: createPerformanceBaseMetricItems({
      ad_spend: adSpend,
      impressions,
      clicks,
      published_content_count: publishedContentCount,
    }),
  };
}

function calculatePerformanceEngagementRate(payload: PerformanceConfirmedPayload): number | null {
  const impressions = performanceMetricValue(payload.metricItems, "impressions");
  const clicks = performanceMetricValue(payload.metricItems, "clicks");
  if (impressions === null || clicks === null || impressions <= 0) return null;
  return clicks / impressions;
}

function createMockContractPerformance(contractId: string): ContractPerformance {
  const points = [
    { period: "2026-05", payload: mockConfirmedPayload(800_000, 12_400, 620, 4) },
    { period: "2026-06", payload: mockConfirmedPayload(900_000, 15_200, 760, 4) },
    { period: "2026-07", payload: mockConfirmedPayload(650_000, 8_300, 249, 2) },
  ];
  const reports = points.map(({ period, payload }, index): PerformanceReport => {
    const reportId = `mock-performance-${period}`;
    const flags: PerformanceFlag[] = index === 2
      ? [
          {
            id: "mock-shortfall-flag",
            flagType: "DELIVERABLE_COUNT_SHORTFALL",
            expectedContentCount: 4,
            actualContentCount: 2,
            previousEngagementRate: null,
            currentEngagementRate: null,
            issueNote: null,
            basisSnapshots: [
              { sourcePage: 3, sourceText: "월 게시물 4건", confidence: 0.96 },
              { sourcePage: 3, sourceText: "매월 콘텐츠를 게시한다.", confidence: 0.92 },
            ],
          },
          {
            id: "mock-engagement-flag",
            flagType: "ENGAGEMENT_RATE_DROP",
            expectedContentCount: null,
            actualContentCount: null,
            previousEngagementRate: calculatePerformanceEngagementRate(points[1].payload),
            currentEngagementRate: calculatePerformanceEngagementRate(payload),
            issueNote: null,
            basisSnapshots: [],
          },
        ]
      : [];
    const inquiryDrafts: PerformanceInquiryDraft[] = index === 2
      ? [
          {
            id: "mock-shortfall-inquiry",
            flagId: "mock-shortfall-flag",
            text: "2026-07 리포트의 게시물 수는 2건으로 기록되어 있습니다. 계약 원문에서 확인한 월 4건과 차이가 있어 해당 월 게시 수와 집계 기준을 확인 부탁드립니다.",
          },
          {
            id: "mock-engagement-inquiry",
            flagId: "mock-engagement-flag",
            text: "2026-06 반응률 4.03%에서 2026-07 2.89%로 낮아진 것으로 계산됩니다. 두 달 리포트의 집계 기준과 변동 사유를 확인 부탁드립니다.",
          },
        ]
      : [];
    const revision: PerformanceReportRevision = {
      id: `${reportId}-revision-1`,
      version: 1,
      status: flags.length ? "FLAGGED" : "CONFIRMED",
      confirmedPayload: payload,
      engagementRate: calculatePerformanceEngagementRate(payload),
      correctionReason: null,
      confirmedAt: `${period}-28T09:00:00+09:00`,
      flags,
      inquiryDrafts,
    };
    return {
      id: reportId,
      period,
      status: revision.status,
      extractedPayload: null,
      currentRevision: revision,
      revisionCount: 1,
      revisions: [revision],
      createdAt: `${period}-28T08:00:00+09:00`,
    };
  });
  return buildMockContractPerformance(contractId, reports);
}

function buildMockContractPerformance(
  contractId: string,
  reports: PerformanceReport[],
): ContractPerformance {
  const confirmed = reports.filter(
    (report) => report.currentRevision && ["CONFIRMED", "FLAGGED"].includes(report.status),
  );
  return {
    contractId,
    reports: [...reports].sort((left, right) => left.period.localeCompare(right.period)),
    confirmedSeries: confirmed.map((report) => ({
      reportId: report.id,
      period: report.period,
      version: report.currentRevision!.version,
      status: report.currentRevision!.status,
      confirmedPayload: report.currentRevision!.confirmedPayload,
      engagementRate: report.currentRevision!.engagementRate,
      confirmedAt: report.currentRevision!.confirmedAt,
    })),
    flags: confirmed.flatMap((report) => report.currentRevision!.flags),
    inquiryDrafts: confirmed.flatMap((report) => report.currentRevision!.inquiryDrafts),
  };
}

function mockExtractedPayload(): PerformanceExtractedPayload {
  const candidate = (
    value: number | null,
    label: string,
  ): PerformanceMetricCandidate => value === null
    ? {
        value: null,
        sourcePage: null,
        sourceText: null,
        confidence: 0,
        verificationStatus: "NOT_FOUND",
      }
    : {
        value,
        sourcePage: 1,
        sourceText: `${label}: ${value.toLocaleString()}`,
        confidence: 0.94,
        verificationStatus: "VERIFIED",
      };
  return {
    adSpend: candidate(720000, "집행 광고비"),
    impressions: candidate(9100, "노출"),
    clicks: candidate(310, "클릭 수"),
    likes: candidate(230, "좋아요"),
    comments: candidate(32, "댓글"),
    reach: candidate(7400, "도달"),
    saves: candidate(48, "저장"),
    shares: candidate(12, "공유"),
    followerNetChange: candidate(35, "팔로워 순증"),
    publishedContentCount: candidate(4, "게시물 수"),
  };
}

function previousPerformancePeriod(period: string): string {
  const [year, month] = period.split("-").map(Number);
  return month === 1
    ? `${String(year - 1).padStart(4, "0")}-12`
    : `${String(year).padStart(4, "0")}-${String(month - 1).padStart(2, "0")}`;
}

class MockAdapter implements DataAdapter {
  private readonly performanceByContract = new Map<string, ContractPerformance>();

  async getDashboard() {
    await delay(120);
    return { stats: DASHBOARD_STATS, contracts: DASHBOARD_CONTRACTS };
  }

  async getContract() {
    await delay(120);
    // 데모: 어떤 id로 진입해도 대표 계약(광안리 카페)을 보여줌.
    // 실 API에서는 미존재 시 reject 해 error 상태로 처리.
    return DEMO_CONTRACT;
  }

  async createContract(input: ContractCreateInput) {
    void input;
    await delay(120);
    return { id: DEMO_CONTRACT.summary.id };
  }

  async uploadContractDocument(contractId: string, file: File) {
    void contractId;
    void file;
    await delay(240);
    return { id: "mock-contract-document" };
  }

  async uploadRevisedContract(contractId: string, file: File) {
    void contractId;
    void file;
    await delay(240);
    return { id: "mock-revised-contract-document" };
  }

  async saveUnderstoodTerms(contractId: string, input: UnderstoodTermInput) {
    void contractId;
    void input;
    await delay(120);
  }

  async startContractAnalysis(
    contractId: string,
    documentId: string,
    supportingDocumentIds: string[] = [],
  ) {
    void contractId;
    void documentId;
    void supportingDocumentIds;
    await delay(240);
  }

  async getContractAnalysis(_contractId: string): Promise<ApiAnalysisTask> {
    void _contractId;
    await delay(120);
    return {
      document_id: "mock-contract-document",
      supporting_document_ids: [],
      status: "COMPLETED",
      error_code: null,
      result: { document_clauses: [], extracted_terms: [], review_items: [] },
    };
  }

  async getLiveContractReview(_contractId: string): Promise<LiveContractReview> {
    void _contractId;
    return {
      title: DEMO_CONTRACT.summary.title,
      counterpartyName: DEMO_CONTRACT.summary.counterpartyName,
      status: DEMO_CONTRACT.summary.status,
      documentAccessUrl: DEMO_CONTRACT.document.pdfUrl,
      documentClauses: [],
      understood: null,
      items: [],
    };
  }

  async selectReviewItem(_contractId: string, _itemId: string, _choice: SuggestionChoice) {
    void _contractId;
    void _itemId;
    void _choice;
    await delay(120);
  }
  async createAdjustmentDraft(
    _contractId: string,
    _reviewItemIds: string[],
    requestTextOverrides: Record<string, string> = {},
    manualItems: ManualAdjustmentDraftInput[] = [],
  ): Promise<LiveAdjustmentDraft> {
    void _contractId;
    await delay(120);
    return {
      id: "mock-adjustment",
      items: [
        ..._reviewItemIds.map((reviewItemId) => ({
          reviewItemId,
          requestText: requestTextOverrides[reviewItemId] ?? "조정 요청",
        })),
        ...manualItems.map((item) => ({
          reviewItemId: item.documentClauseId,
          requestText: item.requestText,
        })),
      ],
    };
  }

  async getAdjustmentPreview(_contractId: string): Promise<AdjustmentPreview> {
    void _contractId;
    await delay(120);
    return {
      items: DEMO_CONTRACT.clauses
        .filter((clause) => clause.userChoice === "REQUEST" || clause.userChoice === "COMPROMISE")
        .map((clause) => ({
          id: clause.id,
          title: clause.title,
          text: clause.suggestions.find((item) => item.choice === clause.userChoice)?.text
            ?? clause.understood
            ?? clause.title,
        })),
    };
  }

  async sendAdjustmentDraft(
    _contractId: string,
    _adjustmentId: string,
  ): Promise<{ publicUrl: string; expiresAt: string }> {
    void _contractId;
    void _adjustmentId;
    await delay(120);
    return {
      publicUrl: "/r/demo-adjustment-token",
      expiresAt: new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString(),
    };
  }

  async getAdjustmentDetail(
    _contractId: string,
    adjustmentId: string,
  ): Promise<LiveAdjustmentDetail> {
    void _contractId;
    await delay(120);
    return {
      id: adjustmentId,
      status: "RESPONDED",
      expiresAt: new Date(Date.now() + 4 * 24 * 60 * 60 * 1000).toISOString(),
      items: DEMO_CONTRACT.clauses
        .filter((clause) => clause.userChoice === "REQUEST" || clause.userChoice === "COMPROMISE")
        .map((clause) => ({
          reviewItemId: clause.id,
          requestText: clause.suggestions.find((item) => item.choice === clause.userChoice)?.text
            ?? clause.understood
            ?? clause.title,
          decision: clause.agencyResponse?.decision ?? null,
          counterText: clause.agencyResponse?.counterText ?? null,
          reason: clause.agencyResponse?.reason ?? null,
          comparison:
            clause.agencyResponse?.decision === "COUNTER"
              ? {
                  changedSummary: "요청안과 대행사 역제안의 조건이 달라졌습니다.",
                  remainingChecks: ["수정 계약서에 역제안 문구가 그대로 반영됐는지 확인하세요."],
                  finalConfirmation: "역제안을 수락할지 직접 확인해주세요.",
                }
              : null,
        })),
    };
  }

  async confirmAdjustmentResult(
    _contractId: string,
    _adjustmentId: string,
    _resolutions: AdjustmentResolutionInput[],
  ): Promise<void> {
    void _contractId;
    void _adjustmentId;
    void _resolutions;
    await delay(120);
  }

  async createRevisedContractReview(
    _contractId: string,
    _adjustmentId: string,
    documentId: string,
  ): Promise<RevisedContractReview> {
    void _contractId;
    void _adjustmentId;
    await delay(240);
    return mockRevisedContractReview(documentId);
  }

  async getLatestRevisedContractReview(_contractId: string): Promise<RevisedContractReview> {
    void _contractId;
    await delay(120);
    return mockRevisedContractReview("mock-revised-contract-document");
  }

  async confirmRevisedContractReview(
    _contractId: string,
    _reviewId: string,
    _reviewItemIds: string[],
  ): Promise<RevisedContractReview> {
    void _contractId;
    void _reviewId;
    void _reviewItemIds;
    await delay(120);
    const review = mockRevisedContractReview("mock-revised-contract-document");
    return {
      ...review,
      status: "CONFIRMED",
      items: review.items.map((item) => ({ ...item, ownerConfirmed: true })),
    };
  }

  async createSignatureDraft(
    _contractId: string,
    _reviewId: string,
    _signers: SignatureSignerInput[],
  ): Promise<{ editorUrl: string; expiresAt: string }> {
    void _contractId;
    void _reviewId;
    void _signers;
    await delay(240);
    return {
      editorUrl: "https://mock.modusign.example/embedded-draft",
      expiresAt: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
    };
  }

  async getSignatureView(_contractId: string): Promise<LiveSignatureView> {
    void _contractId;
    await delay(120);
    return {
      signature: {
        status: DEMO_CONTRACT.signature.modusign === "COMPLETED" ? "COMPLETED" : "SIGNING",
        modusignStatus: DEMO_CONTRACT.signature.modusign,
        documentId: DEMO_CONTRACT.signature.documentId,
      },
      timeline: DEMO_CONTRACT.timeline,
    };
  }

  async getObligation(_contractId: string): Promise<LiveObligation | null> {
    void _contractId;
    await delay(120);
    return {
      id: DEMO_CONTRACT.obligation.id,
      title: DEMO_CONTRACT.obligation.title,
      dueDate: DEMO_CONTRACT.obligation.dueDate,
      sourcePage: 4,
      sourceText: "인스타그램 게시물 4건을 제출한다.",
      confidence: 0.95,
      evidenceUrl: DEMO_CONTRACT.obligation.evidenceUrl,
      status: DEMO_CONTRACT.obligation.status,
      submittedAt: DEMO_CONTRACT.obligation.submittedAt,
      reviewedAt: null,
      paymentConditionMet: false,
    };
  }

  async createObligationEvidenceLink(
    _contractId: string,
    _obligationId: string,
  ): Promise<{ publicUrl: string; expiresAt: string }> {
    void _contractId;
    void _obligationId;
    await delay(120);
    return {
      publicUrl: "/r/mock-obligation/evidence",
      expiresAt: new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString(),
    };
  }

  async reviewObligation(
    _contractId: string,
    _obligationId: string,
    decision: "APPROVED" | "DISPUTED",
    evidenceUrl: string | null = null,
  ): Promise<LiveObligation> {
    const current = await this.getObligation(_contractId);
    if (!current) {
      throw new PublicApiError(404, "NOT_FOUND", "대표 산출물을 찾을 수 없습니다.");
    }
    return {
      ...current,
      evidenceUrl: current.status === "PENDING" ? evidenceUrl : current.evidenceUrl,
      submittedAt:
        current.status === "PENDING" && evidenceUrl ? new Date().toISOString() : current.submittedAt,
      status: decision,
      reviewedAt: new Date().toISOString(),
      paymentConditionMet: decision === "APPROVED",
    };
  }

  async getRenewalView(_contractId: string): Promise<LiveRenewalView> {
    void _contractId;
    await delay(120);
    return {
      title: DEMO_CONTRACT.summary.title,
      expiryDday: DEMO_CONTRACT.renewal.expiryDday,
      noticeDday: DEMO_CONTRACT.renewal.noticeDday,
      autoRenewalDday: DEMO_CONTRACT.renewal.autoRenewDday,
      currentDecision: null,
      revisitReviewItemIds: [],
    };
  }

  async saveRenewalDecision(
    contractId: string,
    decision: "RENEW_SAME_TERMS" | "RENEW_WITH_CHANGES" | "TERMINATE",
  ): Promise<LiveRenewalView> {
    const current = await this.getRenewalView(contractId);
    return { ...current, currentDecision: decision };
  }

  async getContractPerformance(contractId: string): Promise<ContractPerformance> {
    await delay(120);
    const current = this.performanceByContract.get(contractId)
      ?? createMockContractPerformance(contractId);
    this.performanceByContract.set(contractId, current);
    return structuredClone(current);
  }

  async uploadPerformanceReport(
    contractId: string,
    period: string,
    file: File,
  ): Promise<PerformanceReport> {
    void file;
    await delay(240);
    const current = await this.getContractPerformance(contractId);
    if (current.reports.some((report) => report.period === period)) {
      throw new PublicApiError(409, "REPORT_PERIOD_ALREADY_EXISTS", "이미 등록된 월입니다.");
    }
    const report: PerformanceReport = {
      id: `mock-performance-${period}`,
      period,
      status: "UPLOADED",
      extractedPayload: null,
      currentRevision: null,
      revisionCount: 0,
      revisions: [],
      createdAt: new Date().toISOString(),
    };
    this.performanceByContract.set(
      contractId,
      buildMockContractPerformance(contractId, [...current.reports, report]),
    );
    return structuredClone(report);
  }

  async extractPerformanceReport(
    contractId: string,
    reportId: string,
  ): Promise<PerformanceReport> {
    await delay(700);
    const current = await this.getContractPerformance(contractId);
    const report = current.reports.find((item) => item.id === reportId);
    if (!report) throw new PublicApiError(404, "NOT_FOUND", "리포트를 찾을 수 없습니다.");
    if (report.status !== "UPLOADED") {
      throw new PublicApiError(409, "INVALID_STATUS_TRANSITION", "이미 추출한 리포트입니다.");
    }
    const extracted: PerformanceReport = {
      ...report,
      status: "EXTRACTED",
      extractedPayload: mockExtractedPayload(),
    };
    this.performanceByContract.set(
      contractId,
      buildMockContractPerformance(
        contractId,
        current.reports.map((item) => item.id === reportId ? extracted : item),
      ),
    );
    return structuredClone(extracted);
  }

  async confirmPerformanceReport(
    contractId: string,
    reportId: string,
    input: PerformanceConfirmationInput,
  ): Promise<PerformanceReport> {
    await delay(240);
    const current = await this.getContractPerformance(contractId);
    const report = current.reports.find((item) => item.id === reportId);
    if (!report) throw new PublicApiError(404, "NOT_FOUND", "리포트를 찾을 수 없습니다.");
    if (report.revisionCount !== input.expectedRevision) {
      throw new PublicApiError(409, "REPORT_REVISION_CONFLICT", "최신 값을 다시 확인해주세요.");
    }

    const rate = calculatePerformanceEngagementRate(input.confirmedPayload);
    const flags: PerformanceFlag[] = [];
    if (
      input.confirmedPayload.publishedContentCount !== null
      && input.confirmedPayload.publishedContentCount < 4
    ) {
      flags.push({
        id: crypto.randomUUID(),
        flagType: "DELIVERABLE_COUNT_SHORTFALL",
        expectedContentCount: 4,
        actualContentCount: input.confirmedPayload.publishedContentCount,
        previousEngagementRate: null,
        currentEngagementRate: null,
        issueNote: null,
        basisSnapshots: [
          { sourcePage: 3, sourceText: "월 게시물 4건", confidence: 0.96 },
          { sourcePage: 3, sourceText: "매월 콘텐츠를 게시한다.", confidence: 0.92 },
        ],
      });
    }
    const previous = current.confirmedSeries.find(
      (point) => point.period === previousPerformancePeriod(report.period),
    );
    if (
      previous?.engagementRate
      && rate !== null
      && previous.confirmedPayload.impressions >= 1000
      && input.confirmedPayload.impressions >= 1000
      && previous.engagementRate - rate >= 0.01
      && (previous.engagementRate - rate) / previous.engagementRate >= 0.25
    ) {
      flags.push({
        id: crypto.randomUUID(),
        flagType: "ENGAGEMENT_RATE_DROP",
        expectedContentCount: null,
        actualContentCount: null,
        previousEngagementRate: previous.engagementRate,
        currentEngagementRate: rate,
        issueNote: null,
        basisSnapshots: [],
      });
    }
    if (input.hasIssue && input.issueNote) {
      flags.push({
        id: crypto.randomUUID(),
        flagType: "OWNER_REPORTED_ISSUE",
        expectedContentCount: null,
        actualContentCount: null,
        previousEngagementRate: null,
        currentEngagementRate: null,
        issueNote: input.issueNote,
        basisSnapshots: [],
      });
    }
    const inquiryDrafts = flags.map((flag): PerformanceInquiryDraft => ({
      id: crypto.randomUUID(),
      flagId: flag.id,
      text: flag.flagType === "DELIVERABLE_COUNT_SHORTFALL"
        ? `${report.period} 리포트의 게시물 수는 ${flag.actualContentCount}건으로 기록되어 있습니다. 계약 원문에서 확인한 월 ${flag.expectedContentCount}건과 차이가 있어 해당 월 게시 수와 집계 기준을 확인 부탁드립니다.`
        : flag.flagType === "ENGAGEMENT_RATE_DROP"
          ? `${previous?.period} 반응률 ${((flag.previousEngagementRate ?? 0) * 100).toFixed(2)}%에서 ${report.period} ${((flag.currentEngagementRate ?? 0) * 100).toFixed(2)}%로 낮아진 것으로 계산됩니다. 두 달 리포트의 집계 기준과 변동 사유를 확인 부탁드립니다.`
          : `${report.period} 리포트와 관련해 다음 내용을 확인하고 싶습니다: ${flag.issueNote} 관련 수치와 집계 기준을 확인 부탁드립니다.`,
    }));
    const revision: PerformanceReportRevision = {
      id: crypto.randomUUID(),
      version: input.expectedRevision + 1,
      status: flags.length ? "FLAGGED" : "CONFIRMED",
      confirmedPayload: input.confirmedPayload,
      engagementRate: rate,
      correctionReason: input.correctionReason,
      confirmedAt: new Date().toISOString(),
      flags,
      inquiryDrafts,
    };
    const confirmed: PerformanceReport = {
      ...report,
      status: revision.status,
      currentRevision: revision,
      revisionCount: revision.version,
      revisions: [...report.revisions, revision],
    };
    this.performanceByContract.set(
      contractId,
      buildMockContractPerformance(
        contractId,
        current.reports.map((item) => item.id === reportId ? confirmed : item),
      ),
    );
    return structuredClone(confirmed);
  }

  async getAdjustmentRequest(token: string) {
    await delay(120);
    if (token === DEMO_ADJUSTMENT_REQUEST.token) return DEMO_ADJUSTMENT_REQUEST;
    return DEMO_ADJUSTMENT_REQUEST; // 데모: 토큰 무관 대표 요청 제공
  }

  async openAdjustmentRequest(token: string) {
    void token;
    await delay(120);
  }

  async submitAdjustmentResponses(token: string, responses: PublicResponseInput[]) {
    void token;
    void responses;
    await delay(240);
  }

  async submitObligationEvidence(token: string, evidenceUrl: string) {
    void token;
    void evidenceUrl;
    await delay(240);
  }

  async explainClause(_contractId: string, clauseId: string) {
    await delay(700); // 실제 LLM 호출 체감을 위해 조회보다 살짝 긴 지연
    const card = DEMO_CONTRACT.clauses.find((c) => c.docClauseId === clauseId);
    if (card) {
      return {
        summary: card.aiExplanation,
        officialBasis: card.officialBasis,
        confidence: card.confidence,
      };
    }
    const doc = DEMO_CONTRACT.document.clauses.find((d) => d.id === clauseId);
    return {
      summary:
        doc?.note ??
        "이 조항은 AI가 특별히 확인이 필요하다고 표시한 위험 신호는 없어요. 비교적 무난하게 넘어가셔도 괜찮은 조항이에요.",
      officialBasis: null,
      confidence: null,
    };
  }

  async polishAdjustmentCopy(_contractId: string, text: string): Promise<string> {
    await delay(500);
    return politen(text);
  }
}

class ApiAdapter extends MockAdapter {
  constructor(
    private readonly apiBaseUrl: string,
    private readonly demoBearerToken?: string,
    private readonly ownerAccessTokenProvider: () => Promise<string | null> =
      getOwnerAccessToken,
  ) {
    super();
  }

  async getDashboard(): Promise<{ stats: DashboardStats; contracts: ContractSummary[] }> {
    const ownerHeaders = await this.ownerHeaders();
    const [dashboard, contracts] = await Promise.all([
      this.request<ApiDashboard>("/api/v1/dashboard", { headers: ownerHeaders }),
      this.request<ApiContractListItem[]>("/api/v1/contracts", { headers: ownerHeaders }),
    ]);

    return {
      stats: {
        total: dashboard.total,
        signing: dashboard.signing,
        inProgress: dashboard.in_progress,
        completed: dashboard.completed,
        expiringSoon: dashboard.expiring_soon,
        unresolvedSignals: dashboard.unresolved_signals,
        obligationPending: dashboard.obligation_pending,
        obligationSubmitted: dashboard.obligation_submitted,
        obligationApproved: dashboard.obligation_approved,
        totalCommitted: dashboard.total_committed,
        paymentConditionMet: dashboard.payment_condition_met_amount,
        mostCommonSignalLabel: dashboard.most_common_signal ?? "없음",
      },
      contracts: contracts.map((contract) => ({
        id: contract.id,
        title: contract.title,
        counterpartyName: contract.counterparty_name,
        status: contract.status,
        totalAmount: contract.total_amount,
        date: contract.end_date ? `만료 ${contract.end_date}` : undefined,
        stage: contractStage(contract.status),
        hint: contract.expiry_d_day === null ? undefined : dDayLabel(contract.expiry_d_day),
        dDay: contract.expiry_d_day ?? undefined,
      })),
    };
  }

  async createContract(input: ContractCreateInput): Promise<{ id: string }> {
    const contract = await this.request<ApiContract>("/api/v1/contracts", {
      method: "POST",
      headers: await this.ownerHeaders(),
      body: JSON.stringify({
        title: input.title.trim(),
        counterparty_name: input.counterpartyName.trim(),
      }),
    });
    return { id: contract.id };
  }

  async uploadContractDocument(contractId: string, file: File): Promise<{ id: string }> {
    const formData = new FormData();
    formData.set("file", file);
    formData.set("type", "CONTRACT");
    const document = await this.request<ApiDocument>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/documents`,
      { method: "POST", headers: await this.ownerHeaders(), body: formData },
    );
    return { id: document.id };
  }

  async uploadRevisedContract(contractId: string, file: File): Promise<{ id: string }> {
    const formData = new FormData();
    formData.set("file", file);
    formData.set("type", "REVISED_CONTRACT");
    const document = await this.request<ApiDocument>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/documents`,
      { method: "POST", headers: await this.ownerHeaders(), body: formData },
    );
    return { id: document.id };
  }

  async saveUnderstoodTerms(contractId: string, input: UnderstoodTermInput): Promise<void> {
    await this.request(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/understood-terms`,
      {
        method: "PUT",
        headers: await this.ownerHeaders(),
        body: JSON.stringify({
          duration_text: input.durationText,
          monthly_amount: input.monthlyAmount,
          total_amount: input.totalAmount,
          refund_text: input.refundText,
          termination_text: input.terminationText,
          source_type: "USER_MEMORY",
        }),
      },
    );
  }

  async startContractAnalysis(
    contractId: string,
    documentId: string,
    supportingDocumentIds: string[] = [],
  ): Promise<void> {
    await this.request(`/api/v1/contracts/${encodeURIComponent(contractId)}/analysis`, {
      method: "POST",
      headers: { ...(await this.ownerHeaders()), "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        document_id: documentId,
        supporting_document_ids: supportingDocumentIds,
      }),
    });
  }

  async getContractAnalysis(contractId: string): Promise<ApiAnalysisTask> {
    return this.request<ApiAnalysisTask>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/analysis`,
      { headers: await this.ownerHeaders() },
    );
  }

  async getLiveContractReview(contractId: string): Promise<LiveContractReview> {
    const [contract, task] = await Promise.all([
      this.request<{
        title: string;
        counterparty_name: string;
        status: ContractSummary["status"];
        understood_term: {
          duration_text: string;
          monthly_amount: number | null;
          total_amount: number | null;
          refund_text: string;
          termination_text: string;
        } | null;
      }>(
        `/api/v1/contracts/${encodeURIComponent(contractId)}`,
        { headers: await this.ownerHeaders() },
      ),
      this.getContractAnalysis(contractId),
    ]);
    if (task.status !== "COMPLETED" || !task.result) {
      throw new PublicApiError(409, "ANALYSIS_NOT_COMPLETED", "분석이 아직 완료되지 않았습니다.");
    }
    const documentAccess = await this.request<{ access_url: string }>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/documents/`
        + `${encodeURIComponent(task.document_id)}/access`,
      { headers: await this.ownerHeaders() },
    );
    const extractedFieldById = new Map(
      task.result.extracted_terms.map((term) => [term.id, term.field]),
    );
    return {
      title: contract.title,
      counterpartyName: contract.counterparty_name,
      status: contract.status,
      documentAccessUrl: documentAccess.access_url,
      understood: contract.understood_term
        ? {
            durationText: contract.understood_term.duration_text,
            monthlyAmount: contract.understood_term.monthly_amount,
            totalAmount: contract.understood_term.total_amount,
            refundText: contract.understood_term.refund_text,
            terminationText: contract.understood_term.termination_text,
          }
        : null,
      documentClauses: (task.result.document_clauses ?? []).map((clause) => ({
        id: clause.id,
        documentId: clause.document_id,
        ordinal: clause.ordinal,
        heading: clause.heading,
        title: clause.title,
        sourcePage: clause.source_page,
        sourceText: clause.source_text,
        confidence: clause.confidence,
      })),
      items: task.result.review_items.map((item) => ({
        id: item.id, type: item.type, severity: item.severity,
        plainExplanation: item.plain_explanation,
        sourcePage: item.source_page, sourceText: item.source_text, sourceConfidence: item.source_confidence,
        basisText: item.basis_text, suggestionAccept: item.suggestion_accept,
        suggestionCompromise: item.suggestion_compromise, suggestionRequest: item.suggestion_request,
        relatedExtractedFields: item.related_extracted_term_ids
          .map((termId) => extractedFieldById.get(termId))
          .filter((field): field is string => Boolean(field)),
        userChoice: item.user_choice,
      })),
    };
  }

  async selectReviewItem(contractId: string, itemId: string, choice: SuggestionChoice): Promise<void> {
    await this.request(`/api/v1/contracts/${encodeURIComponent(contractId)}/review-items/${encodeURIComponent(itemId)}`, {
      method: "PATCH", headers: await this.ownerHeaders(), body: JSON.stringify({ user_choice: choice }),
    });
  }

  async createAdjustmentDraft(
    contractId: string,
    reviewItemIds: string[],
    requestTextOverrides: Record<string, string> = {},
    manualItems: ManualAdjustmentDraftInput[] = [],
  ): Promise<LiveAdjustmentDraft> {
    const data = await this.request<{ id: string; items: { review_item_id: string; request_text: string }[] }>(`/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-requests`, { method: "POST", headers: { ...(await this.ownerHeaders()), "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ review_item_ids: reviewItemIds, request_text_overrides: requestTextOverrides, manual_items: manualItems.map((item) => ({ document_clause_id: item.documentClauseId, request_text: item.requestText })), expires_in_hours: 72 }) });
    return { id: data.id, items: data.items.map((item) => ({ reviewItemId: item.review_item_id, requestText: item.request_text })) };
  }

  async polishAdjustmentCopy(contractId: string, text: string): Promise<string> {
    const data = await this.request<{ polished_text: string }>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-copy/polish`,
      {
        method: "POST",
        headers: await this.ownerHeaders(),
        body: JSON.stringify({ text }),
      },
    );
    return data.polished_text;
  }

  async getAdjustmentPreview(contractId: string): Promise<AdjustmentPreview> {
    const review = await this.getLiveContractReview(contractId);
    return {
      items: review.items
        .filter((item) => item.userChoice === "REQUEST" || item.userChoice === "COMPROMISE")
        .map((item) => ({
          id: item.id,
          title: item.plainExplanation,
          text:
            item.userChoice === "REQUEST"
              ? item.suggestionRequest
              : item.suggestionCompromise,
        })),
    };
  }

  async sendAdjustmentDraft(
    contractId: string,
    adjustmentId: string,
  ): Promise<{ publicUrl: string; expiresAt: string }> {
    const sent = await this.request<{ public_url: string; expires_at: string }>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-requests/`
        + `${encodeURIComponent(adjustmentId)}/send`,
      {
        method: "POST",
        headers: { ...(await this.ownerHeaders()), "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ confirmed: true }),
      },
    );
    return { publicUrl: sent.public_url, expiresAt: sent.expires_at };
  }

  async getAdjustmentDetail(
    contractId: string,
    adjustmentId: string,
  ): Promise<LiveAdjustmentDetail> {
    const detail = await this.request<ApiOwnerAdjustmentDetail>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-requests/`
        + encodeURIComponent(adjustmentId),
      { headers: await this.ownerHeaders() },
    );
    const responseById = new Map(
      detail.responses.map((response) => [response.review_item_id, response]),
    );
    const comparisonById = new Map(
      detail.comparisons.map((comparison) => [comparison.review_item_id, comparison]),
    );
    return {
      id: detail.request.id,
      status: detail.request.status,
      expiresAt: detail.request.expires_at,
      items: detail.request.items.map((item) => {
        const response = responseById.get(item.review_item_id);
        const comparison = comparisonById.get(item.review_item_id);
        return {
          reviewItemId: item.review_item_id,
          requestText: item.request_text,
          decision: response?.decision ?? null,
          counterText: response?.counter_text ?? null,
          reason: response?.reason ?? null,
          comparison: comparison
            ? {
                changedSummary: comparison.changed_summary,
                remainingChecks: comparison.remaining_checks,
                finalConfirmation: comparison.final_confirmation,
              }
            : null,
        };
      }),
    };
  }

  async confirmAdjustmentResult(
    contractId: string,
    adjustmentId: string,
    resolutions: AdjustmentResolutionInput[],
  ): Promise<void> {
    await this.request(`/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-confirmation`, {
      method: "POST",
      headers: await this.ownerHeaders(),
      body: JSON.stringify({
        adjustment_request_id: adjustmentId,
        confirmed_items: resolutions.map((item) => ({
          review_item_id: item.reviewItemId,
          resolution: item.resolution,
        })),
        confirmed: true,
      }),
    });
  }

  async createRevisedContractReview(
    contractId: string,
    adjustmentId: string,
    documentId: string,
  ): Promise<RevisedContractReview> {
    const data = await this.request<ApiRevisedContractReview>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/revised-contract-reviews`,
      {
        method: "POST",
        headers: await this.ownerHeaders(),
        body: JSON.stringify({
          adjustment_request_id: adjustmentId,
          document_id: documentId,
        }),
      },
    );
    return mapRevisedContractReview(data);
  }

  async getLatestRevisedContractReview(contractId: string): Promise<RevisedContractReview> {
    const data = await this.request<ApiRevisedContractReview>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/revised-contract-reviews/latest`,
      { headers: await this.ownerHeaders() },
    );
    return mapRevisedContractReview(data);
  }

  async confirmRevisedContractReview(
    contractId: string,
    reviewId: string,
    reviewItemIds: string[],
  ): Promise<RevisedContractReview> {
    const data = await this.request<ApiRevisedContractReview>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/revised-contract-reviews/`
        + `${encodeURIComponent(reviewId)}/confirmation`,
      {
        method: "POST",
        headers: await this.ownerHeaders(),
        body: JSON.stringify({
          confirmed_review_item_ids: reviewItemIds,
          confirmed: true,
        }),
      },
    );
    return mapRevisedContractReview(data);
  }

  async createSignatureDraft(
    contractId: string,
    reviewId: string,
    signers: SignatureSignerInput[],
  ): Promise<{ editorUrl: string; expiresAt: string }> {
    const data = await this.request<{ editor_url: string; expires_at: string }>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/signature-embedded-drafts`,
      {
        method: "POST",
        headers: {
          ...(await this.ownerHeaders()),
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          revised_contract_review_id: reviewId,
          signers: signers.map((signer) => ({
            role: signer.role,
            name: signer.name.trim(),
            signing_method: { type: "EMAIL", value: signer.email.trim() },
          })),
          confirmed: true,
        }),
      },
    );
    return { editorUrl: data.editor_url, expiresAt: data.expires_at };
  }

  async getSignatureView(contractId: string): Promise<LiveSignatureView> {
    const contractPath = encodeURIComponent(contractId);
    const [timeline, signature] = await Promise.all([
      this.request<ApiAuditEvent[]>(`/api/v1/contracts/${contractPath}/timeline`, {
        headers: await this.ownerHeaders(),
      }),
      this.request<ApiSignature>(`/api/v1/contracts/${contractPath}/signature`, {
        headers: await this.ownerHeaders(),
      }).catch((error: unknown) => {
        if (error instanceof PublicApiError && error.status === 404) return null;
        throw error;
      }),
    ]);
    return {
      signature: signature
        ? {
            status: signature.status,
            modusignStatus: signature.modusign_status,
            documentId: signature.modusign_document_id,
          }
        : null,
      timeline: mapTimeline(timeline),
    };
  }

  async getObligation(contractId: string): Promise<LiveObligation | null> {
    const obligations = await this.request<ApiObligation[]>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/obligations`,
      { headers: await this.ownerHeaders() },
    );
    return obligations[0] ? mapObligation(obligations[0]) : null;
  }

  async createObligationEvidenceLink(
    contractId: string,
    obligationId: string,
  ): Promise<{ publicUrl: string; expiresAt: string }> {
    const data = await this.request<{ public_url: string; expires_at: string }>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/obligations/`
        + `${encodeURIComponent(obligationId)}/evidence-link`,
      {
        method: "POST",
        headers: {
          ...(await this.ownerHeaders()),
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ expires_in_hours: 72 }),
      },
    );
    return { publicUrl: data.public_url, expiresAt: data.expires_at };
  }

  async reviewObligation(
    contractId: string,
    obligationId: string,
    decision: "APPROVED" | "DISPUTED",
    evidenceUrl: string | null = null,
  ): Promise<LiveObligation> {
    const data = await this.request<ApiObligation>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/obligations/`
        + encodeURIComponent(obligationId),
      {
        method: "PATCH",
        headers: await this.ownerHeaders(),
        body: JSON.stringify({ decision, confirmed: true, evidence_url: evidenceUrl }),
      },
    );
    return mapObligation(data);
  }

  async getRenewalView(contractId: string): Promise<LiveRenewalView> {
    const contractPath = encodeURIComponent(contractId);
    const [contract, contracts] = await Promise.all([
      this.request<ApiContract>(`/api/v1/contracts/${contractPath}`, {
        headers: await this.ownerHeaders(),
      }),
      this.request<ApiContractListItem[]>("/api/v1/contracts", {
        headers: await this.ownerHeaders(),
      }),
    ]);
    const summary = contracts.find((item) => item.id === contractId);
    if (!summary) {
      throw new PublicApiError(404, "NOT_FOUND", "계약을 찾을 수 없습니다.");
    }
    return {
      title: contract.title,
      expiryDday: summary.expiry_d_day,
      noticeDday: summary.termination_notice_d_day,
      autoRenewalDday: summary.auto_renewal_d_day,
      currentDecision: contract.renewal_decision?.decision ?? null,
      revisitReviewItemIds: contract.renewal_decision?.revisit_review_item_ids ?? [],
    };
  }

  async saveRenewalDecision(
    contractId: string,
    decision: "RENEW_SAME_TERMS" | "RENEW_WITH_CHANGES" | "TERMINATE",
  ): Promise<LiveRenewalView> {
    const saved = await this.request<{
      decision: LiveRenewalView["currentDecision"];
      revisit_review_item_ids: string[];
    }>(`/api/v1/contracts/${encodeURIComponent(contractId)}/renewal-decision`, {
      method: "PUT",
      headers: await this.ownerHeaders(),
      body: JSON.stringify({ decision, confirmed: true }),
    });
    const current = await this.getRenewalView(contractId);
    return {
      ...current,
      currentDecision: saved.decision,
      revisitReviewItemIds: saved.revisit_review_item_ids,
    };
  }

  async getContractPerformance(contractId: string): Promise<ContractPerformance> {
    const data = await this.request<ApiContractPerformance>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/performance`,
      { headers: await this.ownerHeaders() },
    );
    return mapContractPerformance(data);
  }

  async uploadPerformanceReport(
    contractId: string,
    period: string,
    file: File,
  ): Promise<PerformanceReport> {
    const formData = new FormData();
    formData.set("period", period);
    formData.set("file", file);
    const data = await this.request<ApiPerformanceReport>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/performance-reports`,
      {
        method: "POST",
        headers: { ...(await this.ownerHeaders()), "Idempotency-Key": crypto.randomUUID() },
        body: formData,
      },
    );
    return mapPerformanceReport(data);
  }

  async extractPerformanceReport(
    contractId: string,
    reportId: string,
  ): Promise<PerformanceReport> {
    const data = await this.request<ApiPerformanceReport>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/performance-reports/`
        + `${encodeURIComponent(reportId)}/extract`,
      {
        method: "POST",
        headers: { ...(await this.ownerHeaders()), "Idempotency-Key": crypto.randomUUID() },
      },
    );
    return mapPerformanceReport(data);
  }

  async confirmPerformanceReport(
    contractId: string,
    reportId: string,
    input: PerformanceConfirmationInput,
  ): Promise<PerformanceReport> {
    const data = await this.request<ApiPerformanceReport>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/performance-reports/`
        + encodeURIComponent(reportId),
      {
        method: "PATCH",
        headers: { ...(await this.ownerHeaders()), "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          expected_revision: input.expectedRevision,
          confirmed_payload: performanceConfirmedPayloadToApi(input.confirmedPayload),
          has_issue: input.hasIssue,
          issue_note: input.issueNote,
          correction_reason: input.correctionReason,
        }),
      },
    );
    return mapPerformanceReport(data);
  }

  async getAdjustmentRequest(token: string): Promise<AdjustmentRequestPublic> {
    const data = await this.request<ApiPublicAdjustment>(
      `/api/v1/public/adjustment-requests/${encodeURIComponent(token)}`,
    );
    return {
      token,
      contractTitle: data.contract_title,
      status: data.status,
      items: data.items.map((item) => ({
        clauseId: item.item_id,
        beforeText: item.before_text ?? undefined,
        sourcePage: item.source_page ?? undefined,
        requestText: item.request_text,
        officialBasis: null,
      })),
    };
  }

  async openAdjustmentRequest(token: string): Promise<void> {
    await this.request(`/api/v1/public/adjustment-requests/${encodeURIComponent(token)}/open`, {
      method: "POST",
    });
  }

  async submitAdjustmentResponses(
    token: string,
    responses: PublicResponseInput[],
  ): Promise<void> {
    await this.request(`/api/v1/public/adjustment-requests/${encodeURIComponent(token)}/responses`, {
      method: "POST",
      body: JSON.stringify({
        responses: responses.map((response) => ({
          item_id: response.itemId,
          decision: response.decision,
          counter_text: response.counterText?.trim() || null,
          reason: response.reason?.trim() || null,
        })),
      }),
    });
  }

  async submitObligationEvidence(token: string, evidenceUrl: string): Promise<void> {
    await this.request<{ submitted: true }>(
      `/api/v1/public/obligations/${encodeURIComponent(token)}/evidence`,
      {
        method: "POST",
        body: JSON.stringify({ evidence_url: evidenceUrl }),
      },
    );
  }

  private async ownerHeaders(): Promise<HeadersInit> {
    const accessToken =
      this.demoBearerToken || (await this.ownerAccessTokenProvider());
    if (!accessToken) {
      throw new PublicApiError(
        401,
        "OWNER_AUTH_REQUIRED",
        "로그인이 필요합니다. 다시 로그인해 주세요.",
      );
    }
    return { Authorization: `Bearer ${accessToken}` };
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.apiBaseUrl}${path}`, {
        ...init,
        cache: "no-store",
        credentials: "omit",
        headers: {
          Accept: "application/json",
          ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
          ...init.headers,
        },
      });
    } catch {
      throw new PublicApiError(0, "NETWORK_ERROR", "요청을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
    }

    const envelope = (await response.json().catch(() => null)) as ApiEnvelope<T> | null;
    if (!response.ok || !envelope?.data) {
      throw new PublicApiError(
        response.status,
        envelope?.error?.code ?? "REQUEST_FAILED",
        envelope?.error?.message ?? "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      );
    }
    return envelope.data;
  }
}

function contractStage(status: ContractSummary["status"]): string {
  const labels: Record<ContractSummary["status"], string> = {
    DRAFT: "계약서 준비",
    ANALYZING: "분석 중",
    REVIEW_REQUIRED: "검토 필요",
    NEGOTIATING: "조정 진행",
    READY_TO_SIGN: "서명 준비",
    SIGNING: "서명 중",
    SIGNED: "서명 완료",
    IN_PROGRESS: "이행 중",
    COMPLETED: "완료",
    RENEWAL_DUE: "재계약 검토",
  };
  return labels[status];
}

function dDayLabel(dDay: number): string {
  if (dDay === 0) return "오늘 만료";
  return dDay > 0 ? `만료 D-${dDay}` : `만료 ${Math.abs(dDay)}일 지남`;
}

/**
 * NEXT_PUBLIC_USE_MOCK=false와 NEXT_PUBLIC_API_BASE_URL을 함께 설정하면 공개 API와
 * 대시보드가 실 API를 호출한다. 소유자 API의 로컬 mock 검증에는 데모 Bearer 토큰만 쓴다.
 */
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
const demoBearerToken = process.env.NEXT_PUBLIC_DEMO_BEARER_TOKEN;
const useMock = process.env.NEXT_PUBLIC_USE_MOCK !== "false" || !apiBaseUrl;
export const isUsingMock = useMock;
export const isUsingDemoOwnerToken = !useMock && Boolean(demoBearerToken);

export const adapter: DataAdapter = useMock
  ? new MockAdapter()
  : new ApiAdapter(apiBaseUrl, demoBearerToken, getOwnerAccessToken);
