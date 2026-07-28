import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "새 계약 등록",
};

export default function NewContractPage() {
  return (
    <main className="page">
      <header className="page__header">
        <div>
          <span className="eyebrow">1단계 · 계약 등록</span>
          <h1>검토할 계약을 등록하세요.</h1>
        </div>
      </header>
      <section className="placeholder">
        <p>
          PDF 업로드와 ‘내가 안내받고 이해한 조건’ 5문항이 이 영역에
          구현됩니다.
        </p>
      </section>
    </main>
  );
}
