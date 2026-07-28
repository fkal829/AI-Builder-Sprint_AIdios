import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "산출물 증빙 제출",
};

export default function ObligationPage() {
  return (
    <main className="landing__hero">
      <span className="eyebrow">대행사 공개 제출 화면</span>
      <h1>산출물 증빙을 제출하세요.</h1>
      <p>
        유효한 토큰인지 확인한 뒤 대표 산출물 URL 입력 폼을 표시합니다.
      </p>
    </main>
  );
}
