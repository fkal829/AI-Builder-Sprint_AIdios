import Link from "next/link";

export default function OwnerLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link className="app-header__brand" href="/">
          안심홍보계약
        </Link>
        <nav aria-label="주요 메뉴">
          <Link href="/dashboard">대시보드</Link>
          <Link href="/contracts/new">새 계약</Link>
        </nav>
      </header>
      {children}
    </div>
  );
}
