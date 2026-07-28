import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "조정 요청 응답",
};

export default function AdjustmentRequestPage() {
  return (
    <main className="landing__hero">
      <span className="eyebrow">대행사 공개 응답 화면</span>
      <h1>계약조건 조정 요청</h1>
      <p>
        유효한 토큰인지 확인한 뒤 조항별 수락·거절·역제안 폼을
        표시합니다.
      </p>
    </main>
  );
}
