# 단디계약 — 프론트엔드

부산 관광상권 소상공인용 AI 광고대행 계약 CLM. Next.js(App Router) + TypeScript + Tailwind CSS v4.
와이어프레임 v2와 최종기획안의 **P0 전체**를 구현했으며, 명시적인 mock/API 모드로
전환할 수 있습니다. 광고효과 기록·대조(6.14)도 mock/API 모드에서 업로드, 추출,
확정·append-only 정정, 계약·전월 대조 조회까지 연결합니다.

> 읽지 못한 계약을 읽어주고, 하지 못한 말을 대신해준다.

## 실행

```bash
npm install
npm run dev     # http://localhost:3000
npm run build   # 프로덕션 빌드 (Turbopack)
```

진입점: `/` (데모 런처). 실제 서비스 진입점은 소상공인 대시보드 `/dashboard`.

## 설계 원칙 (기능보다 우선)

1. **판정하지 않는다** — 경고색(빨강) 없음. "다릅니다 / 근거를 찾지 못했습니다 / 확인이 필요합니다"만 사용.
2. **다섯 층위 분리** — 원문(사실)·내가 이해한 조건·AI 해석(추정)·공식 기준·조정 요청안(미확정)을 색·라벨로 항상 구분 → `components/LayerBlock.tsx`.
3. **선택 중심 완주** — 계약 조건과 조정 결과는 버튼·선택으로 진행하며, 서명자 연락처와
   증빙 URL처럼 외부 처리에 필요한 값만 직접 입력합니다.
4. **근거 필수** — 모든 지적 옆에 원문 페이지·문장 → `components/SourceLink.tsx`.
5. **비가역 행동 전 확인** — 발송·서명 전 모달 → `components/ConfirmModal.tsx`.
6. **조정 이력을 지우지 않는다** — 수락·거절·역제안과 수정 계약서 대조 결과를 함께 보존.
7. **실패·빈 상태 구현** — `/states` 갤러리 + 각 화면 내 분기.
8. **'지급 조건 충족' ≠ 실제 송금** — 산출물 화면에 문구 명시.

## 라우트 맵

### 소상공인 (모바일 우선 · 폰 프레임)
| 화면 | 경로 |
|---|---|
| ⓪ 대시보드 | `/dashboard` |
| ① 업로드 + ② 5문항 | `/contracts/new` |
| ③ AI 분석 진행 | `/contracts/[id]/analysis` |
| ④ 핵심조건·원문 비교 | `/contracts/[id]` |
| ⑤ 조항 카드 상세/문구선택 | `/contracts/[id]/clauses/[clauseId]` |
| ⑥ 조정 요청서 미리보기 | `/contracts/[id]/request` |
| ⑦ 발송 대기 + 역제안 비교 | `/contracts/[id]/responses` |
| ⑧ 수정 계약서 업로드·대조 | `/contracts/[id]/revision` |
| ⑨ 모두싸인 상태 + 타임라인 | `/contracts/[id]/signature` |
| ⑩ 산출물 증빙 확인 | `/contracts/[id]/obligations` |
| ⑪ 광고효과 기록·대조 | `/contracts/[id]/performance` |
| ⑫ 만료·재계약 검토 | `/contracts/[id]/renewal` |

### 대행사 공개 (무가입 · 토큰 접근)
| 화면 | 경로 |
|---|---|
| ① 요청서 열람 | `/r/[token]` |
| ② 조항별 수락/거절/역제안 | `/r/[token]/respond` |
| ③ 응답 완료 | `/r/[token]/done` |
| ④ 산출물 URL 제출 | `/r/[token]/evidence` |

### 기타
- `/` 데모 런처 · `/states` 실패·빈 상태 갤러리(무응답/전부거절/불일치0/파싱실패/첫사용자/링크만료)

## 구조

```
src/
├─ app/                 # App Router 라우트 (P0·6.14 광고효과 mock/API 모드)
├─ components/          # 재사용 컴포넌트
│  ├─ ClauseCard.tsx    #  ★ 조항 카드 — variant="row" | "detail" 두 변형
│  ├─ LayerBlock.tsx    #  층위 분리 프리미티브(원칙 #2)
│  ├─ SourceLink.tsx    #  원문 근거(원칙 #4)
│  ├─ ConfirmModal.tsx  #  비가역 확인(원칙 #5)
│  ├─ AppScreen.tsx     #  소상공인 폰 셸 + CTAButton
│  ├─ AgencyShell.tsx   #  대행사 반응형 셸
│  ├─ Timeline / StatTile / Badge / EmptyState / Bits
└─ lib/
   ├─ types.ts          # §10 데이터 모델 · §11 상태 머신 enum
   ├─ status.ts         # 내부 enum → 쉬운 한국어·색 매핑
   ├─ mock.ts           # 대표 계약(광안리 카페) 데이터
   ├─ adapter.ts        # ★ DataAdapter — Mock↔실 API 전환 지점
   ├─ hooks.ts          # useAsync (로딩/에러/성공)
   └─ format.ts         # 금액·백분율 (계산은 코드로)
```

## 실제 API 연동

`lib/adapter.ts`의 `MockAdapter`와 `ApiAdapter`가 같은 `DataAdapter` 계약을 구현합니다.
API 모드에서는 대시보드, 계약 생성·업로드·분석, 검토 선택, 조정 링크·응답 확정,
수정 계약서 대조, 모두싸인 초안·상태·타임라인, 증빙 링크·제출·검토, 재계약 결정까지
P0 경로가 실제 FastAPI를 호출합니다. 광고효과 화면은 월별 PDF·PNG·JPEG 업로드,
Upstage·Solar 지표 추출, 원문 근거 확인, 최초 확정·정정, 최신 월별 집계·확인 신호·문의
문안 조회를 performance API에 연결합니다. 조정·증빙 공개 링크와 광고효과 문의 문안은
자동 발송하지 않으며 사용자가 기존 채널로 직접 전달합니다.

조정 응답 토큰의 scope는 `ADJUSTMENT_RESPONSE`, 증빙 제출 토큰의 scope는
`OBLIGATION_EVIDENCE`이므로 서로 재사용할 수 없습니다. `.env.local`에는 다음을 설정합니다.

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_USE_MOCK=false
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
```

운영 소유자는 `/login`에서 가입된 이메일로 일회용 링크를 요청합니다. `/auth/callback`이
PKCE 코드를 세션으로 교환하고, `ApiAdapter`는 매 요청마다 현재 access token을 읽어
FastAPI Bearer 헤더로 전달합니다. Supabase Auth의 URL Configuration에는 배포 origin의
`/auth/callback`을 Redirect URL로 등록해야 합니다.

`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`에는 공개 publishable 키(legacy 프로젝트는 anon 키)만
넣습니다. service-role/secret 키와 운영용 정적 토큰은 브라우저에 넣지 않습니다.
`NEXT_PUBLIC_DEMO_BEARER_TOKEN=local-demo-owner-token`은 로컬 `SUPABASE_MODE=mock` API 검증
전용이며 운영에서는 비워 둡니다.

## 참고

- mock 모드와 `/`, `/states` 데모 화면의 데이터는 모두 가상입니다.
- 광고효과 화면은 API가 제공하지 않는 게시물별 상세나 성과 기여도를 임의로 표시하지 않습니다.
- 운영 소유자 인증은 Supabase Auth 이메일 OTP(매직 링크) 세션을 사용합니다.
- 디자인 토큰(amber/paper/ink/gray, 경고색 없음)은 `app/globals.css`의 `@theme`.
- Gaegu 폰트는 판단 메모/개발 주석 전용 — 서비스 실제 화면에는 쓰지 않습니다.
