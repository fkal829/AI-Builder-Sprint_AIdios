export const contractStatuses = [
  "DRAFT",
  "ANALYZING",
  "REVIEW_REQUIRED",
  "NEGOTIATING",
  "READY_TO_SIGN",
  "SIGNING",
  "SIGNED",
  "IN_PROGRESS",
  "COMPLETED",
  "RENEWAL_DUE",
] as const;

export type ContractStatus = (typeof contractStatuses)[number];

export const contractStatusLabels: Record<ContractStatus, string> = {
  DRAFT: "작성 중",
  ANALYZING: "AI 분석 중",
  REVIEW_REQUIRED: "검토 필요",
  NEGOTIATING: "조건 조율 중",
  READY_TO_SIGN: "서명 준비",
  SIGNING: "서명 진행 중",
  SIGNED: "서명 완료",
  IN_PROGRESS: "계약 이행 중",
  COMPLETED: "완료",
  RENEWAL_DUE: "재계약 검토",
};
