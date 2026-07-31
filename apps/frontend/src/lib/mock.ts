/* ===========================================================================
   목업 데이터 — 대표 계약: 광안리 카페 × 홍보대행사 SNS·블로그 광고대행 (§16)
   실제 API 연동 전, 이 데이터로 모든 화면이 완결되게 구성.
   Adapter(adapter.ts) 뒤에 두어 이후 실 API로 전환.
   =========================================================================== */
import type {
  AdjustmentRequestPublic,
  ContractDetail,
  ContractDocument,
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
    options: ["6개월", "1년", "2년 이상", "잘 기억 안 나요"],
  },
  {
    key: "monthlyAmount",
    title: "매달 내는 금액은\n얼마로 들으셨어요?",
    options: ["5만원", "10만원", "50만원 이상", "잘 기억 안 나요"],
  },
  {
    key: "totalAmount",
    title: "총 계약금액은\n얼마로 이해하셨어요?",
    options: ["300만원 정도", "600만원 정도", "따로 안 들었어요", "잘 기억 안 나요"],
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
    title: "광고·마케팅 계약 · 파도담 카페",
    counterpartyName: "주식회사 브릿지웨이브",
    status: "NEGOTIATING",
    totalAmount: 6_000_000,
    date: "2026.07.28",
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

/* -------------------------------- 계약서 원문 (분석 결과 좌측 뷰어) --------------------------------
   실제 예시 계약서: 파도담 카페(갑) × 주식회사 브릿지웨이브(을) 광고/마케팅 계약서.
   risk(고/중/저)는 설문 응답·소상공인 관점에서 확인이 필요한 정도로 표시(위법성 판정 아님).
   note는 설문에서 이해한 내용과 계약 원문을 쉬운 말로 대조한 코멘트. */
export const CONTRACT_DOC: ContractDocument = {
  title: "광고/마케팅 계약서",
  parties: "파도담 카페 × 주식회사 브릿지웨이브",
  pageCount: 5,
  pdfUrl: "/example-contract.pdf",
  clauses: [
    {
      id: "c1",
      no: "제1조",
      title: "계약의 목적",
      body: '본 계약은 "갑"과 "을" 간의 업무 제휴를 체결함에 따른 권리와 의무 및 필요한 제반사항을 규정하는 데 그 목적이 있다.',
      risk: "low",
    },
    {
      id: "c2",
      no: "제2조",
      title: "서비스의 정의",
      body: '"을"이 "갑"에게 제공하는 "서비스"는 계약서 제3조 범위 안에서 이루어진다.',
      risk: "low",
    },
    {
      id: "c3",
      no: "제3조",
      title: "서비스의 범위",
      body: '① "을"이 수행할 "서비스"의 범위는 온라인 광고의 기획, 예산편성 및 집행, 광고물 제작, 매체선정 건의·섭외, 온라인 프로모션, 여론조사·자료수집 등이며, 수행 시 사전에 "갑"의 승인을 받아야 한다.\n③ 월간 제작·게시 목표는 인스타그램 피드 4건, 릴스 2건, 네이버 블로그 4건, 유튜브 쇼츠 1건으로 한다. 다만 위 수량은 운영상 목표치로서 최소 보장 수량을 의미하지 않으며, "을"은 플랫폼 정책·촬영 일정·광고 성과에 따라 매체·일정·수량을 조정할 수 있다.\n④ "갑"이 시안을 받은 날부터 3영업일 이내에 의견을 전달하지 않으면 승인한 것으로 본다. 기본 수정은 결과물별 1회로 제한한다.',
      risk: "mid",
      note: "월 콘텐츠 수량(피드4·릴스2·블로그4·쇼츠1)은 ‘목표치’이며 최소 보장이 아니에요. 몇 건을 반드시 받을 수 있는지는 계약서에 확정돼 있지 않아요.",
    },
    {
      id: "c4",
      no: "제4조",
      title: "계약 일반",
      body: '① "서비스" 계약기간은 2026년 8월 1일부터 2027년 7월 31일까지로 한다. 계약기간 만료 60일 전까지 당사자 일방이 서면으로 갱신거절 의사를 통지하지 않으면 본 계약은 동일한 기간만큼 자동 연장된다. "을"은 갱신일 30일 전까지 서면으로 통지하여 대행수수료율을 조정할 수 있다.\n③ "서비스"의 구체적 내용은 별도의 "광고게재신청서"를 통해 확정한다.',
      risk: "mid",
      note: "기간은 1년으로 이해하신 것과 같아요. 다만 만료 60일 전까지 서면으로 갱신 거절을 통지하지 않으면 같은 조건으로 1년 자동 연장돼요. 통지 시점을 놓치지 않도록 확인이 필요해요.",
    },
    {
      id: "c5",
      no: "제5조",
      title: "광고비",
      body: '⑥ 본 계약의 총 광고매체 예산은 금 6,000,000원으로 하며 부가가치세는 별도이다. 대행수수료는 광고매체 예산의 15%로 별도 청구한다. 촬영장소 대관료, 모델료, 소품비, 유료 음원 및 외부 제작비는 총 광고매체 예산에 포함되지 않는다.\n⑦ 집행되지 않은 매체비는 다음 달 광고비로 이월하는 것을 원칙으로 한다. 광고 플랫폼이 현금 환불을 승인한 경우에만 플랫폼 수수료와 정산 비용을 공제한 잔액을 환불한다.',
      risk: "high",
      note: "총 광고예산 600만원에 부가세와 대행수수료 15%가 별도예요. ‘300만원 정도’로 이해하신 것과 실제 부담이 달라요. 그리고 효과가 없어도 미집행분은 원칙적으로 환불이 아니라 다음 달로 이월돼요.",
    },
    {
      id: "c6",
      no: "제6조",
      title: "광고비의 청구 및 지급",
      body: '② "갑"은 세금계산서 발행일 기준 30일 이내에 현금으로 광고비를 지급한다.\n③ "갑"은 매월 5일까지 월 광고매체비 500,000원과 이에 대한 대행수수료 15%를 선납한다. 지급이 5영업일 이상 지연되면 "을"은 별도 통지 없이 광고 집행을 중단할 수 있다.\n④ "을"은 다음 달 5일까지 게시 URL, 노출 수 및 클릭 수를 포함한 월간 요약 보고서를 1회 제공한다. 광고계정 접근권한, 원시 로그 및 데이터 내보내기 파일은 별도 합의가 없는 한 제공 대상에 포함되지 않는다.',
      risk: "high",
      note: "매달 5일 광고매체비 50만원+수수료를 선납하는 구조예요. ‘매달 5만원’으로 이해하신 금액과 차이가 커요. 5영업일 이상 밀리면 광고가 중단될 수 있어요.",
    },
    {
      id: "c7",
      no: "제7조",
      title: "제작물의 귀속 및 책임",
      body: '① 완성된 광고물의 소유권은 "갑"이 모든 비용을 지급한 때 "갑"에게 이전된다. 다만 원본 촬영 파일, 편집 가능한 작업 파일, 템플릿, 제작 방법 및 광고계정 설정 정보는 "을"에게 귀속된다.\n③ "을"은 완성된 광고물을 포트폴리오·수주 제안·자체 홍보 목적으로 별도의 대가 없이 사용할 수 있다.',
      risk: "mid",
      note: "완성 광고물 소유권은 갑에게 오지만, 원본·작업 파일과 광고계정은 을에게 남아요. 나중에 직접 광고를 이어가려면 확인이 필요해요.",
    },
    {
      id: "c8",
      no: "제8조",
      title: "계약의 양도",
      body: '"을"은 "갑"의 서면승인 없이 본 계약상의 권리·의무의 일부 또는 전부를 제3자에게 양도·이전하거나 담보로 제공할 수 없다.',
      risk: "low",
    },
    {
      id: "c9",
      no: "제9조",
      title: "계약의 해지",
      body: '③ "갑"이 귀책사유 없이 계약을 중도 해지하려는 경우 30일 전에 서면으로 통지하여야 한다. 이미 집행되거나 확정된 매체비와 제작비는 환불하지 않으며, "갑"은 잔여 계약기간에 해당하는 대행수수료의 70%를 중도해지 정산금으로 지급한다. 환불 가능한 금액은 광고 플랫폼의 정산 완료 후 60일 이내에 지급한다.',
      risk: "high",
      note: "중도 해지 시 잔여 대행수수료의 70%를 정산금으로 내고, 이미 집행된 비용은 돌려받지 못해요. ‘언제든 해지 가능’으로 이해하신 것과 달라요.",
    },
    {
      id: "c10",
      no: "제10조",
      title: "자료제공 및 기밀 유지",
      body: '"갑" 또는 "을"은 계약 과정에서 알게 된 상대방의 영업비밀·기술정보·자료를 계약 이행을 위해서만 사용하고, 계약 종료와 동시에 반환하여야 하며, 종료 후에도 사전 서면 승낙 없이 제3자에게 누설·공개할 수 없다.',
      risk: "low",
    },
    {
      id: "c11",
      no: "제11조",
      title: "신의성실의 의무",
      body: '"갑" 또는 "을"은 본 계약의 목적 달성을 위해 신의성실의 원칙에 따라 상호 관련 업무에 협력한다.',
      risk: "low",
    },
    {
      id: "c12",
      no: "제12조",
      title: "손해 배상",
      body: '② "을"의 손해배상책임은 고의 또는 중대한 과실이 있는 경우에 한하며, 그 한도는 손해 발생 직전 1개월 동안 "갑"이 실제 지급한 대행수수료로 한다. 특별손해, 간접손해, 영업손실 및 기대이익의 상실은 배상 범위에서 제외한다.',
      risk: "mid",
      note: "‘을’의 배상 한도가 직전 1개월 대행수수료로 제한되고, 영업손실·기대이익 같은 손해는 배상에서 빠져요.",
    },
    {
      id: "c13",
      no: "제13조",
      title: "불가항력",
      body: "천재지변, 전쟁, 내란, 폭동, 정부규제 등 당사자가 책임질 수 없는 사유(노사분규 제외)로 의무를 이행하지 못하는 경우 그 책임을 면한다.",
      risk: "low",
    },
    {
      id: "c14",
      no: "제14조",
      title: "소송의 합의 관할",
      body: '본 계약 이행과 관련하여 "갑", "을" 간에 분쟁이 발생할 경우 서울중앙지방법원을 전속적 합의 관할 법원으로 한다.',
      risk: "low",
    },
    {
      id: "c15",
      no: "제15조",
      title: "효력 및 해석",
      body: "본 계약과 광고게재신청서, 견적서, 제안서, 메신저 및 구두 설명의 내용이 서로 다른 경우 본 계약과 가장 최근에 작성된 광고게재신청서의 순서로 우선 적용한다. 구두 설명이나 메신저 내용은 양 당사자가 서명한 문서에 반영되지 않는 한 계약내용으로 보지 않는다.",
      risk: "mid",
      note: "구두·메신저로 들은 설명은 서명 문서에 없으면 계약으로 인정되지 않아요. 안내받은 조건은 계약서에 반영해두는 게 안전해요.",
    },
    {
      id: "c16",
      no: "제16조",
      title: "계약서의 보완",
      body: '본 계약서의 세부적인 이행사항에 관하여 내용 보완이 필요한 경우 "갑", "을"은 상호 협의하여 결정한다.',
      risk: "low",
    },
  ],
};

/* -------------------------------- 대표 계약 상세 -------------------------------- */
export const DEMO_CONTRACT: ContractDetail = {
  summary: DASHBOARD_CONTRACTS[0],
  document: CONTRACT_DOC,
  understood: {
    durationText: "1년",
    monthlyAmount: "5만원",
    totalAmount: "300만원 정도",
    refundText: "효과 없으면 전액 환불",
    terminationText: "언제든 가능",
    sourceType: "USER_MEMORY",
  },
  signalCounts: { mismatch: 3, noBasis: 1, unclear: 2 },
  extracted: [
    {
      field: "contract_period",
      label: "계약 기간",
      value: "1년 (2026.8.1~2027.7.31), 60일 전 미통지 시 자동연장",
      source: {
        page: 2,
        text: "계약기간 만료 60일 전까지 당사자 일방이 서면으로 갱신거절 의사를 통지하지 않으면 본 계약은 동일한 기간만큼 자동 연장된다.",
      },
      confidence: 0.93,
    },
    {
      field: "contract_total_amount",
      label: "총 계약금액",
      value: "총 광고매체 예산 600만원 (부가세 별도) + 대행수수료 15% 별도",
      source: {
        page: 2,
        text: "본 계약의 총 광고매체 예산은 금 6,000,000원으로 하며 부가가치세는 별도이다. 대행수수료는 광고매체 예산의 15%로 별도 청구한다.",
      },
      confidence: 0.95,
    },
    {
      field: "monthly_amount",
      label: "매달 내는 금액",
      value: "월 광고매체비 50만원 + 수수료 15%, 매월 5일 선납",
      source: {
        page: 2,
        text: '"갑"은 매월 5일까지 월 광고매체비 500,000원과 이에 대한 대행수수료 15%를 선납한다.',
      },
      confidence: 0.9,
    },
    {
      field: "termination_penalty",
      label: "중도해지 정산금",
      value: "잔여 대행수수료의 70% + 이미 집행된 비용 환불 불가",
      source: {
        page: 3,
        text: '"갑"은 잔여 계약기간에 해당하는 대행수수료의 70%를 중도해지 정산금으로 지급한다.',
      },
      confidence: 0.9,
    },
    {
      field: "refund",
      label: "환불 조건",
      value: "효과·성과 환불 조항 없음 (미집행분은 익월 이월 원칙)",
      source: {
        page: 2,
        text: "집행되지 않은 매체비는 다음 달 광고비로 이월하는 것을 원칙으로 한다. 광고 플랫폼이 현금 환불을 승인한 경우에만 잔액을 환불한다.",
      },
      confidence: 0.8,
    },
    {
      field: "content_quantity",
      label: "콘텐츠 수량",
      value: "월 목표 피드4·릴스2·블로그4·쇼츠1 (최소 보장 아님)",
      source: {
        page: 1,
        text: "월간 제작·게시 목표는 인스타그램 피드 4건, 릴스 2건, 네이버 블로그 콘텐츠 4건 및 유튜브 쇼츠 1건으로 한다. 다만 위 수량은 운영상 목표치로서 최소 보장 수량을 의미하지 않으며",
      },
      confidence: 0.88,
    },
  ],
  clauses: [
    {
      id: "cl_period",
      title: "계약 기간 · 자동연장",
      docClauseId: "c4",
      state: "COUNTER_RECEIVED",
      signal: "NEEDS_CHECK",
      original: {
        page: 2,
        text: "계약기간은 2026년 8월 1일부터 2027년 7월 31일까지로 한다. 계약기간 만료 60일 전까지 서면으로 갱신거절 의사를 통지하지 않으면 본 계약은 동일한 기간만큼 자동 연장된다.",
      },
      understood: "계약 기간 1년으로 이해",
      aiExplanation:
        "기간은 1년으로 이해하신 것과 같아요. 다만 만료 60일 전까지 서면으로 갱신 거절을 통지하지 않으면 같은 조건으로 1년 자동 연장돼요. 통지 시점을 놓치지 않도록 확인이 필요해요.",
      confidence: 0.93,
      officialBasis:
        "자동갱신 조항은 해지·갱신 통보 기한을 명확히 인지하도록 권고됩니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "자동연장 조항 그대로 두기" },
        { choice: "COMPROMISE", label: "절충안", text: "만료 시 자동연장 대신 재협의로" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "만료 60일 전에 갱신 여부를 다시 확인하는 안내 문구를 추가해 주시길 요청드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: {
        decision: "COUNTER",
        counterText: "만료 45일 전 통지",
        reason: "운영상 45일 전 갱신 확인으로 제안드립니다.",
      },
    },
    {
      id: "cl_monthly",
      title: "매달 내는 금액",
      docClauseId: "c6",
      state: "AGREED",
      signal: "MISMATCH",
      original: {
        page: 2,
        text: '"갑"은 매월 5일까지 월 광고매체비 500,000원과 이에 대한 대행수수료 15%를 선납한다. 지급이 5영업일 이상 지연되면 "을"은 별도 통지 없이 광고 집행을 중단할 수 있다.',
      },
      understood: "매달 5만원 정도로 이해",
      aiExplanation:
        "매달 5일에 광고매체비 50만원과 수수료 15%를 선납하는 구조예요. ‘매달 5만원’으로 이해하신 것과 차이가 커요. 5영업일 이상 밀리면 광고가 중단될 수 있어요.",
      confidence: 0.9,
      officialBasis: "정기 지급액과 지연 시 효과(집행 중단 등)는 계약서에서 명확히 확인하도록 권고됩니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "월 50만원 선납 그대로" },
        { choice: "COMPROMISE", label: "절충안", text: "초기 2개월은 낮춰 시작" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "월 선납 금액과 시점을 다시 확인하고, 초기 부담을 낮출 수 있는지 문의드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: { decision: "ACCEPT" },
    },
    {
      id: "cl_content",
      title: "콘텐츠 수량 · 보장",
      docClauseId: "c3",
      state: "AGREED",
      signal: "UNCLEAR",
      original: {
        page: 1,
        text: "월간 제작·게시 목표는 인스타그램 피드 4건, 릴스 2건, 네이버 블로그 4건, 유튜브 쇼츠 1건으로 한다. 다만 위 수량은 운영상 목표치로서 최소 보장 수량을 의미하지 않는다.",
      },
      understood: null,
      aiExplanation:
        "월 콘텐츠 수량(피드4·릴스2·블로그4·쇼츠1)은 ‘목표치’이고 최소 보장이 아니에요. 몇 건을 반드시 받을 수 있는지는 계약서에 확정돼 있지 않아요.",
      confidence: 0.83,
      officialBasis: "산출물 최소 수량·게시 주기는 계약서에 수치로 명시하도록 권고됩니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "목표치 그대로 두기" },
        { choice: "COMPROMISE", label: "절충안", text: "월 최소 게시 건수만 명시" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "월 최소 보장 수량(예: 피드 4건)을 계약서에 명시해 주시길 요청드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: { decision: "ACCEPT" },
    },
    {
      id: "cl_penalty",
      title: "중도 해지 정산금",
      docClauseId: "c9",
      state: "KEPT_ORIGINAL",
      signal: "MISMATCH",
      original: {
        page: 3,
        text: '"갑"이 귀책사유 없이 중도 해지하려는 경우 30일 전 서면 통지하여야 하며, 이미 집행·확정된 매체비와 제작비는 환불하지 않고, 잔여 계약기간에 해당하는 대행수수료의 70%를 중도해지 정산금으로 지급한다.',
      },
      understood: "중도 해지 언제든 가능으로 이해",
      aiExplanation:
        "중도 해지 시 잔여 대행수수료의 70%를 정산금으로 내고, 이미 집행된 비용은 돌려받지 못해요. ‘언제든 가능’으로 이해하신 것과 달라요.",
      confidence: 0.9,
      officialBasis: "중도해지 정산금 비율은 분쟁 사례집에서 확인이 필요한 항목으로 다뤄집니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "정산금 70% 그대로" },
        { choice: "COMPROMISE", label: "절충안", text: "정산금 비율을 낮춰 조정 제안" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "중도해지 정산금 비율(잔여 수수료의 70%)을 낮춰주실 수 있는지 문의드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: {
        decision: "REJECT",
        reason: "사내 규정상 정산금 비율은 조정이 어렵습니다.",
      },
    },
    {
      id: "cl_total",
      title: "총 계약금액",
      docClauseId: "c5",
      state: "AGREED",
      signal: "MISMATCH",
      original: {
        page: 2,
        text: "본 계약의 총 광고매체 예산은 금 6,000,000원으로 하며 부가가치세는 별도이다. 대행수수료는 광고매체 예산의 15%로 별도 청구한다.",
      },
      understood: "총 300만원 정도로 이해",
      aiExplanation:
        "총 광고매체 예산 600만원에 부가세와 대행수수료 15%가 별도로 붙어요. ‘300만원 정도’로 이해하신 총액과 실제 부담이 달라요.",
      confidence: 0.92,
      officialBasis: "부가세·수수료 등 부대비용을 포함한 총부담 금액을 명확히 확인하도록 권고됩니다.",
      suggestions: [
        { choice: "ACCEPT", label: "원안 수용", text: "예산·수수료 그대로" },
        { choice: "COMPROMISE", label: "절충안", text: "예산을 단계적으로 집행" },
        {
          choice: "REQUEST",
          label: "요청안",
          text: "부가세·수수료를 포함한 실제 총부담 금액을 명확히 안내해 주시길 요청드립니다.",
        },
      ],
      userChoice: "REQUEST",
      agencyResponse: { decision: "ACCEPT" },
    },
    {
      id: "cl_refund",
      title: "환불 조건",
      docClauseId: "c5",
      state: "ACCEPT_SELECTED",
      signal: "NO_BASIS",
      original: {
        page: 2,
        text: "집행되지 않은 매체비는 다음 달 광고비로 이월하는 것을 원칙으로 한다. 광고 플랫폼이 현금 환불을 승인한 경우에만 플랫폼 수수료와 정산 비용을 공제한 잔액을 환불한다.",
      },
      understood: "효과 없으면 전액 환불로 안내받음",
      aiExplanation:
        "전액 환불로 이해하셨는데, 계약서에는 성과·효과에 따른 환불 조항이 없어요. 미집행분도 원칙적으로 다음 달로 이월돼요.",
      confidence: 0.8,
      officialBasis: "구두로 안내받은 환불·성과 보장은 계약서 명문화가 권고됩니다.",
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
      title: "계약 기간 · 자동연장",
      outcome: "AGREED",
      before: "만료 60일 전 미통지 시 자동연장",
      after: "만료 45일 전 갱신 여부 확인",
      reason: "역제안 수락 — 통지 시점 앞당김",
    },
    {
      title: "매달 내는 금액",
      outcome: "AGREED",
      before: "월 50만원 + 수수료 선납",
      after: "초기 2개월 완화 후 정상 선납",
    },
    {
      title: "총 계약금액",
      outcome: "AGREED",
      before: "예산 600만 + 부가세·수수료 별도",
      after: "총부담 금액 명시로 안내",
    },
    {
      title: "콘텐츠 수량 · 보장",
      outcome: "AGREED",
      before: "월 목표치(최소 보장 아님)",
      after: "월 최소 보장 수량 명시",
    },
    {
      title: "중도 해지 정산금",
      outcome: "KEPT_ORIGINAL",
      before: "잔여 수수료의 70%",
      after: "잔여 수수료의 70%",
      reason: "사내 규정상 조정 불가",
    },
  ],
  renewal: {
    expiryDday: 30,
    noticeDday: 14,
    autoRenewDday: 7,
    previouslyKeptClause: "중도 해지 정산금(잔여 수수료 70%)",
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
