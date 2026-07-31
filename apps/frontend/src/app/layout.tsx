import type { Metadata, Viewport } from "next";
import { Noto_Sans_KR, Gaegu } from "next/font/google";
import "./globals.css";

const noto = Noto_Sans_KR({
  weight: ["400", "500", "700", "900"],
  subsets: ["latin"],
  variable: "--font-noto",
  display: "swap",
});

// Gaegu — 판단 메모/개발 주석 전용. 서비스 실제 화면에는 쓰지 않음.
const gaegu = Gaegu({
  weight: ["400", "700"],
  subsets: ["latin"],
  variable: "--font-gaegu",
  display: "swap",
});

export const metadata: Metadata = {
  title: "단디계약",
  description:
    "읽지 못한 계약을 읽어주고, 하지 못한 말을 대신해준다 — 소상공인용 광고대행 계약 CLM",
};
// 파비콘은 src/app/icon.svg 파일 규약으로 자동 등록된다.
// iOS 홈 화면용 apple-icon은 PNG가 필요해 아직 없음(dandi-app-icon.png 미제공).

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#ffffff",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className={`${noto.variable} ${gaegu.variable}`}>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
