Your king just now I won up your sleep now in the E topic AI so you can API first contract six two top one issue the AI uses it's me it's mean spoon email the domino the towers quality import let's like some of you some day I got the element I'm going to say well I told it I was using final in our front end finer front end table fuck you final final final sensation incredible to the final sensation let's go check off

`apps/frontend`(단디계약 Next.js UI)에서 AI가 관여하는 지점, 관여하지 않는 지점,
AI 출력을 화면에 표시할 때 지키는 규칙을 기록한다. 모델 호출·프롬프트·평가 결과는
루트 [`AI_USAGE.md`](../../AI_USAGE.md)에 있고, 이 문서는 그 결과를 소비하는 쪽만 다룬다.

## 1. 기본 경계

프론트엔드는 어떤 AI 모델도 직접 호출하지 않는다.

- Upstage Document Parse·Universal Extraction, Solar Chat 호출은 전부 `apps/api` 뒤에 있다.
- 브라우저는 FastAPI가 검증·저장한 결과만 받아 렌더링한다.
- 브라우저 번들에 Upstage·Solar·모두싸인·Supabase 키를 넣지 않는다.
  `NEXT_PUBLIC_*` 변수는 API base URL, mock 스위치, 로컬 데모 Bearer 토큰뿐이다.
- 외부 통신 지점은 `src/lib/adapter.ts` 한 곳으로 모았다. 화면 컴포넌트는 `fetch`를
  직접 쓰지 않는다.

따라서 이 앱의 "AI 활용"은 **모델 호출이 아니라 모델 출력의 표현 방식**이 전부다.

## 2. AI 유래 데이터가 들어오는 경로

`src/lib/adapter.ts`의 `DataAdapter` 인터페이스를 `MockAdapter`와 `ApiAdapter`가 같이
구현한다. `NEXT_PUBLIC_USE_MOCK=false`이고 `NEXT_PUBLIC_API_BASE_URL`이 있을 때만 실 API를
호출하고, 그 외에는 mock으로 떨어진다(`isUsingMock`).

API 응답 중 AI가 만든(또는 AI 추출에 근거한) 필드는 다음과 같다.

| 응답 필드 | 프론트 타입 | 화면에서의 쓰임 |
| --- | --- | --- |
| `review_items[].plain_explanation` | `LiveReviewItem.plainExplanation` | 조항 카드의 "쉬운 설명" |
| `review_items[].suggestion_accept / _compromise / _request` | `suggestionAccept` 외 2종 | 문구 3종 선택지 |
| `review_items[].source_page / source_text / source_confidence` | `sourcePage` 외 2종 | 원문 근거 링크·확신도 |
| `review_items[].type` | `MISMATCH \| NO_BASIS \| UNCLEAR \| MISSING \| NEEDS_CHECK` | 신호 라벨(판정 아님) |
| `comparisons[].changed_summary / remaining_checks / final_confirmation` | `LiveAdjustmentDetail.items[].comparison` | 역제안 "AI 비교" 블록 |
| `revised-contract-reviews.items[].match_status / confidence` | `RevisedContractReview` | 수정 계약서 대조 결과 |
| `obligations[].source_page / source_text / confidence` | `LiveObligation` | 산출물 근거 표시 |
| `analysis.status / error_code` | `ApiAnalysisTask` | 분석 진행·실패 화면 |

## 3. 화면별 AI 표시 지점

| 화면 | 경로 | AI 관여 내용 |
| --- | --- | --- |
| 업로드 + 5문항 | `/contracts/new` | AI 없음. 이후 대조의 기준이 되는 "내가 이해한 조건"을 수집 |
| 분석 진행 | `/contracts/[id]/analysis` | 분석 작업 2초 폴링, Evaluator 단계 문구 3단, `DOCUMENT_PARSE_FAILED` 안내 분기 |
| 계약서 뷰어 | `/contracts/[id]` | 원문 2단 뷰어 + 조항별 `explainClause` 온디맨드 설명, 확신도 % 표기 |
| 조항 상세 | `/contracts/[id]/clauses/[clauseId]` | `ClauseCard`가 원문·이해조건·AI 설명·근거·제안 3종을 층위별로 분리 |
| 조정 요청서 | `/contracts/[id]/request` | AI 제안 문구를 초안으로 싣고 사용자가 수정·삭제. 톤 완충기는 P1 규칙 기반 |
| 응답·역제안 | `/contracts/[id]/responses` | Solar 역제안 비교(달라진 점·남은 확인사항·최종 확인) 표시 |
| 수정 계약서 대조 | `/contracts/[id]/revision` | 서버의 결정적 대조 결과(`MATCHED` / `NEEDS_CONFIRMATION`)를 항목별 체크로 표시 |
| 광고효과 관리 | `/contracts/[id]/performance`, `/performance` | **P2 목업.** 리포트 지표 추출 확신도 UI만 있고 performance API를 호출하지 않는다 |
| 대행사 공개 | `/r/[token]`, `/r/[token]/respond` | AI가 생성하고 사장님이 확정한 요청 문구를 원문과 나란히 열람·응답 |

## 4. AI 출력을 다룰 때의 UI 규칙

프론트엔드가 실제로 담당한 AI 관련 작업은 대부분 이 규칙을 강제하는 일이다.

1. **다섯 층위 분리** — `components/LayerBlock.tsx`가 원문(사실) / 내가 이해한 조건 /
   AI 해석(추정) / 공식 기준 / 조정 요청안(미확정)을 배경·테두리·라벨로 항상 구분한다.
   AI 층은 점선 테두리로 그려 사실과 추정을 시각적으로 섞지 않는다.
2. **판정하지 않는다** — 경고색(빨강)을 팔레트에서 뺐다. AI 신호는 "다릅니다 /
   근거를 찾지 못했습니다 / 확인이 필요합니다"로만 표현하고 위험·불법 같은 단정을 쓰지 않는다.
3. **근거 필수** — AI 설명 옆에는 항상 `components/SourceLink.tsx`로 원문 페이지·문장을
   붙인다. 근거가 없으면 값을 강조하지 않고 확인 필요 상태로 남긴다.
4. **확신도 병기** — `source_confidence`, `confidence`를 `LayerBlock`의 `meta` 자리에
   "확신도 NN%"로 노출한다. 이 값은 백엔드 정의대로 **비보정 자기평가값**이며 법적
   정확도가 아니다. 프론트엔드에서 임의로 재계산·가공하지 않는다.
5. **AI 한계 고지** — `ClauseCard`의 마지막 블록(⑥)에 "AI는 계약서와 답변만 근거로
   판단합니다. 실제 법적 효력은 다를 수 있습니다."를 항상 렌더링한다.
6. **선택 중심 완주** — AI 문구는 초안일 뿐이고 확정은 사용자의 선택
   (원안 수용 / 절충 / 요청)으로만 이뤄진다. 사용자가 조항을 직접 추가할 수도 있으며,
   그 카드에는 AI 제안 3종이 없다는 것을 명시한다(`origin: "auto" | "manual"`).
7. **비가역 행동 전 확인** — 링크 생성·발송·서명 요청은 `ConfirmModal`을 거치고, AI 결과가
   자동으로 발송·수락·서명·승인·재계약을 트리거하지 않는다.
8. **실패·빈 상태 구현** — 파싱 실패, 불일치 0건, 무응답, 전부 거절, 링크 만료를
   `/states` 갤러리와 각 화면 분기에 모두 구현했다. AI 실패를 성공처럼 보이게 하지 않는다.

## 5. 프론트엔드에서 AI를 쓰지 않는 부분

계산과 상태 판단은 모델에 맡기지 않는다.

- `src/lib/format.ts` — 금액·백분율 표시. 계산은 코드로만 한다.
- `src/lib/status.ts` — 내부 enum → 쉬운 한국어 라벨·톤 매핑(고정 테이블).
- `src/lib/adapter.ts`의 `contractStage`, `dDayLabel`, `auditEventLabel` — 상태·D-day·
  타임라인 라벨 변환은 전부 결정적 매핑이다.
- `src/lib/tone.ts`의 `politen()` — 톤 완충 P1은 **규칙 기반 문자열 처리**다. 감정 꼬리표를
  지우고 정중한 어미를 붙일 뿐 문장을 재구성하지 않는다. 실제 변환을 Solar로 옮길 때
  이 함수만 교체하도록 입출력 형태를 고정해 뒀다.
- `src/lib/requestDraft.ts`, `understood.ts`, `reportDemo.ts` — 초안·설문·데모 리포트
  보관용 localStorage/sessionStorage. AI 호출 없음.

## 6. mock 모드에서 표시되는 값

- `src/lib/mock.ts`의 대표 계약(광안리 카페)과 확신도 수치(0.8~0.95)는 **가상 데이터**이며
  실제 모델 출력이 아니다.
- `MockAdapter.explainClause`는 700ms 지연을 넣어 LLM 호출 체감만 흉내 낸다.
- `/`(데모 런처)와 `/states`의 데이터도 전부 가상이며, 런처 화면에 "외부 API는 호출하지
  않는다"를 문구로 명시했다.
- 광고효과 화면(6.14)의 추출 지표·확신도는 P2 목업 값이다.

## 7. 보안 처리

- API 키·서비스 키·운영용 정적 토큰을 브라우저에 넣지 않는다.
- `NEXT_PUBLIC_DEMO_BEARER_TOKEN`은 로컬 `SUPABASE_MODE=mock` 검증 전용이며 운영 소유자
  인증은 로그인 세션 토큰 연동이 필요하다(README에 명시).
- 계약 원문·공개 토큰·서명 링크를 `console`이나 스토리지에 남기지 않는다.
- 공개 토큰 화면(`/r/[token]`)은 `public-route-headers.mjs`로 색인·캐시를 차단하고,
  `tests/public-route-headers.test.mjs`로 회귀를 막는다.
- 조정 응답(`ADJUSTMENT_RESPONSE`)과 증빙 제출(`OBLIGATION_EVIDENCE`) 토큰 scope는 서로
  재사용할 수 없고, 링크 전달은 사용자가 기존 채널로 직접 한다(자동 발송 없음).

## 8. 개발 과정에서의 AI 코딩 도구 활용

프로덕트 기능과 별개로, 이 앱의 구현에는 AI 코딩 어시스턴트(Claude Code)를 사용했다.
무분별한 생성물을 막기 위해 다음 장치를 뒀다.

- `apps/frontend/CLAUDE.md` — 추측 금지, 최소 구현, 외과적 변경, 검증 가능한 성공 기준을
  요구하는 작업 규칙.
- `AGENTS.md`(루트·앱별) — 앱 경계, 근거 보존, 결정적 계산, 자동 발송 금지 같은 제품 불변
  규칙. Next.js 16 등 학습 데이터와 다른 버전은 `node_modules/next/dist/docs/`를 읽고
  작업하도록 지시한다.
- 검증 — `npm run build`(Turbopack), `npm run lint`, `node --test tests/*.test.mjs`.
  특히 `tests/live-api-wiring.test.mjs`는 P0 흐름이 `MockAdapter`로 되돌아가지 않았는지와
  "링크 생성 후 사용자가 직접 전달" 경계가 유지되는지를 소스 수준에서 검사한다.
- 모든 변경은 이슈 브랜치 → PR → 리뷰 → `develop` 병합으로 처리했다. AI가 만든 코드도
  사람이 검토한 PR을 거친 것만 반영한다.

### 프론트엔드 작업 이력

| 날짜 | 커밋 | 내용 |
| --- | --- | --- |
| 07-29 | `2b9137c` | `apps/web` → `apps/frontend` 재구성 |
| 07-29 | `ae81a91` | 계약서 PDF 드래그앤드롭 업로드·파일 검증 |
| 07-29 | `e58d9cb` | postcss/sharp 취약점 overrides |
| 07-29 | `d9e1456` | 업로드·설문 직접입력, 분석결과 2단 뷰어 |
| 07-31 | `733c3f0` | 뷰어에서 조정 요청서 작성, 광고효과 관리 목업 |
| 08-01 | `711cadc` | 흰 바탕·하늘색 테마 개편, Dandi 로고 적용 |
| 08-01 | `dfd4ff8` | 대행사 응답화면 원문 대조, 파일 드롭존 공통화 |
| 08-01 | `dda1e72` | 대시보드 첫 화면 집계 정리·레이아웃 재구성 |
| 08-01 | `65b1b14` | 전체 계약 광고효과 모아보기 페이지·진입점 |
| 08-01 | `9e8ac8f` | 산출물 증빙 확인을 광고효과 관리 화면으로 통합 |
| 08-01 | `884ea60` | 뷰어·요청서 미리보기·네비게이션 UI 수정 4건 |
| 08-01 | `c2d01b2` | auth 기능 및 소개 랜딩 페이지 |
| 08-02 | `cb9bb37` | `RequireAuth` preview 우회 판별 hydration 불일치 수정 |

## 9. 남은 항목

- 광고효과 기록·대조(6.14)는 계획대로 P2 목업이며 실제 리포트 지표 추출 API와 연결돼 있지 않다.
- 톤 완충기의 Solar 변환은 P1이며 현재는 규칙 기반 대체 구현이다.
- 운영 소유자 인증 공급자가 확정되지 않아 로컬 데모 Bearer 토큰만 연결돼 있다.
