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
  AdjustmentRequestPublic,
  ContractDetail,
  ContractSummary,
  DashboardStats,
} from "./types";

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
  /** GET /api/v1/public/adjustment-requests/{token} */
  getAdjustmentRequest(token: string): Promise<AdjustmentRequestPublic | null>;
  /** GET /api/v1/contracts/{contractId}/clauses/{clauseId}/explain — 조항 AI 설명(온디맨드) */
  explainClause(contractId: string, clauseId: string): Promise<ClauseExplanation>;
}

/** 네트워크 지연 흉내 (분석 진행 화면 등에서 사용) */
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

class MockAdapter implements DataAdapter {
  async getDashboard() {
    await delay(120);
    return { stats: DASHBOARD_STATS, contracts: DASHBOARD_CONTRACTS };
  }

  async getContract(_contractId: string) {
    await delay(120);
    // 데모: 어떤 id로 진입해도 대표 계약(광안리 카페)을 보여줌.
    // 실 API에서는 미존재 시 reject 해 error 상태로 처리.
    return DEMO_CONTRACT;
  }

  async getAdjustmentRequest(token: string) {
    await delay(120);
    if (token === DEMO_ADJUSTMENT_REQUEST.token) return DEMO_ADJUSTMENT_REQUEST;
    return DEMO_ADJUSTMENT_REQUEST; // 데모: 토큰 무관 대표 요청 제공
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

/**
 * 이후 실제 API 붙일 자리.
 * class RealAdapter implements DataAdapter { ... fetch(`${BASE}/api/v1/...`) }
 * const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK !== "false";
 */
export const adapter: DataAdapter = new MockAdapter();
