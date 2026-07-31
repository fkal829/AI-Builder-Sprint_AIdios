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
import type {
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
  items: { item_id: string; request_text: string }[];
};

type ApiOwnerAdjustmentDetail = {
  request: { id: string };
  responses: {
    review_item_id: string;
    decision: AgencyDecision;
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

type ApiContract = { id: string };
type ApiDocument = { id: string };
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
  id: string; type: LiveReviewItem["type"]; plain_explanation: string; source_page: number | null;
  source_text: string | null; source_confidence: number | null; basis_text: string;
  suggestion_accept: string; suggestion_compromise: string; suggestion_request: string;
  user_choice: SuggestionChoice | null;
};

type ApiAnalysisTask = {
  status: "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";
  error_code: string | null;
  result: { review_items: ApiReviewItem[] } | null;
};

export type LiveReviewItem = {
  id: string;
  type: "MISMATCH" | "NO_BASIS" | "UNCLEAR" | "MISSING" | "NEEDS_CHECK";
  plainExplanation: string;
  sourcePage: number | null;
  sourceText: string | null;
  sourceConfidence: number | null;
  basisText: string;
  suggestionAccept: string;
  suggestionCompromise: string;
  suggestionRequest: string;
  userChoice: SuggestionChoice | null;
};

export type LiveContractReview = {
  title: string;
  counterpartyName: string;
  status: ContractSummary["status"];
  understood: UnderstoodTermInput | null;
  items: LiveReviewItem[];
};

export type LiveAdjustmentDraft = {
  id: string;
  items: { reviewItemId: string; requestText: string }[];
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
  startContractAnalysis(contractId: string, documentId: string): Promise<void>;
  getContractAnalysis(contractId: string): Promise<ApiAnalysisTask>;
  getLiveContractReview(contractId: string): Promise<LiveContractReview>;
  selectReviewItem(contractId: string, itemId: string, choice: SuggestionChoice): Promise<void>;
  createAdjustmentDraft(contractId: string, reviewItemIds: string[]): Promise<LiveAdjustmentDraft>;
  sendAdjustmentDraft(contractId: string, adjustmentId: string): Promise<void>;
  confirmAdjustmentResult(contractId: string, adjustmentId: string): Promise<void>;
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
    .filter((clause) => clause.userChoice === "REQUEST" || clause.userChoice === "COMPROMISE")
    .slice(0, 4);
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

class MockAdapter implements DataAdapter {
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

  async startContractAnalysis(contractId: string, documentId: string) {
    void contractId;
    void documentId;
    await delay(240);
  }

  async getContractAnalysis(_contractId: string): Promise<ApiAnalysisTask> {
    void _contractId;
    await delay(120);
    return { status: "COMPLETED", error_code: null, result: { review_items: [] } };
  }

  async getLiveContractReview(_contractId: string): Promise<LiveContractReview> {
    void _contractId;
    return {
      title: DEMO_CONTRACT.summary.title,
      counterpartyName: DEMO_CONTRACT.summary.counterpartyName,
      status: DEMO_CONTRACT.summary.status,
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
  ): Promise<LiveAdjustmentDraft> {
    void _contractId;
    await delay(120);
    return {
      id: "mock-adjustment",
      items: _reviewItemIds.map((reviewItemId) => ({ reviewItemId, requestText: "조정 요청" })),
    };
  }

  async sendAdjustmentDraft(_contractId: string, _adjustmentId: string): Promise<void> {
    void _contractId;
    void _adjustmentId;
    await delay(120);
  }

  async confirmAdjustmentResult(_contractId: string, _adjustmentId: string): Promise<void> {
    void _contractId;
    void _adjustmentId;
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
}

class ApiAdapter extends MockAdapter {
  constructor(
    private readonly apiBaseUrl: string,
    private readonly demoBearerToken?: string,
  ) {
    super();
  }

  async getDashboard(): Promise<{ stats: DashboardStats; contracts: ContractSummary[] }> {
    const ownerHeaders = this.ownerHeaders();
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
      headers: this.ownerHeaders(),
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
      { method: "POST", headers: this.ownerHeaders(), body: formData },
    );
    return { id: document.id };
  }

  async uploadRevisedContract(contractId: string, file: File): Promise<{ id: string }> {
    const formData = new FormData();
    formData.set("file", file);
    formData.set("type", "REVISED_CONTRACT");
    const document = await this.request<ApiDocument>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/documents`,
      { method: "POST", headers: this.ownerHeaders(), body: formData },
    );
    return { id: document.id };
  }

  async saveUnderstoodTerms(contractId: string, input: UnderstoodTermInput): Promise<void> {
    await this.request(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/understood-terms`,
      {
        method: "PUT",
        headers: this.ownerHeaders(),
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

  async startContractAnalysis(contractId: string, documentId: string): Promise<void> {
    await this.request(`/api/v1/contracts/${encodeURIComponent(contractId)}/analysis`, {
      method: "POST",
      headers: { ...this.ownerHeaders(), "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ document_id: documentId, supporting_document_ids: [] }),
    });
  }

  async getContractAnalysis(contractId: string): Promise<ApiAnalysisTask> {
    return this.request<ApiAnalysisTask>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/analysis`,
      { headers: this.ownerHeaders() },
    );
  }

  async getLiveContractReview(contractId: string): Promise<LiveContractReview> {
    const [contract, task] = await Promise.all([
      this.request<{ title: string; counterparty_name: string; status: ContractSummary["status"]; understood_term: Record<string, unknown> | null }>(
        `/api/v1/contracts/${encodeURIComponent(contractId)}`,
        { headers: this.ownerHeaders() },
      ),
      this.getContractAnalysis(contractId),
    ]);
    if (task.status !== "COMPLETED" || !task.result) {
      throw new PublicApiError(409, "ANALYSIS_NOT_COMPLETED", "분석이 아직 완료되지 않았습니다.");
    }
    return {
      title: contract.title,
      counterpartyName: contract.counterparty_name,
      status: contract.status,
      understood: contract.understood_term as UnderstoodTermInput | null,
      items: task.result.review_items.map((item) => ({
        id: item.id, type: item.type, plainExplanation: item.plain_explanation,
        sourcePage: item.source_page, sourceText: item.source_text, sourceConfidence: item.source_confidence,
        basisText: item.basis_text, suggestionAccept: item.suggestion_accept,
        suggestionCompromise: item.suggestion_compromise, suggestionRequest: item.suggestion_request,
        userChoice: item.user_choice,
      })),
    };
  }

  async selectReviewItem(contractId: string, itemId: string, choice: SuggestionChoice): Promise<void> {
    await this.request(`/api/v1/contracts/${encodeURIComponent(contractId)}/review-items/${encodeURIComponent(itemId)}`, {
      method: "PATCH", headers: this.ownerHeaders(), body: JSON.stringify({ user_choice: choice }),
    });
  }

  async createAdjustmentDraft(contractId: string, reviewItemIds: string[]): Promise<LiveAdjustmentDraft> {
    const data = await this.request<{ id: string; items: { review_item_id: string; request_text: string }[] }>(`/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-requests`, { method: "POST", headers: { ...this.ownerHeaders(), "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ review_item_ids: reviewItemIds, expires_in_hours: 72 }) });
    return { id: data.id, items: data.items.map((item) => ({ reviewItemId: item.review_item_id, requestText: item.request_text })) };
  }

  async sendAdjustmentDraft(contractId: string, adjustmentId: string): Promise<void> {
    await this.request(`/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-requests/${encodeURIComponent(adjustmentId)}/send`, { method: "POST", headers: { ...this.ownerHeaders(), "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ confirmed: true }) });
  }

  async confirmAdjustmentResult(contractId: string, adjustmentId: string): Promise<void> {
    const detail = await this.request<ApiOwnerAdjustmentDetail>(
      `/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-requests/`
        + encodeURIComponent(adjustmentId),
      { headers: this.ownerHeaders() },
    );
    await this.request(`/api/v1/contracts/${encodeURIComponent(contractId)}/adjustment-confirmation`, {
      method: "POST",
      headers: this.ownerHeaders(),
      body: JSON.stringify({
        adjustment_request_id: adjustmentId,
        confirmed_items: detail.responses.map((response) => ({
          review_item_id: response.review_item_id,
          resolution:
            response.decision === "ACCEPT"
              ? "ACCEPT_REQUEST"
              : response.decision === "COUNTER"
                ? "ACCEPT_COUNTERPROPOSAL"
                : "KEEP_ORIGINAL",
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
        headers: this.ownerHeaders(),
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
      { headers: this.ownerHeaders() },
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
        headers: this.ownerHeaders(),
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
          ...this.ownerHeaders(),
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

  private ownerHeaders(): HeadersInit {
    if (!this.demoBearerToken) {
      throw new PublicApiError(
        401,
        "OWNER_AUTH_REQUIRED",
        "소유자 API를 사용하려면 로컬 데모 Bearer 토큰을 설정해 주세요.",
      );
    }
    return { Authorization: `Bearer ${this.demoBearerToken}` };
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

export const adapter: DataAdapter = useMock
  ? new MockAdapter()
  : new ApiAdapter(apiBaseUrl, demoBearerToken);
