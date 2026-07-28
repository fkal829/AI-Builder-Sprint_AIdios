import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "계약 대시보드",
};

const summary = [
  { label: "진행 중 계약", value: "0" },
  { label: "확인 필요 조항", value: "0" },
  { label: "만료 임박", value: "0" },
] as const;

export default function DashboardPage() {
  return (
    <main className="page">
      <header className="page__header">
        <div>
          <span className="eyebrow">계약 현황</span>
          <h1>대시보드</h1>
        </div>
        <Link className="button button--primary" href="/contracts/new">
          새 계약 등록
        </Link>
      </header>

      <section className="card-grid" aria-label="계약 요약">
        {summary.map((item) => (
          <article className="card" key={item.label}>
            <span className="card__label">{item.label}</span>
            <strong className="card__value">{item.value}</strong>
          </article>
        ))}
      </section>
    </main>
  );
}
