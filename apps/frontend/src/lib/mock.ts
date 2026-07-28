/* ===========================================================================
   목업 데이터 — 대표 계약: 광안리 카페 × 홍보대행사 SNS·블로그 광고대행 (§16)
   실제 API 연동 전, 이 데이터로 모든 화면이 완결되게 구성.
   Adapter(adapter.ts) 뒤에 두어 이후 실 API로 전환.
   =========================================================================== */
import type {
  AdjustmentRequestPublic,
  ContractDetail,
  ContractSummary,
  DashboardStats,
  UnderstoodQuestion,
} from "./types";

export const DEMO_CONTRACT_ID = "cxn_gwanganli_cafe";
export const DEMO_TOKEN = "demo-token";

/* -------------------------------- 5문항 정의 (§6.1) -------------------------------- */
export const UNDERSTOOD_QUESTIONS: UnderstoodQuestion[] = [
  {
    key: "durationText",
    title: "계약 기간은 어떻게\n이해하고 계세요?",
    options: ["6개월", "1년", "3년 이상", "잘 기억 안 나요"],
  },
  {
    key: "monthlyAmount",
    title: "월 납부액은\n얼마로 들으셨어요?",
    options: ["5만원", "10만원", "30만원 이상", "잘 기억 안 나요"],
  },
  {
    key: "totalAmount",
    title: "총 계약금액은\n얼마로 이해하셨어요?",
    options: ["120만원 정도", "300만원 정도", "따로 안 들었어요", "잘 기억 안 나요"],
  },
  {
    key: "refundText",
    title: "환불 조건은\n어떻게 안내받으셨어요?",
    options: ["효과 없으면 전액 환불", "부분 환불", "환불 안 됨", "잘 기억 안 나요"],
  },
  {
    key: "terminationText",
    title: "중도 해지는\n가능하다고 들으셨나요?",
    options: ["언제든 가능", "위약금 있음", "안 된다고 들음", "잘 기억 안 나요"],
  },
];

/* -------------------------------- 대시보드 -------------------------------- */
export const DASHBOARD_STATS: DashboardStats = {
  total: 3,
  signing: 1,
  inProgress: 1,
  completed: 1,
  expiringSoon: 1,
  unresolvedSignals: 2,
  obligationPending: 1,
  obligationSubmitted: 0,
  obligationApproved: 0,
  totalCommitted: 6_000_000,
  paymentConditionMet: 0,
  mostCommonSignalLabel: "계약기간 불일치",
};

export const DASHBOARD_CONTRACTS: ContractSummary[] = [
  {
    id: DEMO_CONTRACT_ID,
    title: "SNS광고 계약 · 광안리 카페",
    counterpartyName: "부산관광홍보 주식회사",
    status: "NEGOTIATING",
    totalAmount: 6_000_000,
    date: "2026.07.20",
    stage: "조정 요청 3건",
    hint: "응답 대기 3/5",
  },
  {
    id: "cxn_signboard",
    title: "간판 제작 계약",
    counterpartyName: "오늘의간판",
    status: "IN_PROGRESS",
    totalAmount: 1_800_000,
    date: "2026.06.14",
    stage: "산출물 확인",
    hint: "진행 중",
  },
  {
    id: "cxn_delivery",
    title: "배달앱 입점 계약",
    counterpartyName: "바다배달",
    status: "RENEWAL_DUE",
    totalAmount: 900_000,
    date: "2025.08.05",
    stage: "재계약 검토",
    hint: "만료 D-12",
    dDay: 12,
  },
];

/* -------------------------------- 대표 계약 상세 -------------------------------- */
export const DEMO_CONTRACT: ContractDetail = {
  summary: DASHBOARD_CONTRACTS[0],
  understood: {
    durationText: "계약 기간 1년",
    monthlyAmount: "월 10만원",
    totalAmount: "총 120만원 정도로 이해",
    refundText: "효과 없으면 전액 환불",
    terminationText: "중도 해지 언제든 가능",
    sourceType: "USER_MEMORY",
  },
  signalCounts: { mismatch: 3, noBasis: 2, unclear: 1 },
  extracted: [
    {
      field: "contract_period",
      label: "계약 기간",
      value: "5년",
      source: { page: 1, text: "본 계약의 기간은 계약일로부터 5년으로 한다." },
      confidence: 0.92,
    },
    {
      field: "contract_total_amount",
      label: "총 계약금액",
      value: "600만원 (카드 선결제)",
      source: {
        page: 1,
        text: "총 계약금액은 금 육백만원(₩6,000,000)으로 하며 카드로 선결제한다.",
      },
      confidence: 0.96,
    },
    {
      field: "monthly_amount",
      label: "월 납부액",
      value: "환산 시 월 10만원",
      source: {
        page: 1,
        text: "총 계약금액은 금 육백만원(₩6,000,000)으로 하며 카드로 선결제한다.",
      },
      confidence: 0.88,
    },
    {
      field: "termination_penalty",
      label: "중도해지 위약금",
      value: "잔여금의 40%",
      source: { page: 1, text: "중도 해지 시 잔여 계약금액의 40%를 위약금으로 지급한다." },
      confidence: 0.9,
    },
    {
      field: "government_support",
      label: "정부지원 문구",
      value: "근거 조항 없음",
      source: null,
      confidence: 0.71,
    },
    {
      field: "refund",
      label: "환불 조항",
      value: "전액 환불 조항 없음",
      source: null,
      confidence: 0.74,
    },
    {
      field: "content_quantity",
      label: "콘텐츠 수량",
      value: "수량란 공란",
      source: { page: 1, text: "월별 콘텐츠 제작 수량: (          )" },
      confidence: 0.83,
    },
    {
      field: "auto_renewal",
      label: "자동갱신",
      value: "해지 통보기한 명확하지 않음",
      source: { page: 1, text: "계약 만료 전 별도 협의가 없으면 동일 조건으로 갱신될 수 있다." },
      confidence: 0.69,
    },
  ],
  clauses: [
    {
      id: "cl_period",
      title: "계약 기간",
      state: "COUNTER_RECEIVED",
      signal: "MISMATCH",
      original: { page: 1, text: "본 계약의 기간은 계약일로부터 5년으로 한다." },
      understood: "계약 기간 1년",
      aiExplanation:
        "내가 이해한 내용과 계약서가 다릅니다. 1년으로 이해하셨는데 5년으로 적혀 있어요.",
      confidence: 0.92,
      officialBasis:
        "공정거래위원회 표준약관 기준 — 장기계약은 중도해지·자동갱신 조건을 명확히 하도록 권고",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "5년 그대로 진행" },
        { choice: "COMPROMISE", label: "절충안", text: "3년 + 조건부 연장 제안" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "계약 기간을 1년으로 조정하고, 상호 만족 시 연장하는 방식을 제안드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: {
        decision: "COUNTER",
        counterText: "2년",
        reason: "1년은 콘텐츠 효과가 나기 전이라, 2년을 제안드립니다.",
      },
    },
    {
      id: "cl_total",
      title: "총액 지급 방식",
      state: "AGREED",
      signal: "MISMATCH",
      original: {
        page: 1,
        text: "총 계약금액은 금 육백만원(₩6,000,000)으로 하며 카드로 선결제한다.",
      },
      understood: "월 10만원씩 납부로 이해",
      aiExplanation:
        "총액을 한 번에 카드로 선결제하는 조건이에요. 월 납부로 이해하신 것과 지급 방식이 달라요.",
      confidence: 0.94,
      officialBasis: "선결제 비중이 큰 계약은 분납 전환 요청이 일반적으로 통용됩니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "600만원 선결제 그대로" },
        { choice: "COMPROMISE", label: "절충안", text: "50% 선결제 + 50% 분납" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "월 분납으로 전환하는 방안을 문의드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: { decision: "ACCEPT" },
    },
    {
      id: "cl_content",
      title: "콘텐츠 수량",
      state: "AGREED",
      signal: "MISSING",
      original: { page: 1, text: "월별 콘텐츠 제작 수량: (          )" },
      understood: null,
      aiExplanation:
        "월별 제작 수량이 비어 있어요. 나중에 몇 건을 받을 수 있는지 근거가 없어요.",
      confidence: 0.83,
      officialBasis: "산출물 수량·게시 주기는 계약서에 수치로 명시하도록 권고됩니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "공란 그대로 두기" },
        { choice: "COMPROMISE", label: "절충안", text: "월 2건 이상으로 명시" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "월별 제작 수량을 4건으로 명시해 주시길 요청드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: { decision: "ACCEPT" },
    },
    {
      id: "cl_penalty",
      title: "중도해지 위약금",
      state: "KEPT_ORIGINAL",
      signal: "MISMATCH",
      original: {
        page: 1,
        text: "중도 해지 시 잔여 계약금액의 40%를 위약금으로 지급한다.",
      },
      understood: "중도 해지 언제든 가능으로 이해",
      aiExplanation:
        "중도 해지가 자유롭다고 이해하셨는데, 잔여금의 40%를 위약금으로 내야 하는 조건이에요.",
      confidence: 0.9,
      officialBasis: "과도한 위약금 조항은 분쟁 사례집에서 확인이 필요한 항목으로 다뤄집니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "40% 그대로" },
        { choice: "COMPROMISE", label: "절충안", text: "잔여금의 20%로 조정 제안" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "중도해지 위약금 비율을 낮춰주실 수 있는지 문의드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: {
        decision: "REJECT",
        reason: "사내 규정상 위약금 비율은 조정이 어렵습니다.",
      },
    },
    {
      id: "cl_gov",
      title: "정부지원 문구",
      state: "ACCEPT_SELECTED",
      signal: "NO_BASIS",
      original: { page: 1, text: "본 계약은 정부지원 대상 사업이다." },
      understood: "정부지원 대상이라고 안내받음",
      aiExplanation:
        "정부지원 대상이라는 문구는 있지만, 어떤 지원인지 계약서에서 근거를 찾지 못했어요.",
      confidence: 0.71,
      officialBasis: "지원 사업임을 표시할 때는 근거 사업명·기관을 명시하도록 안내됩니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "문구 그대로 두기" },
        { choice: "COMPROMISE", label: "절충안", text: "지원 근거를 첨부로 요청" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "정부지원 근거(사업명·기관)를 확인할 수 있는 자료를 요청드립니다.",
        },
      ],
      userChoice: "ACCEPT",
      agencyResponse: null,
    },
    {
      id: "cl_refund",
      title: "환불 조항",
      state: "ACCEPT_SELECTED",
      signal: "NO_BASIS",
      original: { page: 1, text: "(환불에 관한 별도 조항 없음)" },
      understood: "효과 없으면 전액 환불로 안내받음",
      aiExplanation:
        "전액 환불로 이해하셨는데, 계약서에서 환불에 관한 조항 자체를 찾지 못했어요.",
      confidence: 0.74,
      officialBasis: "성과·환불 보장을 구두로 안내한 경우 계약서 명문화가 권고됩니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "환불 조항 없이 진행" },
        { choice: "COMPROMISE", label: "절충안", text: "부분 환불 기준 신설 요청" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "안내받은 환불 조건을 계약서에 명문화해 주시길 요청드립니다.",
        },
      ],
      userChoice: "ACCEPT",
      agencyResponse: null,
    },
  ],
  timeline: [
    { id: "e1", label: "계약 업로드", date: "7/20", state: "done" },
    { id: "e2", label: "조건 입력 · AI 분석 완료", date: "7/20", state: "done" },
    { id: "e3", label: "요청 발송 · 대행사 응답", date: "7/22", state: "done" },
    { id: "e4", label: "합의 확정 · 서명 요청", date: "7/23", state: "done" },
    { id: "e5", label: "서명 진행 중 (현재)", date: "7/23", state: "current" },
    { id: "e6", label: "산출물 제출·확인 · 만료 검토", date: "", state: "upcoming" },
  ],
  signature: {
    modusign: "ON_GOING",
    ownerSigned: true,
    agencySigned: false,
    documentId: "modu_9f2c81a",
  },
  obligation: {
    id: "ob_ig4",
    title: "인스타그램 게시물 4건",
    dueDate: "2026-08-20",
    assignee: "AGENCY",
    evidenceType: "URL",
    evidenceUrl: "https://instagram.com/p/demo-4posts",
    status: "SUBMITTED",
    submittedAt: "2026-08-18",
  },
  agreement: [
    {
      title: "계약 기간",
      outcome: "AGREED",
      before: "5년",
      after: "2년",
      reason: "역제안 수락 — 상호 만족 시 연장 협의",
    },
    {
      title: "총액 지급 방식",
      outcome: "AGREED",
      before: "선결제 600만원",
      after: "월 분납",
    },
    {
      title: "콘텐츠 수량",
      outcome: "AGREED",
      before: "수량란 공란",
      after: "월 4건 명시",
    },
    {
      title: "중도해지 위약금",
      outcome: "KEPT_ORIGINAL",
      before: "잔여금의 40%",
      after: "잔여금의 40%",
      reason: "사내 규정상 조정 불가",
    },
  ],
  renewal: {
    expiryDday: 30,
    noticeDday: 14,
    autoRenewDday: 7,
    previouslyKeptClause: "중도해지 위약금 40%",
  },
};

/* -------------------------------- 대행사 공개 요청 (토큰) -------------------------------- */
export const DEMO_ADJUSTMENT_REQUEST: AdjustmentRequestPublic = {
  token: DEMO_TOKEN,
  contractTitle: "SNS·블로그 광고대행 계약",
  ownerLabel: "광안리 카페 사장님",
  estimatedMinutes: 3,
  status: "SENT",
  items: DEMO_CONTRACT.clauses
    .filter((c) => c.userChoice === "REQUEST" || c.userChoice === "COMPROMISE")
    .map((c) => {
      const chosen = c.suggestions.find((s) => s.choice === c.userChoice)!;
      return {
        clauseId: c.id,
        requestText: chosen.text,
        officialBasis: c.officialBasis,
      };
    }),
};
