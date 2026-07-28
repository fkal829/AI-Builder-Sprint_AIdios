import Link from "next/link";

export default function HomePage() {
  return (
    <main className="landing">
      <section className="landing__hero">
        <span className="eyebrow">부산 관광상권 소상공인용 CLM</span>
        <h1>읽지 못한 계약을 읽어주고, 하지 못한 말을 대신해드립니다.</h1>
        <p>
          광고대행 계약의 설명과 실제 문서를 비교하고, 조정 요청부터
          전자서명·산출물 확인·재계약 시점까지 한 흐름으로 관리합니다.
        </p>
        <div className="landing__actions">
          <Link className="button button--primary" href="/contracts/new">
            계약 검토 시작
          </Link>
          <Link className="button button--secondary" href="/dashboard">
            데모 대시보드
          </Link>
        </div>
      </section>

      <section className="workflow" aria-labelledby="workflow-title">
        <div>
          <span className="eyebrow">MVP 핵심 흐름</span>
          <h2 id="workflow-title">확인할 근거와 결정할 순간을 분리합니다.</h2>
        </div>
        <ol>
          <li>
            <strong>01. 비교</strong>
            <span>내가 이해한 조건과 계약서 원문을 함께 확인합니다.</span>
          </li>
          <li>
            <strong>02. 조율</strong>
            <span>정중한 요청안을 골라 상대방에게 한 번에 전달합니다.</span>
          </li>
          <li>
            <strong>03. 확정</strong>
            <span>합의·서명·산출물·만료 기록을 한 타임라인에 남깁니다.</span>
          </li>
        </ol>
      </section>
    </main>
  );
}
