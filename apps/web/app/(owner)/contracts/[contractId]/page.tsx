import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "계약 상세",
};

type ContractDetailPageProps = {
  params: Promise<{ contractId: string }>;
};

export default async function ContractDetailPage({
  params,
}: ContractDetailPageProps) {
  const { contractId } = await params;

  return (
    <main className="page">
      <header className="page__header">
        <div>
          <span className="eyebrow">계약 ID · {contractId}</span>
          <h1>계약 검토와 진행 상태</h1>
        </div>
      </header>
      <section className="placeholder">
        <p>
          핵심 조건, 원문 근거, 조항 카드, 조정 이력, 서명과 이행
          타임라인이 이 화면에 모입니다.
        </p>
      </section>
    </main>
  );
}
