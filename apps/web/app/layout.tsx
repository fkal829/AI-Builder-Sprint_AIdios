import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "안심홍보계약",
    template: "%s | 안심홍보계약",
  },
  description:
    "광고대행 계약의 설명과 문서를 비교하고 조정부터 이행까지 관리합니다.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
