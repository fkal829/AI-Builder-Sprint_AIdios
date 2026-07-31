# 안심홍보계약 — 프론트엔드

부산 관광상권 소상공인용 AI 광고대행 계약 CLM. Next.js(App Router) + TypeScript + Tailwind CSS v4.
와이어프레임 v2와 최종기획안의 **P0 전체**를 목업 데이터로 완결되게 구현했습니다.

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
3. **타이핑 없이 완주** — 업로드~서명 필수 경로는 버튼·선택만. 자유 입력(톤완충)은 P1 접힘 경로.
4. **근거 필수** — 모든 지적 옆에 원문 페이지·문장 → `components/SourceLink.tsx`.
5. **비가역 행동 전 확인** — 발송·서명 전 모달 → `components/ConfirmModal.tsx`.
6. **거절된 것을 지우지 않는다** — 합의서에 합의·원안유지 조항이 gray 톤으로 나란히 남음.
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
| ⑧ 변경·확인 합의서 | `/contracts/[id]/agreement` |
| ⑨ 모두싸인 상태 + 타임라인 | `/contracts/[id]/signature` |
| ⑩ 산출물 증빙 확인 | `/contracts/[id]/obligations` |
| ⑪ 만료·재계약 검토 | `/contracts/[id]/renewal` |

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
├─ app/                 # App Router 라우트 (전부 목업 데이터로 동작)
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

`lib/adapter.ts`의 `DataAdapter` 인터페이스만 구현해 교체합니다. 화면 코드는 그대로.
엔드포인트 매핑은 기획안 §12 참고. 외부 상태(모두싸인 등)는 `lib/status.ts`에서 쉬운
한국어로 매핑하고 내부 enum은 별도 유지합니다.

```ts
// class RealAdapter implements DataAdapter { fetch(`${BASE}/api/v1/...`) }
// export const adapter = USE_MOCK ? new MockAdapter() : new RealAdapter();
```

현재는 대행사 공개 조정 응답 화면(`/r/[token]`), 공개 증빙 제출 화면
(`/r/[token]/evidence`), 소상공인 대시보드가 실 API 연동을 지원합니다. `.env.local`에
다음을 설정하면 나머지 화면은 목업으로 유지하면서 해당 화면이 API를 호출합니다. 조정 응답 토큰의
scope는 `ADJUSTMENT_RESPONSE`, 증빙 제출 토큰의 scope는 `OBLIGATION_EVIDENCE`이므로
서로 재사용할 수 없으며, 증빙은 소유자가 별도로 발급한 증빙 제출 링크로 접근해야 합니다.

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_USE_MOCK=false
NEXT_PUBLIC_DEMO_BEARER_TOKEN=local-demo-owner-token
```

`NEXT_PUBLIC_DEMO_BEARER_TOKEN`은 로컬 `SUPABASE_MODE=mock` 검증 전용입니다. 브라우저에
API 키·서비스 키·운영용 정적 토큰을 넣지 않습니다. 운영 소유자 API는 로그인 세션 토큰 연동이
필요합니다.

## 참고

- 모든 데이터는 가상(목업)입니다.
- 디자인 토큰(amber/paper/ink/gray, 경고색 없음)은 `app/globals.css`의 `@theme`.
- Gaegu 폰트는 판단 메모/개발 주석 전용 — 서비스 실제 화면에는 쓰지 않습니다.
