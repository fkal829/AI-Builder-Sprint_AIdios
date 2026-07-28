# 안심홍보계약 웹

소상공인 관리자 화면과 대행사 토큰 응답 화면을 제공하는 Next.js 앱입니다.

## Prerequisites

- Node.js `>=22.13.0`
- FastAPI server on `http://localhost:8000`

## Quick Start

```bash
cp .env.example .env.local
npm install
npm run dev
npm run build
```

## Route groups

- `app/(owner)`: 계약 소유자 화면
- `app/public/adjustment-requests/[token]`: 대행사 조정 응답
- `app/public/obligations/[token]`: 대행사 산출물 증빙 제출

외부 API를 페이지에서 직접 호출하지 말고 `lib/api`의 FastAPI 클라이언트를 사용합니다. Supabase, Upstage, 모두싸인 키는 이 앱에 두지 않습니다.
