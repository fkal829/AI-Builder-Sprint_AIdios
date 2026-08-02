# 단디계약 API 명세서

<!-- markdownlint-configure-file {"MD013": false} -->

> 버전: `0.3.0`<br>
> Base URL: `/api/v1`<br>
> 상세 기계 판독 명세: `packages/contracts/openapi/openapi.yaml`<br>
> 적용 범위: 1~14절은 현재 P0 구현 계약, 15~19절은 6.14 P2-0 확정 설계<br>
> P2 구현 상태: canonical OpenAPI 0/4 `planned`, runtime endpoint 4/4,
> 16.1~16.5·17.2·17.5 구현

이 문서는 백엔드 API와 개발 순서를 사람이 읽을 수 있도록 정리한다. 1~14절의 P0 제품
범위와 사용자 흐름은 `docs/기획안.md`, 15~19절의 6.14 P2 변경분은
`docs/단디계약최종기획안.md`를 기준으로 한다.
그 범위 안에서 필드·enum·응답의 기계 판독 기준은
`packages/contracts/openapi/openapi.yaml`, 영속·전이 불변식의 기준은
`docs/api-data-contract.md`다. 세 문서는 같은 변경에서 함께 맞춘다. 이 문서의 파일
경로 표기는 모두 저장소 루트 기준이다.

15~19절은 `docs/단디계약최종기획안.md` 6.14의 P2-0 확정 설계 구역이다. 현재
신규 4개 operation은 모두 canonical OpenAPI의 활성 operation과 FastAPI runtime에
등록했다. 16.1 공통 접근 기반, 업로드 Document·report·감사 원자 RPC, 추출
attempt·완료·복구 RPC와 비공개 AI Adapter 조합기, append-only 확정·정정·계약별
집계 기반을 구현했다. 17.4의 확정값은 기획안, OpenAPI,
`docs/api-data-contract.md`, 공통 enum·오류에 같은 값으로 유지하고 구조 검증을
통과시킨 뒤 runtime을 추가한다.

## 1. 담당 구분

제품 범위와 사용자 흐름은 최종 기획안을 그대로 적용한다. 다만 최신 팀 실행 결정에 따라
기획안에서 D에게 배정했던 백엔드 구현은 B와 C가 나누어 맡고, D는 백엔드 코드를 직접
개발하지 않고 배포·E2E·데모 검증을 담당한다.

- **B — 문서·AI·공통 기반·이행:** FastAPI 공통 기반, DB·Storage, 문서·분석,
  이행 항목과 증빙 API
- **C — 계약·모두싸인·대시보드:** 계약 생애주기, 조정, 수정 계약서 대조, 모두싸인, 일정·집계
- **D — 배포·QA 검증:** 배포·환경변수 확인, E2E 실행, 데모 데이터와 테스트 증빙;
  백엔드 endpoint·service·repository 구현은 맡지 않음

현재 활성 API 35개의 구현 주 담당은 B 14개, C 21개이며 D가 직접
구현하는 API는 0개다. 이전 데이터 호환용 deprecated `/agreement` 2개는
이 활성 개수에 포함하지 않는다. D는 모든 endpoint의 배포본 E2E와 데모
검증 결과를 제공하지만 코드 구현 소유자는 아니다.

15~19절의 P2 API 4개는 모두 위 현재 구현 개수에 포함했다.

### 1.1 현재 활성 API 담당표

| 담당 | Method | Path | 기능 |
| --- | --- | --- | --- |
| B | `GET` | `/health` | 서버 상태 확인 |
| C | `GET` | `/contracts` | 계약 목록·만료 D-day 조회 |
| C | `POST` | `/contracts` | 계약 생성 |
| C | `DELETE` | `/contracts/{contract_id}` | 조정 요청 발송 전 계약 삭제 |
| C | `GET` | `/contracts/{contract_id}` | 계약 상세 조회 |
| C | `GET` | `/contracts/{contract_id}/timeline` | 감사 타임라인 조회 |
| C | `PUT` | `/contracts/{contract_id}/renewal-decision` | 갱신·조건 변경·종료 의사 저장 |
| B | `POST` | `/contracts/{contract_id}/documents` | 계약 문서 업로드 |
| B | `GET` | `/contracts/{contract_id}/documents/{document_id}/access` | 원문 페이지 임시 접근 |
| B | `PUT` | `/contracts/{contract_id}/understood-terms` | 사용자 이해조건 5문항 저장 |
| B | `POST` | `/contracts/{contract_id}/analysis` | 분석 작업 시작 |
| B | `GET` | `/contracts/{contract_id}/analysis` | 최근 분석 상태·결과 조회 |
| B | `PATCH` | `/contracts/{contract_id}/review-items/{item_id}` | 검토 항목 선택 저장 |
| B | `POST` | `/contracts/{contract_id}/adjustment-copy/polish` | Solar 조정 요청 문구 다듬기 |
| C | `POST` | `/contracts/{contract_id}/adjustment-requests` | 조정 요청 초안 생성 |
| C | `GET` | `/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}` | 소유자용 조정 상세 조회 |
| C | `POST` | `/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}/send` | 조정 링크 활성화 |
| C | `GET` | `/public/adjustment-requests/{token}` | 대행사용 조정 요청 조회 |
| C | `POST` | `/public/adjustment-requests/{token}/open` | 대행사 최초 열람 기록 |
| C | `POST` | `/public/adjustment-requests/{token}/responses` | 대행사 1회 응답 제출 |
| C | `POST` | `/contracts/{contract_id}/adjustment-confirmation` | 최종 조정 결과 확정 |
| C | `POST` | `/contracts/{contract_id}/revised-contract-reviews` | 수정 계약서 대조 생성 |
| C | `GET` | `/contracts/{contract_id}/revised-contract-reviews/latest` | 최신 대조 조회 |
| C | `POST` | `/contracts/{contract_id}/revised-contract-reviews/{review_id}/confirmation` | 대조 최종 확인 |
| C | `POST` | `/contracts/{contract_id}/signature-embedded-drafts` | 모두싸인 임베디드 서명 초안 생성 |
| C | `GET` | `/contracts/{contract_id}/signature` | 서명 상태 조회 |
| C | `POST` | `/webhooks/modusign` | 모두싸인 웹훅 수신 |
| B | `GET` | `/contracts/{contract_id}/obligations` | 이행 항목 목록 조회 |
| B | `POST` | `/contracts/{contract_id}/obligations/{obligation_id}/evidence-link` | 증빙 제출 링크 생성 |
| B | `POST` | `/public/obligations/{token}/evidence` | 대행사 증빙 URL 제출 |
| B | `PATCH` | `/contracts/{contract_id}/obligations/{obligation_id}` | 증빙 승인·이의 처리 |
| B | `POST` | `/contracts/{contract_id}/performance-reports` | 광고효과 리포트 업로드 |
| B | `POST` | `/contracts/{contract_id}/performance-reports/{report_id}/extract` | 광고효과 지표 추출 |
| C | `PATCH` | `/contracts/{contract_id}/performance-reports/{report_id}` | 광고효과 확정값 최초 확인·정정 |
| C | `GET` | `/contracts/{contract_id}/performance` | 계약별 월별 광고효과·계약 대조 조회 |
| C | `GET` | `/dashboard` | 계약·분석·이행 집계 |

## 2. 공통 규칙

### 2.1 인증

소유자 API:

```http
Authorization: Bearer <access_token>
```

공개 API:

- 조정 응답: `ADJUSTMENT_RESPONSE` scope 토큰
- 산출물 증빙: `OBLIGATION_EVIDENCE` scope 토큰
- 공개 토큰은 URL path에만 사용하며 로그와 오류 메시지에 남기지 않는다.

모두싸인 웹훅:

```http
X-Modusign-Webhook-Secret: <configured_secret>
```

### 2.2 멱등 헤더

외부 호출 또는 중복 생성 위험이 있는 API는 다음 헤더가 필요하다.

```http
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
```

적용 API:

- 분석 시작
- 조정 요청 초안 생성
- 조정 링크 활성화
- 수정 계약서 대조 생성·최종 확인
- 모두싸인 임베디드 서명 초안 생성
- 증빙 제출 링크 생성
- 광고효과 리포트 업로드
- 광고효과 지표 추출

같은 키와 같은 요청은 최초 결과를 재생한다. 같은 키에 다른 요청을 사용하면
`409 IDEMPOTENCY_CONFLICT`다.
단, 임베디드 초안의 `editor_url`은 저장하지 않으므로 같은 키 재호출에서 재생하지
않고 `409`를 반환한다.

### 2.3 공통 성공 응답

```json
{
  "data": {},
  "error": null,
  "requestId": "req_123abc"
}
```

### 2.4 공통 실패 응답

```json
{
  "data": null,
  "error": {
    "code": "INVALID_STATUS_TRANSITION",
    "message": "현재 상태에서는 요청을 처리할 수 없습니다."
  },
  "requestId": "req_123abc"
}
```

### 2.5 주요 HTTP 상태

| 상태 | 의미 |
| --- | --- |
| `200` | 조회·수정 성공 |
| `201` | 리소스 생성 성공 |
| `202` | 비동기 분석 작업 접수 |
| `204` | 웹훅 수신 완료, 응답 body 없음 |
| `401` | 인증 실패 |
| `404` | 리소스 없음 또는 권한·scope 은닉 |
| `409` | 상태 전이·중복 제출·멱등 충돌 |
| `410` | 공개 링크 만료 |
| `422` | 요청 스키마 검증 실패 |
| `502` | Solar 역제안 비교 또는 모두싸인 요청 실패 |
| `503` | 분석 작업 접수 또는 외부 기반 서비스 사용 불가 |

### 2.6 공통 경로 변수

| 이름 | 형식 |
| --- | --- |
| `contract_id` | UUID |
| `document_id` | UUID |
| `item_id` | UUID |
| `adjustment_request_id` | UUID |
| `obligation_id` | UUID |
| `token` | 최소 32자 공개 토큰 |

소유자 API의 UUID path 변수가 잘못되면 `422 VALIDATION_ERROR`를 반환한다. 공개
토큰은 열거 방지를 위해 형식·길이·scope·대상 불일치를 모두 `404 NOT_FOUND`로 처리하고,
유효하지만 만료된 토큰만 `410`으로 처리한다.

## 3. 공통·계약 API — B·C

### 3.1 서버 상태 확인

`GET /api/v1/health`

- 인증: 없음
- 담당: B
- 성공: `200 HealthResponse`

```json
{
  "data": {
    "status": "ok"
  },
  "error": null,
  "requestId": "req_123abc"
}
```

### 3.2 계약 목록 조회

`GET /api/v1/contracts`

- 인증: Bearer
- 담당: C
- 성공: `200 ContractListResponse`

목록은 만료일 오름차순, 만료일이 없으면 마지막, 같은 값이면 `id` 오름차순이다.
검색·필터는 P1이므로 P0 목록에는 query parameter가 없다.

계약 목록 항목:

| 필드 | 타입 |
| --- | --- |
| `id` | UUID |
| `title` | string |
| `counterparty_name` | string |
| `status` | `ContractStatus` |
| `total_amount` | integer KRW 또는 null |
| `end_date` | date 또는 null |
| `expiry_d_day` | integer 또는 null |
| `termination_notice_d_day` | integer 또는 null |
| `auto_renewal_d_day` | integer 또는 null |

- 오류: `401`

`auto_renewal_d_day`는 canonical `renewal_type=AUTO`이고 `end_date`가 있을 때
`end_date - 오늘`로 계산하며, `MANUAL`, `NONE` 또는 날짜가 없으면 `null`이다.

### 3.3 계약 생성

`POST /api/v1/contracts`

- 인증: Bearer
- 담당: C
- 성공: `201 ContractResponse`

요청:

```json
{
  "title": "광안리 카페 SNS 광고대행 계약",
  "counterparty_name": "부산홍보대행"
}
```

- 오류: `401`, `422`

계약과 `CONTRACT_CREATED` 감사 이벤트를 하나의 트랜잭션으로 기록한다.

### 3.4 계약 상세 조회

`GET /api/v1/contracts/{contract_id}`

- 인증: Bearer
- 담당: C
- 성공: `200 ContractResponse`
- 오류: `401`, `404`, `422`, `502`

주요 응답 필드:

```json
{
  "id": "contract_uuid",
  "title": "광안리 카페 SNS 광고대행 계약",
  "counterparty_name": "부산홍보대행",
  "status": "REVIEW_REQUIRED",
  "signed_date": "2026-07-29",
  "start_date": "2026-08-01",
  "end_date": "2027-07-31",
  "termination_notice_date": "2027-06-30",
  "renewal_type": "AUTO",
  "total_amount": 6000000,
  "understood_term": {
    "contract_id": "contract_uuid",
    "duration_text": "1년",
    "monthly_amount": 500000,
    "total_amount": 6000000,
    "refund_text": "중도해지 시 일부 환불",
    "termination_text": "중도해지 가능",
    "source_type": "USER_MEMORY"
  },
  "renewal_decision": null,
  "modusign_document_id": null,
  "created_at": "2026-07-29T09:00:00Z",
  "updated_at": "2026-07-29T09:10:00Z"
}
```

canonical 날짜·갱신·금액, 사용자 이해조건, 재계약 의사와 모두싸인 문서 ID는 아직
확정·저장되지 않았더라도 필드를 생략하지 않고 `null`로 반환한다. 저장된
`understood_term`은 새로고침 뒤 조항 카드의 `내가 이해한 조건`을 다시 표시하는 데
사용한다.

### 3.5 조정 요청 발송 전 계약 삭제

`DELETE /api/v1/contracts/{contract_id}`

- 인증: Bearer
- 담당: C
- 성공: `200 ContractDeletionResponse`
- 오류: `401`, `404`, `409`, `422`

삭제는 소유자 본인의 초기 계약에만 허용한다. Contract 상태는 `DRAFT`, `ANALYZING`,
`REVIEW_REQUIRED`, `NEGOTIATING` 중 하나여야 하며, 조정 요청이 있다면 모든 요청이
`DRAFT`여야 한다. 발송 이력이 있는 `SENT`, `OPENED`, `RESPONDED`, `CONFIRMED`,
`EXPIRED` 조정 요청이나 상태와 무관한 모두싸인 Signature 행이 하나라도 있으면 삭제를
거부한다. `READY_TO_SIGN`, `SIGNING`, `SIGNED`, `IN_PROGRESS`, `COMPLETED`,
`RENEWAL_DUE` 계약도 삭제할 수 없다.

성공 시 계약, 업로드 문서 메타데이터, 분석 결과, 검토 항목, 발송 전 조정 초안과 감사
타임라인을 하나의 DB 트랜잭션에서 삭제한다. 비공개 Storage 객체는 DB가 반환한 서버 생성
경로만 삭제하며, 파일명이나 클라이언트 입력 경로를 사용하지 않는다. 상태와 하위 행을
잠근 뒤 조건을 다시 검사하므로 조정 발송 또는 서명 생성과 동시에 실행되어도 둘 중 하나만
성공한다.

```json
{
  "data": {
    "contract_id": "contract_uuid",
    "deleted": true
  },
  "error": null,
  "requestId": "req_123abc"
}
```

### 3.6 계약 감사 타임라인 조회

`GET /api/v1/contracts/{contract_id}/timeline`

- 인증: Bearer
- 담당: C
- 성공: `200 TimelineResponse`
- 정렬: `created_at`, `id` 오름차순
- 오류: `401`, `404`, `422`

`AuditEvent`는 `id`, `event_type`, `actor_type`, `summary`, `created_at`만 외부에 제공한다.
민감한 내부 payload는 반환하지 않는다.

P0 `event_type`은 다음 값으로 제한한다.

```text
CONTRACT_CREATED, CONTRACT_STARTED, CONTRACT_COMPLETED, CONTRACT_RENEWAL_DUE,
DOCUMENT_UPLOADED, UNDERSTOOD_TERMS_SAVED,
ANALYSIS_STARTED, ANALYSIS_RESTARTED, ANALYSIS_COMPLETED, ANALYSIS_FAILED,
REVIEW_ITEM_SELECTION_UPDATED, ADJUSTMENT_DRAFT_CREATED, ADJUSTMENT_SENT,
ADJUSTMENT_OPENED, ADJUSTMENT_RESPONDED, ADJUSTMENT_CONFIRMED,
ADJUSTMENT_EXPIRED, AGREEMENT_CREATED, REVISED_CONTRACT_REVIEW_CREATED,
REVISED_CONTRACT_CONFIRMED, SIGNATURE_DRAFT_CREATED,
SIGNATURE_REQUESTED, SIGNATURE_STARTED,
SIGNATURE_COMPLETED, SIGNATURE_ABORTED, SIGNATURE_FAILED, OBLIGATION_CREATED,
EVIDENCE_LINK_CREATED, EVIDENCE_SUBMITTED, EVIDENCE_APPROVED,
EVIDENCE_DISPUTED, RENEWAL_DECISION_SAVED
```

상태나 사용자 의사가 실제로 바뀌는 쓰기는 대응 이벤트와 원자적으로 기록한다. 멱등
재생처럼 상태가 바뀌지 않으면 새 이벤트를 만들지 않는다.

### 3.7 만료·재계약 의사 저장

`PUT /api/v1/contracts/{contract_id}/renewal-decision`

- 인증: Bearer
- 담당: C
- 성공: `200 RenewalDecisionResponse`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "decision": "RENEW_WITH_CHANGES",
  "confirmed": true
}
```

`decision`은 `RENEW_SAME_TERMS`, `RENEW_WITH_CHANGES`, `TERMINATE` 중 하나다.
저장은 D-30 만료, D-14 해지 통보기한, D-7 자동갱신 중 하나의 검토 구간에서만
허용한다.
같은 선택의 반복 PUT은 기존 `decided_at`과 응답을 유지하며 새 감사 이벤트를 만들지
않는다. 다른 선택으로 바꿀 때만 시각과 `RENEWAL_DECISION_SAVED` 감사 이벤트를
원자적으로 갱신한다. 서버는 선택과 `decided_at`, 감사 이벤트만 저장한다. 조건
변경이면 이전에 거절되거나
원안 유지된 `revisit_review_item_ids`를 응답하고 다른 두 선택에서는 빈 배열이다.
이 API는 계약 상태를 바꾸거나 새
계약·문서·조정·서명 요청을 자동 생성하지 않는다. 재계약 초안 복제는 P1이다.
저장된 최신 결과는 이후 계약 상세의 nullable `renewal_decision`에서도 조회한다.

## 4. 문서·사용자 이해조건·AI 분석 — B

### 4.1 계약 문서 업로드

`POST /api/v1/contracts/{contract_id}/documents`

- 인증: Bearer
- 담당: B
- Content-Type: `multipart/form-data`
- 성공: `201 DocumentResponse`
- 오류: `401`, `404`, `422`

Form:

| 필드 | 타입 | 필수 | 규칙 |
| --- | --- | --- | --- |
| `file` | binary | 예 | 문서 type별 허용 형식 검증 후 저장 |
| `type` | enum | 예 | `CONTRACT`, `PROPOSAL`, `ESTIMATE`, `MESSAGE` |

`CONTRACT`, `PROPOSAL`, `ESTIMATE`는 PDF를 받고 `MESSAGE`는 PDF·PNG·JPEG·UTF-8
text 파일을 선택 자료로 받는다. 확장자만 신뢰하지 않고 MIME, magic bytes, 빈 파일,
암호화 여부를 검사한다. P0 기본 제한은 파일당 20 MiB, PDF 100페이지이며
`DOCUMENT_MAX_SIZE_MIB`, `DOCUMENT_MAX_PDF_PAGES`로 더 낮게 조정할 수 있다.
이미지·text 메시지는
`source_page=1`인 단일 가상 페이지로 정규화한다.

응답 `Document`:

```json
{
  "id": "document_uuid",
  "contract_id": "contract_uuid",
  "type": "CONTRACT",
  "parse_status": "PENDING",
  "created_at": "2026-07-29T09:00:00Z"
}
```

영속 `file_url`과 Storage 경로는 private이며 이 응답에 포함하지 않는다.
문서 메타데이터와 `DOCUMENT_UPLOADED` 감사 이벤트를 하나의 트랜잭션으로 기록한다.

### 4.2 계약 원문 임시 접근

`GET /api/v1/contracts/{contract_id}/documents/{document_id}/access`

- 인증: Bearer
- 담당: B
- Query: 선택 `source_page`(1 이상의 정수)
- 성공: `200 DocumentAccessResponse`
- 성공 헤더: `Cache-Control: no-store`
- 오류: `401`, `404`, `422`

계약과 문서의 소유권을 확인한 뒤 최대 5분 유효한 private Storage `access_url`,
`expires_at`, 요청한 `source_page`를 반환한다. 프런트는 근거 카드에서 이 endpoint를
호출해 해당 문서 또는 가상 페이지를 연다. URL·Storage 경로를 일반 응답이나 로그에
남기지 않는다. `source_page`는 1-based이며 저장된 `Document.page_count`를 초과하면
`422 VALIDATION_ERROR`로 거부하고 접근 URL을 발급하지 않는다.

`SUPABASE_MODE=mock`에서는 같은 API 프로세스의 메모리 원문을 300초 동안 실제로 읽는
로컬 전용 URL을 발급한다. `live`에서는 Supabase private bucket의 signed URL을
발급한다. mock URL은 프로세스를 재시작하면 유효하지 않으며 실제 Supabase 연동 성공을
뜻하지 않는다.

### 4.3 사용자 이해조건 저장

`PUT /api/v1/contracts/{contract_id}/understood-terms`

- 인증: Bearer
- 담당: B
- 성공: `200 UnderstoodTermResponse`
- 오류: `401`, `404`, `422`

요청:

```json
{
  "duration_text": "1년",
  "monthly_amount": 500000,
  "total_amount": 6000000,
  "refund_text": "중도해지 시 일부 환불",
  "termination_text": "중도해지 가능",
  "source_type": "USER_MEMORY"
}
```

사용자 답변은 계약서 근거가 아니라 사용자가 기억하고 이해한 설명으로 저장한다.
요청에는 `contract_id`를 보내지 않으며 서버가 경로와 권한 컨텍스트에서 정한다.
`UnderstoodTermResponse.data`에는 서버가 정한 `contract_id`를 포함한다.
`source_type`은 `USER_MEMORY`만 허용하고 DB에도 같은 값으로 고정한다.

한 계약에는 `UnderstoodTerm` 한 행만 두며 PUT은 다섯 조건 전체를 교체한다.
`monthly_amount`, `total_amount`는 필수 필드지만 사용자가 기억하지 못하면 `null`을
허용한다. 두 금액은 사용자 답변이므로 서버가 서로 계산하거나 보정하지 않는다.
최초 저장 또는 값 변경 시 다섯 조건과 `UNDERSTOOD_TERMS_SAVED` 감사 이벤트를 하나의
트랜잭션으로 기록한다. 완전히 같은 PUT 재시도는 기존 값을 반환하고 감사 이벤트를
중복 생성하지 않는다.

### 4.4 분석 작업 시작

`POST /api/v1/contracts/{contract_id}/analysis`

- 인증: Bearer
- 담당: B
- 필수 헤더: `Idempotency-Key`
- 성공: `202 AnalysisTaskResponse`
- 오류: `401`, `404`, `409`, `422`, `503`

요청:

```json
{
  "document_id": "contract_document_uuid",
  "supporting_document_ids": [
    "proposal_document_uuid",
    "message_document_uuid"
  ]
}
```

`document_id`는 같은 계약의 최신 `CONTRACT` 문서여야 한다. 실행 중인 분석이 있으면 중복
작업을 만들지 않는다. `supporting_document_ids`는 같은 계약의 `PROPOSAL`,
`ESTIMATE`, `MESSAGE`만 허용하고 없으면 빈 배열이다. 선택 자료의 추출값은
`DOCUMENTED_EXPLANATION`으로 비교·표시할 뿐 canonical 값이나 대표 의무로 승격하지
않는다.

같은 필드의 검증된 계약 원문과 선택 자료 값은 날짜·금액·정수·enum·정규화된 TEXT로
결정 비교한다. 선택 자료끼리 값이 다르거나 어느 한쪽 근거가 미검증이면
`NEEDS_CHECK`, 계약 원문에서 근거를 찾지 못하고 선택 자료에 검증된 설명이 있으면
`NO_BASIS`로 표시하며 확정 불일치로 단정하지 않는다. 비교한 추출값 ID는 계약 원문을
먼저 두고 선택 자료 요청 순서대로 `related_extracted_term_ids`에 연결한다.

최신 작업이 `FAILED`이고 실행 중 작업이 없으면 사용자가 새 `Idempotency-Key`와 최신
계약 문서 ID로 수동 재시작할 수 있다. 계약은 `ANALYZING`을 유지하고 새 `QUEUED`
작업과 `ANALYSIS_RESTARTED` 감사 이벤트를 만든다. 기존 멱등 키 재호출은 최초 HTTP
결과(보통 `202` 접수, 접수 자체 실패 시 `503`)를 재생하고 새 작업을 만들지 않는다.
비동기 `FAILED` 상태는 조회 API에서 확인하며 자동 무한 재시도는 하지 않는다.
별도 worker는 짧은 대기 cutoff보다 오래된 `QUEUED`만 다시 처리한다. 이미 시작한
`PROCESSING`은 별도 처리 timeout(기본 14,400초)을 넘긴 경우에만 DB에서 잠그고
상태·cutoff을 재검증한 뒤 `FAILED/DOCUMENT_PARSE_FAILED`, 주 계약 문서와 선택 자료
`parse_status=FAILED`, `ANALYSIS_FAILED` 감사 이벤트를 원자적으로 기록한다.
계약은 `ANALYZING`을 유지하므로 사용자가 위 명시적 재시작 경로를 사용한다.

구현은 최초 접수에서 계약을 `ANALYZING`, 작업을 `QUEUED`로 저장하고 감사 이벤트를
같은 트랜잭션에 기록한 뒤 `202`를 반환한다. 이후 백그라운드 작업이 private Storage
원문을 읽어 Upstage Adapter의 mock/live 모드로 파싱·추출한다. live 모드는
Document Parse와 Universal Extraction의 location 메타데이터를 연결해
`source_page`, `source_text`, `confidence`를 검증한다. 1차 결과의 누락·근거 부족
필드만 한 번 재추출하며 두 번째 결과도 Pydantic AI 스키마에 맞지 않으면
`FAILED/ANALYSIS_SCHEMA_INVALID`로 종료한다.

추출·근거 검증 뒤 서버 코드가 누락, 불일치, 명시적인 불명확 표현과 책임 확인
후보를 판정한다. Solar Adapter는 후보별 최소 원문·사용자 이해조건을 받아 쉬운 설명과
원안 수용·절충·요청 문구만 생성한다. 출력 UUID, 문구, 비보정 자기평가값과 한계는
strict JSON Schema와 Pydantic으로 검증하며 Solar가 신호, 근거, 계산 결과, 상태를
변경하게 하지 않는다. Solar timeout·HTTP·스키마 오류는 고정 문구로 대체하지 않고
`FAILED/ANALYSIS_SCHEMA_INVALID`로 종료한다. Solar 호출은 추출
`attempt_count`에 포함하지 않는다.

완료 저장은 `ExtractedTerm`, `ReviewItem`, 비어 있는 Contract canonical 값,
`AnalysisTask=COMPLETED`, `Contract=REVIEW_REQUIRED`,
`ANALYSIS_COMPLETED` 이벤트를 하나의 DB 트랜잭션으로 기록한다. 기존 non-null canonical
값은 덮어쓰지 않고 최신 계약 원문과 다르면 확인용 `ReviewItem`을 남긴다.

### 4.5 최근 분석 상태·결과 조회

`GET /api/v1/contracts/{contract_id}/analysis`

- 인증: Bearer
- 담당: B
- 성공: `200 AnalysisTaskResponse`
- 반환 기준: 가장 최근에 생성된 분석 작업 한 건
- 오류: `401`, `404`, `422`

작업 상태:

| 상태 | `result` | `error_code` |
| --- | --- | --- |
| `QUEUED` | null | null |
| `PROCESSING` | null | null |
| `COMPLETED` | `Analysis` | null |
| `FAILED` | null | `DOCUMENT_PARSE_FAILED` 또는 `ANALYSIS_SCHEMA_INVALID` |

`attempt_count=0`은 아직 추출을 시작하지 않은 `QUEUED` 작업에서만 허용한다.
`PROCESSING`, `COMPLETED`, `FAILED`는 초기 추출을 포함한 1~2회다.
`FAILED`가 되면 `ANALYSIS_FAILED` 감사 이벤트를 기록하고 위 수동 재시작 경로만
허용한다.

완료 예시:

```json
{
  "data": {
    "id": "analysis_uuid",
    "contract_id": "contract_uuid",
    "document_id": "document_uuid",
    "supporting_document_ids": [],
    "status": "COMPLETED",
    "attempt_count": 1,
    "error_code": null,
    "result": {
      "contract_id": "contract_uuid",
      "document_clauses": [
        {
          "id": "clause_uuid",
          "document_id": "document_uuid",
          "ordinal": 1,
          "heading": "제1조",
          "title": "목적",
          "source_page": 1,
          "source_text": "제1조(목적) ...",
          "confidence": null
        }
      ],
      "extracted_terms": [],
      "review_items": []
    },
    "created_at": "2026-07-29T09:00:00Z",
    "updated_at": "2026-07-29T09:01:30Z"
  },
  "error": null,
  "requestId": "req_123abc"
}
```

`document_clauses`는 주 계약 문서의 비어 있지 않은 원문을 원래 순서대로 모두 담는다.
`제N조` 표제가 인식되면 조항 단위로 나누고, 표제 앞 머리말·페이지를 넘어 이어지는 문장·
표제가 없는 페이지도 별도의 원문 구간으로 남겨 누락하지 않는다. `id`는 같은 문서와 같은
원문 구간에 대해 결정적으로 생성한다. 문서 파서가 조항 단위 신뢰도를 제공하지 않으므로
현재 `confidence`는 `null`이며, 이를 임의의 AI 확신도로 대체하지 않는다. 기존에 저장된
분석 결과에는 이 필드가 없을 수 있으므로 클라이언트는 `review_items` 근거를 폴백으로 쓴다.

각 `ExtractedTerm`은 `id`, `contract_id`, `document_id`, `source_type`, `field`,
`value_type`, `value`, `source_page`, `source_text`, `confidence`,
`verification_status`를 가진다. `source_type`은 `CONTRACT_DOCUMENT` 또는
`DOCUMENTED_EXPLANATION`이다.

- 소유권: `advertising_account_ownership`, `content_ownership`
- 안전·손해: `shooting_safety`, `facility_damage_liability`
- 권리·개인정보: `portrait_rights`, `personal_information_handling`
- 갱신 방식: `contract_renewal_type` = `AUTO`, `MANUAL`, `NONE`, `UNKNOWN`

- `VERIFIED`: 값과 페이지·문장이 모두 존재
- `NOT_FOUND`: 값과 페이지·문장이 모두 `null`
- `MISSING_EVIDENCE`: 값은 있으나 페이지·문장은 모두 `null`
- `NEEDS_CHECK`: 페이지·문장이 모두 있고 사용자 확인 필요

non-null `TEXT`는 빈 문자열을 허용하지 않는다. `auto_renewal=YES`는
`contract_renewal_type=AUTO`로 정규화하지만 `NO`만으로 `MANUAL`·`NONE`을 추정하지
않는다. 갱신 방식 또는 Boolean 값이 `UNKNOWN`이면 `NEEDS_CHECK`이며 canonical 값으로
승격하지 않는다.

분석 완료 시 최신 `CONTRACT` 문서에서 나온 `VERIFIED` 단일·비모순 후보만 비어 있는
계약 canonical 체결일·기간·해지 통보기한·갱신 유형·총액에 승격한다. 기존 값은 덮어쓰지 않으며 다른 값은
검토 신호로 남긴다. 분석 결과의 첫 번째 명확한 `VERIFIED` 산출물은 근거
`source_page`, `source_text`, `confidence`를 보존한 대표 `Obligation` 한 건으로
자동 생성한다. 명확한 산출물이 없으면 임의로 생성하지 않는다. canonical 승격,
대표 의무 생성, 분석 완료와 감사 이벤트는 하나의 로컬 트랜잭션으로 기록한다.
최초 분석 접수는 `ANALYSIS_STARTED`, 완료는 `ANALYSIS_COMPLETED`, 대표 의무 생성은
`OBLIGATION_CREATED`를 기록하며 실패는 `ANALYSIS_FAILED`로 남긴다.

### 4.6 검토 항목 선택 저장

`PATCH /api/v1/contracts/{contract_id}/review-items/{item_id}`

- 인증: Bearer
- 담당: B
- 성공: `200 ReviewItemResponse`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "user_choice": "REQUEST"
}
```

`user_choice`: `ACCEPT`, `COMPROMISE`, `REQUEST`

AI 재실행은 사용자가 확정한 선택을 덮어쓰지 않는다. 선택 수정은 `UNREVIEWED`,
`SELECTED`에서만 허용한다. 조정 요청 발송으로 `SENT` 이상이 된 뒤에는 발송
스냅샷과 다르게 바꾸지 못하도록 `409 INVALID_STATUS_TRANSITION`으로 거부한다.
`ACCEPT`는 원안 수용으로 즉시 `RESOLVED`, `COMPROMISE`·`REQUEST`는 `SELECTED`로
저장하며 조정 초안에는 `SELECTED`인 절충안·요청안만 포함한다. `/send`가 성공하면
포함 항목을 `SENT`로 동결한다.
선택과 `REVIEW_ITEM_SELECTION_UPDATED` 감사 이벤트는 하나의 트랜잭션으로 기록한다.
`ReviewItem.source_document_id`, `source_page`, `source_text`, `source_confidence`는
항상 함께 존재하거나 함께 `null`이다. `VERIFIED`·`NEEDS_CHECK`에서는 네 필드가 모두
필요하고 `NOT_FOUND`·`MISSING_EVIDENCE`에서는 모두 `null`이다.
`related_extracted_term_ids`로 계약 원문과 선택 자료의 비교 근거를 연결하며
`source_document_id`와 `source_confidence`는 그중 기본 원문 근거
`ExtractedTerm.document_id`와 `ExtractedTerm.confidence`에서 가져온다.
`basis_type`은 `OFFICIAL_SOURCE` 또는 `INTERNAL_RULE`이며 비어 있지 않은
`basis_text`를 원문·사용자 이해·제안 문구와 분리해 반환한다. 공식 기준의
`basis_citation`은 기관·문서명과 nullable URL·버전·시행일을 포함하고 내부 규칙이면
`basis_citation=null`이다.
`source_confidence`는 원문 추출 근거의 확신도다. `MODEL`·`HYBRID` 항목은 이와 별도로
검토 판단의 `model_confidence`와 비어 있지 않은
`model_limitations`를 함께 반환하고, `DETERMINISTIC` 항목에서는 두 필드가 모두
`null`이다.
현재 결정 규칙이 신호를 판정하고 Solar가 설명·3종 문구를 생성한 결과는
`detection_method=HYBRID`다. Solar Chat이 별도의 보정 confidence를 제공하지 않으므로
`model_confidence`는 문구가 입력 범위를 반영했다는 모델의 비보정 자기평가값이며,
법적 판단 정확도나 원문 추출의 `source_confidence`로 해석하지 않는다. 이 한계는
`model_limitations`에도 포함한다.
`UNREVIEWED`의 `user_choice`는 `null`이고 이후 상태에서는 저장된 선택을 반환한다.

## 5. 조정 요청·대행사 응답 — C

### 5.0 조정 요청 문구 다듬기

`POST /api/v1/contracts/{contract_id}/adjustment-copy/polish`

- 인증: Bearer
- 담당: B
- 성공: `200 AdjustmentCopyPolishResponse`
- 모든 응답: `Cache-Control: no-store`
- 오류: `401`, `404`, `422`, `502`
- 입력: 사용자가 직접 작성한 `text` 1~1200자
- 출력: Solar strict JSON Schema를 통과한 `polished_text` 1~1200자

서버는 계약 소유권을 AI 호출 전에 확인한다. 입력 문구를 신뢰할 수 없는
데이터로 취급하고, 입력에 없는 사실·금액·날짜·기간·비율·법적 결론을
추가하지 않도록 제한한다. 입력과 출력의 숫자 토큰 multiset이 정확히 같지
않거나 금지된 단정 표현이 있으면 결과를 폐기하고 `502 ANALYSIS_SCHEMA_INVALID`를
반환한다. mock 모드는 입력을 직접 반영하는 규칙 기반 예시이며 live Solar 성공으로
간주하지 않는다. 입력·출력은 영속화하지 않고 로그에도 남기지 않으며 응답은
캐시하지 않는다.

이 API는 문구 후보만 반환한다. 사용자가 미리보기의 **이 문구로 적용**을 누르기
전에는 초안을 변경하지 않고, 적용 후에도 조정 링크를 자동 생성·전송하지 않는다.

### 5.1 조정 요청 초안 생성

`POST /api/v1/contracts/{contract_id}/adjustment-requests`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 성공: `201 AdjustmentRequestResponse`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "review_item_ids": [
    "review_item_uuid_1",
    "review_item_uuid_2"
  ],
  "request_text_overrides": {
    "review_item_uuid_1": "계약기간을 1년으로 조정해 주시기를 요청드립니다."
  },
  "manual_items": [
    {
      "document_clause_id": "document_clause_uuid_1",
      "request_text": "결과물 승인 기한을 5영업일로 명확히 적어 주세요."
    }
  ],
  "expires_in_hours": 72
}
```

- `review_item_ids`와 `manual_items`를 합해 중복 없이 한 개 이상이며 개수 상한을 두지 않는다.
- `review_item_ids`는 `SELECTED` 상태인 `COMPROMISE`·`REQUEST`만 허용한다.
  원안 수용인 `ACCEPT` 항목은 발송하지 않는다.
- `request_text_overrides`는 선택 사항이며 키는 `review_item_ids`의 부분집합이어야 한다.
  값은 사용자가 미리보기에서 직접 확인·수정한 1~1200자 문구로, 초안에 그대로 저장한다.
- `manual_items`는 최신 완료 분석의 `document_clauses`에 실제로 존재하는 조항 ID와
  1~1200자 요청 문구만 받는다. 제목·원문·페이지는 요청에서 받지 않고 서버의 분석
  결과에서 다시 연결한다. 서버는 이를 `USER_SELECTED` 출처의 내부 조정 항목으로
  저장하며, 원문 근거와 AI 검토 결과를 혼동하지 않는다.
- 응답 `items`에는 `review_item_id`, `user_choice`, 실제 `request_text`가 들어간다.
- 초안에는 `public_url`이 없으며 사용자가 발송 전 문구를 확인한다.
- `expires_in_hours`는 유효기간 정책값이다. `DRAFT`의 `sent_at`, `expires_at`,
  `opened_at`, `responded_at`은 모두 `null`이다.
- 초안과 `ADJUSTMENT_DRAFT_CREATED` 감사 이벤트를 하나의 트랜잭션으로 기록한다.

### 5.2 소유자용 조정 상세 조회

`GET /api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}`

- 인증: Bearer
- 담당: C
- 성공: `200 OwnerAdjustmentDetailResponse`
- 오류: `401`, `404`, `422`

응답:

- `request`: 실제 요청 문구와 상태
- `responses`: 대행사의 수락·거절·역제안
- `comparisons`: 역제안 변화 요약과 남은 확인사항

endpoint와 저장 책임은 C가 맡고, B의 `CounterproposalComparator`를 호출한다.
수락·거절은 서버 코드가 결정적으로 설명하고, 역제안은 저장된 실제 요청 문구,
대행사의 `counter_text`와 `reason`만 Solar에 전달해 원 요청에서 달라진 부분,
유지된 위험·확인 항목과 최종 확인 내용을 생성한다. 출력은
`counterproposal-comparison-v1` strict JSON Schema와 Pydantic으로 검증한다.
Solar 요청 실패, 출력 ID 불일치, 금지된 단정 표현 또는 입력에 없는 숫자가 있으면
`502 ANALYSIS_SCHEMA_INVALID`를 반환하되 이미 저장된 대행사 응답은 유지한다.

### 5.3 조정 링크 활성화

`POST /api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}/send`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 성공: `200 AdjustmentRequestSentResponse`
- 모든 응답: `Cache-Control: no-store`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "confirmed": true
}
```

응답:

```json
{
  "data": {
    "id": "adjustment_request_uuid",
    "status": "SENT",
    "public_url": "https://example.com/r/raw-token",
    "expires_at": "2026-08-01T09:00:00Z"
  },
  "error": null,
  "requestId": "req_123abc"
}
```

`public_url`은 이 생성 응답에서만 반환하고 일반 조회에서는 다시 노출하지 않는다.
같은 멱등 키로 재시도해 최초 생성 응답을 재생하는 경우만 같은 생성 요청으로 취급한다.
성공 시 `sent_at`을 기록하고 `expires_at = sent_at + expires_in_hours`로 계산한다.
P0에서는 계약당 실제 발송·응답 라운드를 한 번만 허용한다. 이미 발송 이력이 있으면
다른 초안의 `/send`를 `409 INVALID_STATUS_TRANSITION`으로 거부하며 자동 재요청·반복
협상은 만들지 않는다. 성공 시 포함된 `ReviewItem`을 `SENT`로 동결하고
`ADJUSTMENT_SENT` 감사 이벤트를 같은 트랜잭션에 기록한다.

### 5.4 대행사용 공개 조정 요청 조회

`GET /api/v1/public/adjustment-requests/{token}`

- 인증: Bearer 없음, 조정 scope 공개 토큰 사용
- 담당: C
- 성공: `200 PublicAdjustmentResponse`
- 모든 응답: `Cache-Control: no-store`
- 오류: `404`, `410`

내부 `review_item_id` 대신 토큰 범위에서만 유효한 `item_id`를 반환한다.
각 항목의 `before_text`에는 조정 요청과 직접 관련된 원계약 문구만 반환한다. 원본 파일
URL·Storage 경로·계약 전문은 공개하지 않는다. `source_page`에는 해당 문구가 확인된
원계약의 1-based 페이지를 반환하며, 실제 원문 근거가 없으면 두 필드를 `null`로 반환한다.
이 조회는 상태를 바꾸지 않는다. 성공 응답의 `status`는 `SENT`, `OPENED`,
`RESPONDED`, `CONFIRMED` 중 하나이며, `DRAFT`에는 공개 토큰이 없고 만료 상태는
`410`으로 반환한다.

### 5.5 대행사 최초 열람 기록

`POST /api/v1/public/adjustment-requests/{token}/open`

- 인증: Bearer 없음, 조정 scope 공개 토큰 사용
- 담당: C
- 요청 body: 없음
- 성공: `200 PublicAdjustmentOpenResponse`
- 모든 응답: `Cache-Control: no-store`
- 오류: `404`, `410`

공개 화면이 실제로 렌더링된 뒤 호출한다. 최초 호출은 `SENT → OPENED`와
`opened_at`, `ADJUSTMENT_OPENED` 감사 이벤트를 원자적으로 기록한다. 반복 호출 또는
응답 이후 호출은 최초 `opened_at`을 바꾸지 않고 같은 열람 결과를 반환하며 새 이벤트를
만들지 않는다.

### 5.6 대행사 1회 응답 제출

`POST /api/v1/public/adjustment-requests/{token}/responses`

- 인증: 조정 scope 공개 토큰
- 담당: C
- 성공: `201 PublicSubmissionResponse`
- 모든 응답: `Cache-Control: no-store`
- 오류: `404`, `409`, `410`, `422`

요청 예시:

```json
{
  "responses": [
    {
      "item_id": "opaque_item_1",
      "decision": "ACCEPT",
      "counter_text": null,
      "reason": null
    },
    {
      "item_id": "opaque_item_2",
      "decision": "COUNTER",
      "counter_text": "계약기간을 2년으로 조정하겠습니다.",
      "reason": "촬영과 게시 일정 확보가 필요합니다."
    }
  ]
}
```

규칙:

- `decision`: `ACCEPT`, `REJECT`, `COUNTER`
- `ACCEPT`: `counter_text`, `reason` 모두 `null`
- `REJECT`: `counter_text=null`, 비어 있지 않은 `reason` 필수
- `COUNTER`: 비어 있지 않은 `counter_text`, `reason` 필수
- 공개 요청의 모든 항목을 정확히 한 번씩 제출
- 전체 응답은 한 번만 원자적으로 확정
- `/open` 기록 없이 `SENT`에서 직접 제출하면 `opened_at=responded_at`을 함께 기록
- 응답과 `ADJUSTMENT_RESPONDED` 감사 이벤트를 하나의 트랜잭션으로 기록

### 5.7 최종 조정 결과 확정

`POST /api/v1/contracts/{contract_id}/adjustment-confirmation`

- 인증: Bearer
- 담당: C
- 성공: `200 AdjustmentRequestResponse`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "adjustment_request_id": "adjustment_request_uuid",
  "confirmed_items": [
    {
      "review_item_id": "review_item_uuid_1",
      "resolution": "ACCEPT_REQUEST"
    },
    {
      "review_item_id": "review_item_uuid_2",
      "resolution": "ACCEPT_COUNTERPROPOSAL"
    }
  ],
  "confirmed": true
}
```

`resolution`:

- `ACCEPT_REQUEST`
- `ACCEPT_COUNTERPROPOSAL`
- `KEEP_ORIGINAL`

클라이언트는 최종 문구를 직접 보내지 않는다. 서버가 저장된 요청·응답에서 최종 문구를
결정한다. `ACCEPT_REQUEST`와 `ACCEPT_COUNTERPROPOSAL`은 관련 `ReviewItem`을
`SENT → RESOLVED`, `KEEP_ORIGINAL`은 `SENT → KEPT_ORIGINAL`로 바꾼다.
조정·계약 상태, 항목 상태, 최종 문구와 `ADJUSTMENT_CONFIRMED` 감사 이벤트를 하나의
트랜잭션으로 기록한다.

## 6. 수정 계약서 대조·모두싸인 — C

### 6.1 수정 계약서 대조 생성

`POST /api/v1/contracts/{contract_id}/revised-contract-reviews`

- 인증: Bearer
- 요청: 확정된 `adjustment_request_id`, 최신 `REVISED_CONTRACT` `document_id`
- 성공: `201 RevisedContractReviewResponse`
- 오류: `401`, `404`, `409`, `422`

확정 문구를 수정 계약서 각 페이지에서 정규화해 정확히 찾은 경우만 `MATCHED`로 표시하고
`source_page`, `source_text`, 결정적 `confidence=1.0`을 보존한다. 찾지 못하거나 표현이
다르면 `NEEDS_CONFIRMATION`이며 자동으로 합의 반영을 확정하지 않는다.

### 6.2 최신 대조 조회·최종 확인

- `GET /api/v1/contracts/{contract_id}/revised-contract-reviews/latest`
- `POST /api/v1/contracts/{contract_id}/revised-contract-reviews/{review_id}/confirmation`

최종 확인 요청은 최신 검토의 모든 `review_item_id`를 정확히 한 번씩 포함하고
`confirmed=true`여야 한다. 성공하면 검토와 모든 항목을 확정하고 Contract를
`NEGOTIATING → READY_TO_SIGN`으로 바꾼다. 이전 검토와 수정본은 삭제하지 않는다.

기존 `/agreement` 생성·조회 API와 관련 테이블은 이전 데이터 호환을 위한 deprecated
경로이며 새 P0 정상 흐름에서는 호출하지 않는다.

### 6.3 모두싸인 임베디드 서명 초안 생성

`POST /api/v1/contracts/{contract_id}/signature-embedded-drafts`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 성공: `201 EmbeddedSignatureDraftResponse`
- 성공 응답 헤더: `Cache-Control: no-store`
- 오류: `401`, `404`, `409`, `422`, `502`

> **C-7 변경(2026-07-31):** 기존
> `POST /contracts/{contract_id}/signature-requests` 템플릿 기반 즉시 발송 API를
> 임베디드 초안 생성 API로 대체했다. 이 API는 서명 요청을 발송하지 않으며, 사용자가
> 반환된 모두싸인 편집 화면에서 서명란을 배치하고 직접 발송한다.

요청:

```json
{
  "revised_contract_review_id": "revision_review_uuid",
  "signers": [
    {
      "role": "OWNER",
      "name": "김소상",
      "signing_method": {
        "type": "EMAIL",
        "value": "owner@example.com"
      }
    },
    {
      "role": "AGENCY",
      "name": "박대행",
      "signing_method": {
        "type": "KAKAO",
        "value": "01012345678"
      }
    }
  ],
  "confirmed": true
}
```

규칙:

- `OWNER`와 `AGENCY` 각각 정확히 한 명
- 이름 2~30자
- `EMAIL`은 email 형식
- `KAKAO`는 하이픈 없는 국내 휴대전화 번호
- 역할과 연락처 중복 금지
- 연락처 원문을 모두싸인 Adapter에만 전달하고 API 응답·DB·로그에 저장하지 않음
- 서버가 최신 확정 대조의 수정 계약서 PDF를 읽어 SHA-256 무결성을 검증한 뒤
  모두싸인 `POST /embedded-drafts`에 Base64 PDF로 전달. PDF를 다시 렌더링하지 않음
- `Signature=REQUESTING → EDITING`, `modusign_status=DRAFT`,
  `modusign_draft_id`와 `SIGNATURE_DRAFT_CREATED` 감사 이벤트를 저장
- 이 단계에서는 Contract를 `READY_TO_SIGN`으로 유지하며 자동 발송하지 않음
- `editor_url`과 `expires_at`은 생성 응답에서만 반환하고 DB·로그·멱등 재생값에
  저장하지 않음
- 같은 `Idempotency-Key` 재호출은 민감 URL을 재발급·재생하지 않고 `409` 반환

응답 예시:

```json
{
  "data": {
    "signature": {
      "id": "signature_uuid",
      "contract_id": "contract_uuid",
      "status": "EDITING",
      "modusign_status": "DRAFT",
      "modusign_draft_id": "modusign_draft_id",
      "modusign_document_id": null,
      "last_event_id": null,
      "requested_at": "2026-07-31T06:00:00Z",
      "completed_at": null
    },
    "editor_url": "https://app.modusign.co.kr/embedded-draft/...",
    "expires_at": "2026-07-31T08:00:00Z"
  },
  "error": null,
  "requestId": "req_123abc"
}
```

PDF 생성 또는 외부 초안 생성 실패는 `502`를 반환하고 `Signature=FAILED`를 보존하되
Contract는 `READY_TO_SIGN`을 유지한다. 실패·중단 뒤 자동 재요청하지 않으며 사용자가
현재 수정 계약서를 다시 확인하고 새 `Idempotency-Key`와 `confirmed=true`로 요청해야 한다.

### 6.4 서명 상태 조회

`GET /api/v1/contracts/{contract_id}/signature`

- 인증: Bearer
- 담당: C
- 성공: `200 SignatureResponse`
- 오류: `401`, `404`, `422`

여러 시도가 있으면 가장 최근에 생성된 `Signature` 한 건을 반환하며 이전 terminal
시도와 외부 문서 ID는 감사 이력으로 보존한다.

내부 상태:

`REQUEST_READY`, `REQUESTING`, `EDITING`, `SIGNING`, `COMPLETED`, `ABORTED`, `FAILED`

모두싸인 원본 상태:

`DRAFT`, `SCHEDULED`, `ON_PROCESSING`, `ON_GOING`, `COMPLETED`, `ABORTED`,
`PROCESSING_FAILED`

두 상태는 별도 필드로 저장한다. 임베디드 초안 생성 직후는 원본 `DRAFT`이고 사용자가
편집 화면에서 직접 발송한 뒤 `ON_PROCESSING → ON_GOING → COMPLETED / ABORTED /
PROCESSING_FAILED`로 진행한다.
내부 `Signature`는 `id`와 마지막으로 반영한 `last_event_id`를 보존한다.
`modusign_draft_id`, `modusign_document_id`, `last_event_id`, `requested_at`,
`completed_at`은 값이 없더라도 응답 필드를 생략하지 않고 `null`로 반환한다.
`EDITING`은 원본 `DRAFT`, `modusign_draft_id`, 요청 시각이 필요하고
`modusign_document_id`, `last_event_id`, `completed_at`은 `null`이다.
`SIGNING`은 원본 `ON_GOING`, 외부 문서 ID, 마지막 이벤트, 요청 시각이 필요하고
`completed_at=null`이다. `COMPLETED`는 원본 `COMPLETED`와 외부 문서 ID, 마지막
이벤트, 요청·완료 시각을 모두 보존한다. `ABORTED`도 원본 `ABORTED`와 같은 추적
필드를 보존한다.
`REQUESTING`은 초안 생성 호출 중인 내부 상태이므로 원본 상태·초안 ID·문서 ID·
이벤트 ID가 모두 `null`이다. `SIGNING`·terminal 상태부터 마지막 이벤트 ID 또는
fingerprint가 필수다.
`FAILED`는 외부 생성 전 로컬 실패의 외부 상태·초안 ID·문서 ID·이벤트 ID가 모두
`null`인 경우 또는 원본
`PROCESSING_FAILED`와 문서·이벤트 ID가 모두 있는 외부 실패만 허용하고, 두 경우 모두
요청·완료 시각을 보존한다.

### 6.5 모두싸인 웹훅

`POST /api/v1/webhooks/modusign`

- 인증: `X-Modusign-Webhook-Secret`
- 담당: C
- 성공: `204 No Content`
- 오류: `401`, `422`

P0 구독 이벤트:

- `document_started`
- `document_signed`
- `document_all_signed`
- `document_rejected`
- `document_request_canceled`
- `document_signing_canceled`

인증 후 이벤트를 멱등 저장하고 즉시 `204`를 반환한다. 문서 상태 조회와 내부 계약 상태
전이는 응답 이후 비동기로 처리한다. 실제 payload에서 안정적인 이벤트 ID를 Adapter가
검증하면 사용하고, 없으면 `event.type + document.id + canonical payload hash`를
fingerprint로 사용한다. `requester.email`은 인증에 사용하지 않는다.
기획안의 `WEBHOOK_DUPLICATED`는 공개 `ApiError.code`가 아닌 내부 관측·테스트
분류로 남기며, 이 vendor endpoint의 오류 body로 반환하지 않고 동일하게 `204`로
승인한다.

사용자가 임베디드 편집기에서 발송한 뒤 인증된 최신 원본이 `ON_GOING`이면
`modusign_draft_id`와 외부 문서 ID를 연결하고 Contract를
`READY_TO_SIGN → SIGNING`으로 전환한다. 최신 조회 원본이 `COMPLETED`이면 계약을
`SIGNING → SIGNED`로 전환한다. `ABORTED`
또는 `PROCESSING_FAILED`이면 terminal Signature와 대응 감사 이벤트를 보존하고 계약을
`SIGNING → READY_TO_SIGN`으로 되돌린다. 종료 상태 뒤의 오래된 이벤트는 상태를
되돌리지 않으며 실패·중단 뒤 서명을 자동 재요청하지 않는다.

초안 생성 시에는 내부 Signature ID와 서버 secret으로 만든 HMAC 증명 metadata를 모두싸인
문서에 함께 넣는다. 웹훅 payload의 문서 ID만으로 내부 시도를 추측하지 않고, 최신 문서
조회에서 이 metadata를 검증한 경우에만 연결한다. `COMPLETED`가 `ON_GOING`보다 먼저
처리되면 최신 원본 상태를 우선하여 `EDITING/READY_TO_SIGN → COMPLETED/SIGNED`를 같은
트랜잭션으로 보정한다.

## 7. 이행 항목·증빙 — B

### 7.1 이행 항목 목록

`GET /api/v1/contracts/{contract_id}/obligations`

- 인증: Bearer
- 담당: B
- 성공: `200 ObligationListResponse`
- 정렬: `due_date`, `id` 오름차순
- 오류: `401`, `404`, `422`

P0에서는 계약당 대표 이행 항목을 최대 한 건만 반환하므로 `data`는 빈 배열 또는 원소
한 개의 배열이다.

### 7.2 대표 산출물 자동 생성 규칙

별도의 수동 생성 API는 없다. 분석이 완료되면 제목 구성 필드와
`deliverable_due_date`가 같은 원문 근거에서 명확한 첫 번째 `VERIFIED` 산출물을
계약당 대표 `Obligation` 한 건으로 자동 생성한다. 같은 분석의 재처리·동시 실행에도
한 건만 남도록 트랜잭션과 유일성 제약을 사용한다.

- 제목과 due date는 계약 근거를 사용하며 둘 중 하나라도 불명확하면 의무를 만들지 않고
  확인 신호를 유지한다.
- `assignee=AGENCY`, `evidence_type=URL`로 고정한다.
- `source_document_id`에는 대표 근거 `ExtractedTerm.document_id`를 기록하고 같은
  추출값의 `source_page`, `source_text`로 원문 클릭 근거를 보존한다.
- 제목은 같은 근거의 검증된 채널·유형·수량을 결정적 코드로 조합하고 `confidence`는
  사용한 `VERIFIED ExtractedTerm.confidence`의 최솟값으로 기록한다.
- 명확한 산출물이 없으면 임의로 만들지 않고 확인 신호를 유지한다.
- 초기 상태는 `PENDING`, `evidence_url`, 제출·검토 시각은 `null`이다.

### 7.3 증빙 제출 링크 생성

`POST /api/v1/contracts/{contract_id}/obligations/{obligation_id}/evidence-link`

- 인증: Bearer
- 담당: B
- 필수 헤더: `Idempotency-Key`
- 성공: `201 PublicLinkResponse`
- 모든 응답: `Cache-Control: no-store`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "expires_in_hours": 72
}
```

응답의 `scope`는 `OBLIGATION_EVIDENCE`로 고정한다.
계약 상태가 `SIGNED` 또는 `IN_PROGRESS`이고 대표 이행 항목이 `PENDING`일 때만 링크를
생성한다. 링크 생성 자체는 계약을 `SIGNED → IN_PROGRESS`로 자동 전환하지 않는다.
`expires_at`은 최초 성공 시각에 `expires_in_hours`를 더해 계산한다. 같은 멱등
요청은 최초 `public_url`과 `expires_at`을 그대로 재생한다. 최초 생성 시
멱등 예약·공개 토큰·안전한 재생값과 `EVIDENCE_LINK_CREATED` 감사 이벤트를 같은
트랜잭션에 기록한다. DB 커밋 뒤 응답이 유실되어도 같은 키 재시도에서 최초 링크를
재생하며 토큰과 감사 이벤트를 중복 생성하지 않는다.

### 7.4 대행사 증빙 URL 제출

`POST /api/v1/public/obligations/{token}/evidence`

- 인증: 증빙 scope 공개 토큰
- 담당: B
- 성공: `200 PublicSubmissionResponse`
- 모든 응답: `Cache-Control: no-store`
- 오류: `404`, `409`, `410`, `422`

요청:

```json
{
  "evidence_url": "https://www.instagram.com/p/example"
}
```

URL은 `http://` 또는 `https://`, 최대 2,048자만 허용한다. 서버는 URL을 가져오거나
실재 여부를 판정하지 않는다. 최초 제출은 상태와 `EVIDENCE_SUBMITTED` 감사 이벤트를
하나의 트랜잭션으로 기록한다.

### 7.5 증빙 승인·이의 처리

`PATCH /api/v1/contracts/{contract_id}/obligations/{obligation_id}`

- 인증: Bearer
- 담당: B
- 성공: `200 ObligationResponse`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "decision": "APPROVED"
}
```

`decision`: `APPROVED`, `DISPUTED`

상태는 `PENDING → SUBMITTED → APPROVED / DISPUTED`다.
`payment_condition_met=true`는 `APPROVED`일 때만 표시하며 실제 지급 승인이 아니다.
승인은 `EVIDENCE_APPROVED`, 이의 제기는 `EVIDENCE_DISPUTED` 감사 이벤트를 상태와
같은 트랜잭션에 기록한다.

## 8. 대시보드 — C

### 8.1 대시보드 조회

`GET /api/v1/dashboard`

- 인증: Bearer
- 담당: C
- 성공: `200 DashboardResponse`
- 오류: `401`

응답 집계:

| 필드 | 의미 |
| --- | --- |
| `total` | 전체 계약 수 |
| `signing` | `SIGNING` 계약 수 |
| `in_progress` | 이행 중 계약 수 |
| `completed` | `COMPLETED` 계약 수 |
| `expiring_soon` | 만료 임박 계약 수 |
| `unresolved_signals` | `UNREVIEWED`·`SELECTED`·`SENT` 검토 신호 수 |
| `adjustment_requested_clauses` | DRAFT를 제외한 발송 조정 항목 수 |
| `adjustment_agreed_clauses` | 요청안 또는 역제안으로 최종 합의된 항목 수 |
| `adjustment_rejected_clauses` | 대행사 거절 또는 최종 원안 유지 distinct 항목 수 |
| `obligation_pending` | 증빙 대기 수 |
| `obligation_submitted` | 증빙 제출 수 |
| `obligation_approved` | 승인된 증빙 수 |
| `total_committed` | `SIGNED`·`IN_PROGRESS`·`RENEWAL_DUE`·`COMPLETED` 계약의 canonical 총액 합계 |
| `payment_condition_met_amount` | 대표 의무가 `APPROVED`인 계약의 canonical 총액 합계 |
| `most_common_signal` | 같은 미해결 집합의 `ReviewItem.type` 최빈값 또는 null |

`in_progress`에는 `IN_PROGRESS`, `RENEWAL_DUE`를 포함한다. `expiring_soon`은
`0 ≤ expiry_d_day ≤ 30`, `0 ≤ termination_notice_d_day ≤ 14`,
`0 ≤ auto_renewal_d_day ≤ 7` 중 하나 이상인 계약을 중복 없이 센다.
`payment_condition_met_amount`는 대표 의무 승인 시 계약 총액을 계약당
한 번만 세는 P0 지표이며 실제 지급액·지급 승인·법적 채권액이 아니다.

## 9. 상태 머신

### 9.1 계약

`DRAFT → ANALYZING → REVIEW_REQUIRED → NEGOTIATING → READY_TO_SIGN → SIGNING → SIGNED → IN_PROGRESS → COMPLETED / RENEWAL_DUE`

기획안이 확정하지 않은 `SIGNED → IN_PROGRESS → COMPLETED / RENEWAL_DUE`의 정확한
날짜·이행 조건은 구현 전에 결정적 규칙으로 확정한다. 그 전에는 자동 완료·자동
재계약 전이를 임의로 추가하지 않는다.

### 9.2 조정 요청

`DRAFT → SENT → OPENED → RESPONDED → CONFIRMED / EXPIRED`

### 9.3 분석 작업

`QUEUED → PROCESSING → COMPLETED / FAILED`

### 9.4 이행 항목

`PENDING → SUBMITTED → APPROVED / DISPUTED`

### 9.5 내부 서명과 모두싸인 원본

- 내부:
  `REQUEST_READY → REQUESTING → EDITING → SIGNING → COMPLETED / ABORTED / FAILED`
  (`COMPLETED` 최신 상태가 먼저 도착하면 `EDITING → COMPLETED` 보정 허용)
- 원본 enum: `DRAFT`, `SCHEDULED`, `ON_PROCESSING`, `ON_GOING`, `COMPLETED`,
  `ABORTED`, `PROCESSING_FAILED`
- 정상 원본 흐름:
  `DRAFT → ON_PROCESSING → ON_GOING → COMPLETED / ABORTED / PROCESSING_FAILED`
- 초안 생성 동안 Contract는 `READY_TO_SIGN`을 유지한다. 인증된 최신 `ON_GOING`은
  Contract `READY_TO_SIGN → SIGNING`, 최신 `COMPLETED`는 `SIGNING → SIGNED`,
  단 `ON_GOING`보다 먼저 처리된 `COMPLETED`는 `READY_TO_SIGN → SIGNED` 보정,
  최신 `ABORTED`·`PROCESSING_FAILED`는 `SIGNING → READY_TO_SIGN`이다.
  실패·중단 후 재요청은 새 멱등 키를 사용한 사용자의 명시적 확인에서만 허용한다.

### 9.6 재계약 의사

D-30·D-14·D-7 신호는 날짜 계산 결과다. 사용자의 명시적 재계약 의사 저장은 계약
상태 머신과 별도이며 선택만으로 상태·계약·문서·조정·서명을 자동 생성하거나 변경하지
않는다.

상태를 router, repository, Adapter 또는 웹훅에서 직접 대입하지 않는다. domain/service의
전이 함수가 검증하고 상태 변경과 `AuditEvent`를 하나의 트랜잭션으로 기록한다.

## 10. B 개발 순서

B는 C의 전체 기능이 완성될 때까지 기다리지 않고 공통 FastAPI 기반과
`StoragePort`·repository를 먼저 제공한다. 계약 상태 변경은 C가 정의한 상태 서비스의
fake를 사용해 독립 개발하고, 실제 연결에서도 그 전이 규칙을 우회하지 않는다.

| 순서 | 구현 내용 | 연결 API·완료 조건 |
| --- | --- | --- |
| B-1 | FastAPI 공통 골격, 설정, request ID, 오류 envelope, 인증 컨텍스트 | `GET /health`, `/docs` 정상 |
| B-2 | Supabase DB·Storage Adapter, repository, 감사 트랜잭션, 마이그레이션 골격 | B·C가 같은 repository와 private 원문 접근 사용 |
| B-3 | `ExtractedTerm`, `ReviewItem`, `AnalysisTask` Pydantic 스키마와 평가 fixture 작성 | 잘못된 타입·근거 누락이 검증에서 거부됨 |
| B-4 | Upstage `mock/live` Adapter와 Document Parse 정규화 | 샘플 PDF의 페이지·문장이 내부 형식으로 변환됨 |
| B-5 | 문서 검증·업로드·원문 접근 흐름 | `POST /documents`, `GET /documents/{document_id}/access`; StoragePort fake로 테스트 통과 |
| B-6 | 사용자 이해조건 5문항 저장 | `PUT /understood-terms`; 계약 근거와 별도 저장 |
| B-7 | Information Extract와 결정적 값 정규화 | 체결일·산출물 기한·KRW·비율·Boolean 및 자료별 source_type 검증 |
| B-8 | 분석 작업 생성·상태 조회 | `POST/GET /analysis`; 진행·완료·실패 상태 확인 |
| B-9 | 기간·총액·해지·환불 불일치와 누락 검출 | 대표 문제 4종 테스트 통과 |
| B-10 | Solar 쉬운 설명과 수용·절충·요청 3종 문구 | 모든 문구가 원문 근거와 연결됨 |
| B-11 | 최대 2회의 Evaluator Loop | 필요한 필드만 한 번 재추출하고 종료 |
| B-12 | 사용자 검토 선택 저장 | `PATCH /review-items/{item_id}`; AI 재실행 덮어쓰기 방지 |
| B-13 | 역제안 비교 내부 서비스 | C가 `CounterproposalComparator`를 fake 없이 호출 가능 |
| B-14 | 분석 완료의 대표 산출물 자동 생성 | 같은 계약 문서 근거가 있을 때 계약당 1건, 재처리 중복 방지 |
| B-15 | 이행 목록·증빙 링크·공개 제출·검토 | 별도 scope, 최초 TTL, HTTP(S) URL, 승인·이의 API 테스트 통과 |
| B-16 | 고정 계약 10건 평가와 live 분리 테스트 | 일반 `pytest`가 외부 네트워크 없이 통과 |

## 11. C 개발 순서와 D 검증 역할

C는 B의 분석 결과가 완성될 때까지 기다리지 않고 고정 `ReviewItem` fixture와 가짜
역제안 비교 서비스를 사용한다. B가 제공한 공통 repository를 사용하되 계약·조정·서명
상태 규칙은 C가 정의한다.

| 순서 | 구현 내용 | 연결 API·완료 조건 |
| --- | --- | --- |
| C-1 | 계약·조정·서명 상태 규칙 | 잘못된 전이는 `409`, B의 repository에서 감사 이벤트와 원자 기록 |
| C-2 | 계약 생성·목록·상세·초기 삭제·타임라인·갱신 의사 | 계약 API 6개, 보호 경계·무부작용 갱신 저장·정렬 테스트 통과 |
| C-3 | 공개 토큰·멱등 키 기반 | B의 공통 저장 기반으로 hash·scope·만료·동일 요청 재생 테스트 통과 |
| C-4 | 조정 초안·상세·발송 | B의 ReviewItem fixture로 미리보기와 계약당 1회 `/send` |
| C-5 | 대행사 공개 조회·열람 기록·1회 응답 | GET 무변경, `/open` 최초 시각 유지, 전체 항목 정확히 한 번 제출 |
| C-6 | 최종 확정·수정 계약서 대조·확인 | 임의 최종 문구 거부, 원문 근거 보존, 최신 PDF ID·SHA-256, 확정 조항 전체 대조 |
| C-7 | 모두싸인 `mock/live` Adapter와 임베디드 초안 | C-6 저장 PDF 무결성 검증, 서명자 2명, `EDITING`, 민감 URL 비저장 검증 |
| C-8 | 웹훅 인증·중복·순서 역전 처리 | 즉시 204, 종료 상태 회귀 방지 |
| C-9 | D-day·갱신 날짜 계산 | 한국 날짜 경계와 D-30·D-14·D-7 테스트 통과 |
| C-10 | 대시보드 집계 | 상태 집합·distinct·D-day·금액 집계 테스트 통과 |

D는 endpoint, service, repository, Adapter 또는 migration을 직접 구현하지 않는다.
배포·환경변수 체크리스트 확인, 전체 P0 E2E 실행, 데모 데이터와 `AI_USAGE`·테스트
증빙 정리, 발견 이슈의 재현 절차 제공을 맡는다. 백엔드 수정이 필요하면 담당 B 또는 C가
코드와 테스트를 함께 변경한다.

## 12. B·C·D 교차 의존성

| 제공자 | 제공 내용 | 소비자 |
| --- | --- | --- |
| B | 소유자 권한·StoragePort·repository·감사 트랜잭션 | B 문서·이행 API, C 상태 서비스 |
| C | 계약 상태 전이 규칙 | B 분석 시작·완료·실패·대표 의무, 공통 repository |
| B | 완료된 `ReviewItem`과 실제 3종 문구 | C 조정 초안, B 대표 의무 |
| B | `CounterproposalComparator` | C 소유자 조정 상세 |
| B | 검증된 추출 날짜·금액·산출물 후보 | C 계약 canonical 값·대시보드, B 대표 의무 |
| C | 대행사 응답 원본 | B 역제안 비교 |
| C | 계약·서명·갱신 상태 | B 이행 API, C 대시보드 |
| D | 배포본 E2E 결과·재현 절차·데모 검증 증빙 | B·C 수정과 완료 판정 |

중요 규칙:

- B가 계약 상태 enum을 DB에 직접 대입하지 않는다.
- C가 AI 추출값을 검증 없이 계약 확정값이나 대시보드 집계에 사용하지 않고, B도
  검증되지 않은 값을 대표 의무에 사용하지 않는다.
- C는 대행사 응답을 먼저 저장한 후 B 비교 서비스를 호출한다. 비교 실패로 응답 원본을
  잃으면 안 된다.
- B와 C는 `apps/api` 하나를 공동 사용하고 별도 백엔드를 만들지 않는다. D는 백엔드
  구현 브랜치를 소유하지 않고 배포본을 검증한다.
- 공통 파일 변경 전 B·C가 API·스키마를 먼저 합의하고 작은 PR로 통합하며 D에는 검증
  영향과 재실행할 시나리오를 공유한다.

## 13. 병렬 개발 체크포인트

| 시점 | 반드시 연결해 볼 흐름 |
| --- | --- |
| Day 1 | 단일 서버·`/docs`·`/health`·DB 연결(B), Upstage Parse(B), 모두싸인 QuickStart(C), 배포 체크리스트(D) |
| Day 2 | `계약 생성(C) → 문서 업로드·원문 접근(B) → 5문항(B) → 분석 시작·조회(B)` |
| Day 3 | `ReviewItem 생성·선택(B) → 조정 초안(C)` |
| Day 4 | `공개 조정 링크·응답(C) → 역제안 비교(B) → 최종 확정·수정 계약서 대조(C)`, 공개 흐름 검증(D) |
| Day 5 | `수정 계약서 확인(C) → 모두싸인 임베디드 편집·사용자 발송·웹훅(C) → 대표 산출물·증빙 승인(B)`, 전체 E2E 실행(D) |
| Day 6 | 계약 목록·D-day·대시보드·타임라인(C) → 전체 P0 회귀(B·C) → 배포본 완료 검증(D) |
| Day 7 | 새 기능 없이 P0 버그 수정, 문서·데모 안정화 |

## 14. 구현 완료 공통 기준

- [ ] `ruff check .` 통과
- [ ] `pytest` 통과
- [ ] OpenAPI와 Pydantic 요청·응답 일치
- [ ] 영속 구조 변경 시 새 마이그레이션 추가
- [ ] 상태 변경과 감사 이벤트가 같은 트랜잭션
- [ ] 소유자 권한·토큰 scope·만료 검증
- [ ] 멱등 키·중복 제출·웹훅 순서 역전 테스트
- [ ] 계약 전문·연락처·공개 토큰·서명 URL 로그 제외
- [ ] mock과 live 결과를 문서에서 명확히 구분
- [ ] AI 변경 시 fixture·프롬프트 버전·`AI_USAGE.md` 갱신

--------------------------------------------------------------------------------

## 15. ⬇️ 여기부터 신규 기획안 6.14 작업 시작 — P2 설계 구역

--------------------------------------------------------------------------------

> **기존 1~14절과 신규 P2 작업을 섞어서 카운트하지 않는다.**
>
> - 기준: `docs/단디계약최종기획안.md` 6.14·10장·11장·12장·13장
> - 우선순위: P2 발표 로드맵
> - 현재 상태: 프론트엔드 16.2~16.5 API 연동, 백엔드 공통 기반과 endpoint 구현
> - 기계 계약: canonical OpenAPI 0/4 `planned`, runtime 4/4, 기반 DB migration 구현
> - 선행 의존성: 이행·증빙 API와 기존 대시보드 API는 현재 구현됨
> - 신규 번호: `P2-B-*`, `P2-C-*`; 기존 B-1~B-16·C-1~C-10과 독립

### 15.1 제품 원칙

- 제품이 광고 성과를 직접 측정하지 않는다. 대행사가 리포트에 보고한 값을
  소상공인이 확인해 기록하고 계약 조건과 대조할 뿐이다.
- 대행사를 이 흐름의 사용자로 추가하지 않는다. 모든 신규 API는 소상공인
  Bearer 인증 API이며 공개 토큰 API를 만들지 않는다.
- AI `extracted_payload`는 초안이다. 소상공인이 확인·수정한
  최신 확정 revision의 `confirmed_payload`만 광고효과 화면·비교·재계약 검토에
  사용한다. P2에서 말하는 광고효과 대시보드는 16.5의 계약별 `/performance`이며,
  기존 전역 `/dashboard` 응답은 이번 범위에서 변경하지 않는다.
- 신호와 문의 문안은 판정·위법성·성과 점수가 아니다. 서버는 문안을 발송하지
  않고 소상공인이 복사해 기존 채널로 직접 보낸다.
- 전환율·CPA·ROAS, 플랫폼 API 직접 수집, 매출 기여도, 위·변조 판정은
  요청·추출·저장·응답하지 않는다.

### 15.2 코드 작성 전 시작 순서

1. **P2-0 공통 계약 PR:** 17.4의 확정값을 기획안, OpenAPI, 데이터 계약과
   공통 enum·오류에 같은 값으로 반영한다.
2. 확정한 16~17절을 `openapi.yaml`, `api-data-contract.md`, 공통 enum·오류에
   먼저 반영하고 구조 검증을 통과시킨다.
3. B는 `source_document_id` 기반 업로드·추출을 구현하고, C는 같은 스키마의 fake로
   revision·근거 snapshot·문의 문안 snapshot·집계 규칙과 테스트를 병렬 작성한다.
4. B의 `PerformanceReport` 기반과 두 API가 merge된 뒤 C가 확인·집계 두 API를
   실제 repository에 연결한다.
5. 4개 operation의 runtime과 회귀 검증이 통과하면 canonical OpenAPI의
   `planned` 표시를 제거한다. `업로드 → 추출 → 최초 확정 → append-only 정정
   → 최신 revision 조회 → 저장된 문의 문안 복사` 배포본 E2E는 실제 자격증명으로
   수행하는 별도 운영 검증으로 남긴다.

## 16. 6.14 광고효과 API 설계 — P2-0 확정값

### 16.1 공통 계약

| 항목 | 규칙 |
| --- | --- |
| 인증 | 모두 소상공인 Bearer 인증 |
| 권한 | `contract_id`의 소유자만 접근 |
| 계약 상태 | 쓰기는 `SIGNED`, `IN_PROGRESS`, `RENEWAL_DUE`, `COMPLETED`에서만 허용하며 report가 Contract 상태를 변경하지 않음 |
| `report_id` | UUID, 경로의 계약과 같은 계약에 속해야 함 |
| 월별 단위 | 계약·`period`별 논리 리포트 1건, 채널별 분리는 P2에서 지원하지 않음 |
| 응답 헤더 | 민감한 계약·성과 자료이므로 성공·오류 모두 `Cache-Control: no-store` |
| 멱등성 | 업로드·추출·확인 쓰기에 `Idempotency-Key` 필수 |
| 원본 파일 | `Document.type=PERFORMANCE_REPORT`와 private Storage를 사용하고, 공개 URL·Storage 경로를 일반 응답에 포함하지 않음 |
| 현재 등록 상태 | 16.2~16.5 모두 canonical OpenAPI·runtime 등록 |

16.1 공통 기반은 구현됐다. Bearer 인증은 기존 공통 인증을 재사용하며, owner-scoped
Contract·report·source Document 조회, 쓰기 허용 상태 guard, 월 중복 preflight와 DB
고유 제약, multipart 멱등 fingerprint 구성요소, 성과 경로 `no-store`, private Document
경계를 공통 service·repository·migration에서 제공한다. 업로드 원자 RPC와 16.2
endpoint, 추출 attempt RPC·service·Upstage·Solar 경계와 16.3 endpoint,
append-only 확정·정정과 결정적 신호·문의 문안 snapshot의 16.4 endpoint, 최신 revision
기준 집계·계약 대조의 16.5 endpoint까지 runtime에 구현해 operation 수는 4/4이다.

`period`는 API에서 `YYYY-MM`으로 받되 연도 `0001`~`9999`만 허용하고,
`(contract_id, period)`를 DB 고유 제약으로
보호한다. 같은 `Idempotency-Key`와 같은 요청은 최초 응답을 재생하고, 다른 요청으로
같은 월의 리포트를 다시 만들면 `409 REPORT_PERIOD_ALREADY_EXISTS`를 반환한다.
확정값 정정은 같은 월의 두 번째 리포트를 생성하지 않고 16.4의 새 revision으로 남긴다.
여러 플랫폼·채널의 개별 리포트와 `channel_key`는 후속 범위다.

전월 비교 신호가 오래된 revision을 가리키지 않도록 P2에서는 가장 최근 확정 월만
정정할 수 있다. 더 뒤의 `CONFIRMED`·`FLAGGED` report가 있으면
`409 REPORT_CORRECTION_DEPENDENCY_EXISTS`를 반환한다. 과거 월 자유 정정과 연쇄
재계산은 후속 범위다.

`DocumentType.PERFORMANCE_REPORT`는 이 전용 업로드 API에서만 생성한다. 기존
계약 문서 업로드 API의 요청 enum과 분리해 `/documents`로 우회 업로드할 수 없게 하고,
원본 열람에는 기존 소유자 전용 문서 접근 API를 재사용한다.

### 16.2 리포트 업로드 — P2-B

`POST /api/v1/contracts/{contract_id}/performance-reports`

- 구현 상태: canonical OpenAPI·FastAPI runtime 등록 완료
- 인증: Bearer
- 담당: P2-B
- 필수 헤더: `Idempotency-Key`
- Content-Type: `multipart/form-data`
- 성공: `201 PerformanceReportCreatedResponse`
- 오류: `401`, `404`, `409`, `422`, `503`

Form:

| 필드 | 타입 | 필수 | 규칙 |
| --- | --- | --- | --- |
| `period` | string | 예 | `YYYY-MM` |
| `file` | binary | 예 | PDF·PNG·JPEG, MIME·magic bytes·크기·빈 파일 검증 |

multipart 멱등 fingerprint는 정규화한 `period`, 파일 바이트의 SHA-256,
검증된 MIME, 파일 크기로 만든다. 같은 키라도 이 값 중 하나가 다르면
`409 IDEMPOTENCY_CONFLICT`다.

응답은 `id`, `contract_id`, `period`, `source_document_id`, `status=UPLOADED`,
nullable `extracted_payload`, `current_revision=null`, `revision_count=0`을 포함한다.
`source_document_id`는 같은 계약의 `Document.id`를 참조하며 해당 문서의 type은
`PERFORMANCE_REPORT`다.

Storage 업로드는 긴 DB 트랜잭션 밖에서 수행한다. 이후 DB RPC에서 `Document`
메타데이터, `PerformanceReport`, `PERFORMANCE_REPORT_UPLOADED` 감사 이벤트를 원자
저장한다. 명시적인 DB 거부에는 업로드 객체를 삭제하지만 전송 오류로 커밋 여부가
불명확하면 객체와 멱등 예약을 보존한다. `Idempotency-Key`에서 결정적으로 만든
Document·report UUID로 응답 유실과 멱등 응답 저장 실패를 복구한다. 같은 계약·`period`의
두 번째 논리 리포트 생성은 `409 REPORT_PERIOD_ALREADY_EXISTS`로 거부한다.

### 16.3 리포트 지표 추출 — P2-B

`POST /api/v1/contracts/{contract_id}/performance-reports/{report_id}/extract`

- 인증: Bearer
- 담당: P2-B
- 필수 헤더: `Idempotency-Key`
- 요청 body: 없음
- 구현 상태: canonical OpenAPI·FastAPI runtime 등록 완료
- 성공: `200 PerformanceReportExtractedResponse`
- 오류: `401`, `404`, `409`, `422`, `502 REPORT_EXTRACT_FAILED`,
  `503 EXTERNAL_SERVICE_UNAVAILABLE`

`UPLOADED`에서만 시작한다. 원본 파일을 Upstage Document Parse로 읽고 Solar가
지표명과 숫자 후보를 매핑한다. 외부 호출은 긴 DB 트랜잭션 밖에서 수행하고,
검증된 완전한 결과와 `PERFORMANCE_REPORT_EXTRACTED` 감사 이벤트만 원자적으로
저장한다.

`extracted_payload`의 각 AI 추출 필드는 `value`, `source_page`, `source_text`,
`confidence`, `verification_status`를 가진다. 필수 지표와 선택 지표뿐 아니라
`published_content_count`도 원문에 명시된 경우에만 후보로 반환한다. 찾지 못한 값을
행 수·URL 수 등으로 추정하지 않고 `NOT_FOUND`로 반환해 소상공인이 확인 단계에서
입력하게 한다.

성공하면 `EXTRACTED`로 전이하고 `current_revision=null`, `revision_count=0`을 유지한다.
이 값을 대시보드·비교에 사용하거나 이 단계에서 문의 문안을 생성하지 않는다.
timeout·HTTP 오류·Parse 실패·AI 스키마 오류는 고정 샘플로 대체하지 않고
`502 REPORT_EXTRACT_FAILED`를 반환한다. 이때 상태는 `UPLOADED`를 유지하며 사용자의
새 `Idempotency-Key`를 사용한 명시적 extraction attempt 재시도만 허용한다. 서버가
attempt 전체를 자동으로 다시 실행하지는 않는다. 다만 이미 claim한 동일 attempt 안에서
Solar 요청이 일시적인 transport 오류 또는 HTTP `429`/`500`/`502`/`503`/`504`로
실패하면 adapter가 최대 1회 전송 재시도할 수 있다. 이 재전송은 새 attempt를 만들거나
Document Parse를 다시 실행하지 않으며, 두 전송이 모두 실패하면 해당 attempt를
`REPORT_EXTRACT_FAILED`로 종료한다.

`Document.parse_status`는 파일 파싱 시도의 기술 상태이고 `PerformanceReport.status`는
사용자 흐름의 업무 상태다. Parse 실패는 Document를 `FAILED`로 기록할 수 있지만
report는 `UPLOADED`를 유지한다. Solar 매핑만 실패했다면 Document Parse 성공 상태를
보존하고 report만 `UPLOADED`에 둔다. 명시적 재시도에서만 기술 상태를 다시 진행시킨다.

추출 서비스는 먼저 완료된 같은 멱등 요청을 재생한 뒤 report와 Document를 lock해
report가 `UPLOADED`인지 검사하고 기술 상태를 `PROCESSING`으로 claim한다. 다른 멱등
키의 동시 요청은 외부 AI를 중복 실행하지 않는다. 성공 시 Document=`COMPLETED`,
report=`EXTRACTED`, 추출 payload와 감사 이벤트를 원자 저장한다. Parse 실패는
Document=`FAILED`, Solar만 실패하면 Document=`COMPLETED`를 보존한다. P2는 Parse
결과를 별도 저장하지 않으므로 명시적 재시도에서는 Document Parse부터 다시 실행한다.

같은 멱등 키의 성공·실패 응답은 최초 `requestId`까지 재생한다. 완료·실패 RPC의 응답이
유실됐거나 멱등 응답 저장이 실패한 경우에는 owner-scoped report와 source Document를
다시 확인해 이미 커밋된 결과만 복구하며, 커밋 여부가 불명확하면 AI를 다시 호출하지 않고
`503 EXTERNAL_SERVICE_UNAVAILABLE`로 종료한다. 일반 자동화 검증은 mock·fake 경계다.
2026-08-01 비식별 합성 PDF로 Upstage Document Parse → Solar Chat Adapter live 연결과
8개 지표 strict 근거 검증은 통과했다. 배포 FastAPI·live Supabase까지 포함한 E2E는
별도 배포 검증으로 남기며 상세 안전 메타데이터는 `AI_USAGE.md`에 기록한다.

claim할 때 `extraction_attempt_id`와 `extraction_started_at`을 저장한다. 활성
`PROCESSING`이 15분 미만이면 다른 키의 요청을 `409 REPORT_EXTRACTION_IN_PROGRESS`로
거부한다. 15분 이상 지난 stale attempt만 새 `Idempotency-Key`로 원자 재점유할 수
있으며, 이전 멱등 예약을 abandon하고 `PERFORMANCE_REPORT_EXTRACTION_RECOVERED` 감사
이벤트를 남긴다. 동일 attempt의 완료만 상태와 payload를 저장할 수 있어 오래된 작업의
늦은 응답이 새 결과를 덮어쓰지 못하게 한다. 복구는 사용자의 명시적 재시도에서만
수행하고 서버가 extraction attempt 전체를 자동 재개하지 않는다. 동일 attempt 내부의
Solar 일시적 전송 실패에 대한 최대 1회 재전송만 위 예외로 허용한다.

### 16.4 추출값 확인·수정 — P2-C

`PATCH /api/v1/contracts/{contract_id}/performance-reports/{report_id}`

- 인증: Bearer
- 담당: P2-C
- 필수 헤더: `Idempotency-Key`
- 구현 상태: canonical OpenAPI·FastAPI runtime 등록 완료
- 성공: `200 PerformanceReportConfirmedResponse`
- 오류: `401`, `404`, `409`, `422`
- 저장 기반 장애: `503 EXTERNAL_SERVICE_UNAVAILABLE`

요청 예시:

```json
{
  "expected_revision": 0,
  "confirmed_payload": {
    "impressions": 12500,
    "likes": 430,
    "comments": 37,
    "reach": 9800,
    "saves": 82,
    "shares": 24,
    "follower_net_change": 61,
    "published_content_count": 4,
    "inquiries": 16,
    "reservations": 7,
    "purchases": null
  },
  "has_issue": false,
  "issue_note": null,
  "correction_reason": null
}
```

`EXTRACTED`에서는 `expected_revision=0`, `correction_reason=null`로 version 1을 최초
확정한다. `CONFIRMED`·`FLAGGED`에서는 현재 version과 같은 `expected_revision` 및
비어 있지 않은 `correction_reason`을 받아 version N+1 정정 revision을 추가한다.
revision이 다르면 `409 REPORT_REVISION_CONFLICT`를 반환한다. 기존 revision·flag·문의
문안은 수정하거나 삭제하지 않으며, 같은 멱등 요청은 최초 revision 응답을 재생한다.
달력상 뒤 월이 이미 확정된 상태에서 과거 월을 처음 확정하면 월간 비교 누락을 막기 위해
`409 REPORT_PERIOD_ORDER_CONFLICT`로 거부한다. 바로 전월 revision이 flag 계산 이후
정정된 경우도 원자 RPC에서 감지해 `409 REPORT_REVISION_CONFLICT`로 재확인을 요구한다.
더 뒤의 확정 월이 있으면 `409 REPORT_CORRECTION_DEPENDENCY_EXISTS`로 정정을 거부한다.
`expected_revision`은 0 이상 정수이며, 정정 사유는 앞뒤 공백과 제어문자를 제거한
1~500자 문자열이어야 한다.

서비스는 같은 멱등 요청 재생을 상태·revision 검사보다 먼저 수행한다. 새 요청은 report
행을 `FOR UPDATE`로 lock한 뒤 상태, 현재 version, 더 뒤의 확정 월 존재 여부를 다시
검사하고 새 revision 번호를 할당한다. DB 고유 제약 오류를 정상적인 동시성 제어로
대신하지 않는다.

`impressions`, `likes`, `comments`는 확정 시 필수며 이외 지표는 nullable이다.
`published_content_count`는 정식 제품 필드인 nullable 0 이상 정수다. 리포트에
명시되었거나 소상공인이 확인·입력한 경우에만 저장하며, `0`과 알 수 없음을 뜻하는
`null`을 구분한다.

`engagement_rate`는 요청으로 받지 않고 서버가
`(likes + comments + saves + shares) / impressions`로 결정 계산한다. nullable 세부
지표는 0으로 계산하고 `impressions=0`이면 0으로 단정하지 않고
`engagement_rate=null`로 둔다. 비교는 반올림 전 `Decimal` 값으로 수행하고 API는
비율값을 소수 6자리 `ROUND_HALF_UP`으로 반환한다. 화면의 백분율 표시는 소수
2자리로 반올림한다.
정확한 DB·도메인 상한은 `36893488147419103228.000000`이고, JSON number
IEEE-754 직렬화 상한 `36893488147419103232`를 OpenAPI 응답 경계로 사용한다.
계산·신호·저장은 직렬화 전 정확한 `Decimal` 값으로만 수행한다.

`has_issue=true`면 비어 있지 않은 `issue_note`가 필요하다. 사용자 이상 기록
또는 17.3의 결정적 확인 신호가 하나 이상이면 `FLAGGED`, 그렇지 않으면
`CONFIRMED`다. 최초 확정은 `PERFORMANCE_REPORT_CONFIRMED` 또는
`PERFORMANCE_REPORT_FLAGGED`, 정정은 결과 상태를 함께 기록한
`PERFORMANCE_REPORT_CORRECTED` 감사 이벤트를 남긴다.

`PerformanceReportRevision`, `PerformanceFlag`, 결정적 문의 문안 snapshot,
report의 `current_revision_id`·현재 상태와 감사 이벤트를 같은 트랜잭션에 저장한다.
응답의 `current_revision`은 방금 생성한 revision이고 `revision_count`는 새 version과
같다.

### 16.5 월별 기록·대조 조회 — P2-C

`GET /api/v1/contracts/{contract_id}/performance`

- 인증: Bearer
- 담당: P2-C
- 구현 상태: canonical OpenAPI·FastAPI runtime 등록 완료
- 성공: `200 ContractPerformanceResponse`
- 오류: `401`, `404`, `422`
- 저장 기반 장애: `503 EXTERNAL_SERVICE_UNAVAILABLE`

응답은 다음 네 구역을 포함한다.

| 구역 | 내용 |
| --- | --- |
| `reports` | 상태, `source_document_id`, 현재 revision과 version 오름차순 append-only revision 이력 |
| `confirmed_series` | 각 월의 최신 `CONFIRMED`·`FLAGGED` revision만 `period` 오름차순으로 집계 |
| `flags` | 최신 revision의 확인 신호·소상공인 이상 사유·날짜·계약 원문 근거 |
| `inquiry_drafts` | 최신 revision의 flag와 연결해 저장한 복사용 문의 문안 snapshot |

`UPLOADED`·`EXTRACTED`의 값은 `reports`에서 확인 화면을 위해 보일 수 있지만
`confirmed_series`, 계약 대조, 재계약 근거에는 포함하지 않는다. GET은 상태,
기록, 감사 이벤트를 변경하지 않고 AI나 문안 생성기를 실행하지 않는다. 과거 revision은
감사 이력으로만 제공하고 현재 집계에 중복 포함하지 않는다. 원본은
`source_document_id`를 기존 문서 접근 API에 전달해 열람한다. 문의 문안은 저장된
snapshot만 응답으로 제공하고 서버가 외부로 발송하지 않는다. owner 확인과 전체
report/revision/flag/문의 문안은 단일 DB statement snapshot으로 읽는다.

## 17. 데이터·상태·비교 규칙 — P2-0 확정값

### 17.1 지표 범위

| 구분 | 필드 | 규칙 |
| --- | --- | --- |
| 확정 필수 | `impressions`, `likes`, `comments` | 0 이상 정수 |
| 리포트 선택 | `reach`, `saves`, `shares` | nullable, 값이 있으면 0 이상 정수 |
| 리포트 선택 | `follower_net_change` | nullable 정수, 감소는 음수 허용 |
| 계약 대조 | `published_content_count` | 정식 제품 필드, nullable 0 이상 정수; `0`과 알 수 없음인 `null` 구분 |
| 소상공인 선택 입력 | `inquiries`, `reservations`, `purchases` | nullable, 0 이상 정수 |
| 서버 파생 | `engagement_rate` | 확정값으로만 `Decimal` 계산, 클라이언트 입력 금지 |

요청·AI 출력 스키마는 `additionalProperties=false`로 제한하여 CPA·ROAS·매출
기여도·성과 점수가 실수로 저장되지 않게 한다.

`published_content_count`는 원문 근거가 있으면 AI 추출 후보로 제공할 수 있지만
소유자가 확정한 값만 계약 대조에 사용한다. 값이 `null`이면 수량 신호를 만들지 않는다.
`engagement_rate` 계산에서는 nullable `saves`·`shares`를 0으로 보되,
`impressions=0`이면 `null`이다. 월별 하락 비교에서는 두 달의 `saves`·`shares`
포함 구성이 같을 때만 비교한다.

revision에는 원본 정수 지표를 보존한다. 전월 임계값 판정은 API에 표시한 소수 6자리
반응률을 다시 사용하지 않고 원본 정수에서 충분한 정밀도의 `Decimal`로 매번 계산한다.
저장하거나 반환하기 위한 반올림은 판정 결과에 영향을 주지 않는다.

### 17.2 `PerformanceReport` 상태 불변식

| 상태 | 저장 규칙 | 허용 작업 |
| --- | --- | --- |
| `UPLOADED` | `source_document_id` 존재, 추출값·revision 없음 | 추출 |
| `EXTRACTED` | `extracted_payload` 존재, revision 없음 | version 1 최초 확정 |
| `CONFIRMED` | 현재 revision 존재, 현재 flag 0개 | append-only 정정 revision 추가 |
| `FLAGGED` | 현재 revision 존재, 현재 flag 1개 이상 | append-only 정정 revision 추가 |

추출 실패는 새로운 성과 값이나 상태를 만들지 않고 `UPLOADED`를 유지한다.
`CONFIRMED`·`FLAGGED`는 기존 revision을 변경할 수 없다는 의미에서 terminal이다.
정정 PATCH는 terminal revision을 전이하거나 덮어쓰지 않고 새 immutable revision을
추가한 뒤 report의 `current_revision_id`와 현재 표시 상태만 갱신한다. 따라서 현재
projection은 `CONFIRMED`와 `FLAGGED` 사이에서 바뀔 수 있지만 과거 revision의 상태는
변하지 않는다.

`PerformanceReportRevision`은 `report_id` 안에서 1부터 시작하는 `version`, 확정
payload, 결정 계산한 반응률, 상태, nullable `corrected_from_revision_id`, nullable
`correction_reason`, `confirmed_at`을 보존한다. `(report_id, version)`은 고유하며,
version 2 이상에는 직전 revision과 비어 있지 않은 정정 사유가 필요하다. API의
`expected_revision`과 현재 version이 다르면 새 revision을 만들지 않는다.

DB는 다음 관계를 제약 또는 원자 RPC로 강제한다.

- `performance_reports.source_document_id`는 고유하며 같은 `contract_id`의
  `Document.type=PERFORMANCE_REPORT`를 참조한다.
- `current_revision_id`는 반드시 자기 report의 revision을 참조한다.
- `corrected_from_revision_id`는 같은 report의 바로 전 version을 참조한다.
- 후속 확정 월이 있는 report에는 정정 revision을 추가하지 않는다.
- 현재 report 상태는 current revision 상태와 같고, 과거 revision은 UPDATE·DELETE하지
  않는다.
- 추출 완료·실패는 현재 `extraction_attempt_id`와 일치하는 작업만 기록하고 stale
  attempt의 늦은 응답은 버린다.

### 17.3 `PerformanceFlag`·문의 문안

P2의 `flag_type`은 다음 범위로 제한한다.

- `DELIVERABLE_COUNT_SHORTFALL`: 검증된 월 단위 계약 수량과 확정된
  `published_content_count`가 모두 있고 실제 게시 수가 약정보다 적을 때만 생성한다.
  실제 게시 수가 같거나 많으면 생성하지 않는다.
- `ENGAGEMENT_RATE_DROP`: 달력상 바로 전월과 현재 월의 최신 확정 revision이 있고,
  두 달 모두 노출 수 1,000 이상, 이전 반응률이 0보다 크며, 반올림 전 값의 절대
  하락폭이 1.0%p 이상이고 상대 하락률이 25% 이상일 때만 생성한다. 두 조건은 동시에
  충족해야 한다.
- `OWNER_REPORTED_ISSUE`: 소상공인이 `has_issue=true`와 사유를 명시한 경우

첫 달, 달력상 전월 누락, `impressions=0`, 표본 미달, 이전 반응률 0, 두 달 사이의
`saves`·`shares` 포함 구성 차이 중 하나라도 있으면 `ENGAGEMENT_RATE_DROP`을 만들지
않는다.
임계값 판정은 반올림 전 `Decimal`로 수행한다.

새로운 가상 Clause 엔티티는 만들지 않는다. 공개 응답의
`basis_extracted_term_ids`는 중복 없는 목록이지만 DB에서는
`PerformanceFlagBasisTerm(flag_id, extracted_term_id)` 연결 테이블로 같은 계약의
`ExtractedTerm.id`를 참조한다. 수량 부족
신호에는 `source_type=CONTRACT_DOCUMENT`, `verification_status=VERIFIED`이고 원문
페이지·문장이 있는 `CONTENT_QUANTITY`와 월 단위임을 확인하는 `POSTING_FREQUENCY`
근거 두 개가 모두 필요하다. 둘 중 하나라도 불명확하면 수량 신호를 만들지 않는다.

`PerformanceFlag`는 report 자체가 아니라 `report_revision_id`에 속한다. 근거 ID와
함께 문서 ID·페이지·문장·confidence·기대 수량·단위 snapshot을 flag에 보존한다.
사용자 이상 기록과 반응률 하락은 적절한 계약 원문 근거가 없으므로
`basis_extracted_term_ids=[]`를 허용한다. 반응률 하락은
`comparison_report_revision_id`만 보존하고 report ID는 해당 revision에서 유도한다.
계약 위반으로 표현하지 않는다.

문의 문안은 flag의 확정값·비교 기준·nullable 계약 원문 근거만 사용한다. “확인이
필요합니다” 톤을 사용하고 대행사 성과·계약 위반·지급 여부를 단정하지 않는다.

문안은 Solar가 아니라 version이 고정된 결정적 템플릿
`performance-inquiry-copy-v1`로 확정·정정 시 생성한다. `PerformanceInquiryDraft`는
고유한 `flag_id`, `text`, `template_version`, `created_at`을 snapshot으로 보존하고
report revision은 flag에서 유도한다. 조회 시 다시 만들거나 외부로 발송하지 않는다.

템플릿의 정확한 본문은 다음과 같다.

- `DELIVERABLE_COUNT_SHORTFALL`:
  “{period} 리포트의 게시물 수는 {actual_count}건으로 기록되어 있습니다. 계약 원문에서
  확인한 월 {expected_count}건과 차이가 있어 해당 월 게시 수와 집계 기준을 확인
  부탁드립니다.”
- `ENGAGEMENT_RATE_DROP`:
  “{previous_period} 반응률 {previous_rate_percent}%에서 {period}
  {current_rate_percent}%로 낮아진 것으로 계산됩니다. 두 달 리포트의 집계 기준과 변동
  사유를 확인 부탁드립니다.”
- `OWNER_REPORTED_ISSUE`:
  “{period} 리포트와 관련해 다음 내용을 확인하고 싶습니다: {issue_note} 관련 수치와
  집계 기준을 확인 부탁드립니다.”

반응률 placeholder는 백분율 소수 2자리, 수량은 10진 정수로 포맷한다. `issue_note`는
앞뒤 공백과 제어문자를 제거하고 최대 500자로 제한한다. 생성 결과는 최대 1,000자이며
템플릿 밖의 문장이나 법적·성과 판정을 추가하지 않는다.

### 17.4 P2-0 확정 결정

- [x] 계약·월별 논리 리포트 한 건만 허용하고 `(contract_id, period)`를 고유하게 한다.
- [x] `published_content_count`를 nullable 0 이상 정식 제품 필드로 사용하고 약정보다 부족할 때만 신호를 만든다.
- [x] `saves`·`shares` 구성이 같은 양월 노출 1,000 이상에서 반올림 전 Decimal의 절대 1.0%p·상대 25% 이상 하락을 동시에 만족할 때만 신호를 만들고 API는 비율값을 소수 6자리로 반환한다.
- [x] 계약 근거는 `basis_extracted_term_ids`로 기존 검증된 `ExtractedTerm`에 연결하고 가상 Clause를 만들지 않는다.
- [x] 기존 PATCH에서 가장 최근 확정 월의 append-only 정정 revision만 추가하고 과거 값을 덮어쓰지 않는다.
- [x] `source_document_id`는 `Document.type=PERFORMANCE_REPORT`인 기존 `Document.id`를 참조한다.
- [x] 문의 문안은 `performance-inquiry-copy-v1` 결정적 템플릿으로 생성해 revision별 snapshot으로 저장하고 조회 시 생성하지 않는다.

위 일곱 가지는 이 API 명세서에서 확정한 P2-0 값이다. P2-0 공통 계약은
`docs/단디계약최종기획안.md`, OpenAPI, 데이터 계약, 공통 enum·오류에 같은 값을
반영하고 구조 검증을 통과해야 완료다. runtime과 migration은 이 공통 계약과 다른
값으로 먼저 구현하지 않는다.

### 17.5 감사·보안·AI 경계

- 감사 이벤트:
  `PERFORMANCE_REPORT_UPLOADED`, `PERFORMANCE_REPORT_EXTRACTED`,
  `PERFORMANCE_REPORT_CONFIRMED`, `PERFORMANCE_REPORT_FLAGGED`,
  `PERFORMANCE_REPORT_CORRECTED`, `PERFORMANCE_REPORT_EXTRACTION_RECOVERED`
- 16.1 기반 migration에서 DB CHECK를 확장하고 위 값을 기존 `AuditEventType`에
  병합했다. `PERFORMANCE_REPORT_UPLOADED`, `PERFORMANCE_REPORT_EXTRACTED`,
  `PERFORMANCE_REPORT_EXTRACTION_RECOVERED`는 각 원자 RPC에서 생성한다. 확정·flag·
  정정 이벤트는 16.4 `confirm_performance_report_with_audit` 원자 RPC에서
  revision·flag·문의 문안과 함께 생성한다.
- 업로드는 `Document` 메타데이터·report·감사 이벤트, 추출은
  `extracted_payload`·상태·감사 이벤트, 확정·정정은 revision·flag·문의 문안
  snapshot·현재 projection·감사 이벤트를 각각 원자 저장한다.
- 기존 revision·과거 flag·문의 문안 snapshot은 UPDATE·DELETE하지 않는다. 멱등
  재생은 revision이나 감사 이벤트를 중복 생성하지 않는다.
- 원본 리포트·전체 OCR 텍스트·AI 입출력·문의 문안·소상공인 입력을 로그에
  남기지 않는다.
- Upstage·Solar는 지표 추출에만 사용하고 기존 Adapter 규칙에 따라 `mock`/`live`를
  분리한다. private 원본 다운로드 → Upstage Parse →
  `performance-report-metrics-v1` Solar strict-schema 매핑을 내부 조합기로
  제공한다. 문의 문안은 결정적 템플릿으로 만들며, 일반 `pytest`는 외부
  네트워크를 호출하지 않는다.
- 반응률·월 정렬·수량 비교·상태 전이는 AI가 아닌 결정적 코드와 DB 제약으로
  수행한다.
- GET에서는 AI·문안 생성·상태 변경·감사 이벤트 생성을 수행하지 않는다.

## 18. 신규 P2 백엔드 B·C 독립 역할 분담

### 18.1 API 담당 — 2개 : 2개

| 신규 담당 | Method | Path | 핵심 책임 |
| --- | --- | --- | --- |
| P2-B | `POST` | `/contracts/{contract_id}/performance-reports` | private 리포트 업로드·메타데이터 |
| P2-B | `POST` | `/contracts/{contract_id}/performance-reports/{report_id}/extract` | Upstage·Solar 지표 추출 |
| P2-C | `PATCH` | `/contracts/{contract_id}/performance-reports/{report_id}` | 최초 확정·append-only 정정·flag·문의 snapshot |
| P2-C | `GET` | `/contracts/{contract_id}/performance` | 최신 revision 집계·계약 대조·저장 문안 조회 |

B는 파일·AI 호출·추출 스키마·재시도 경계를, C는 사용자 확정·결정 계산·대조·
revision·문의 문안 snapshot·조회 집계를 맡는다. API 개수는 2:2이고 B의 외부 AI
경계와 C의 revision·상태·집계 규칙을 감안하면 구현 분량도 대략 동등하다.

### 18.2 P2-B 작업 순서

| 순서 | 작업 | 완료 조건 |
| --- | --- | --- |
| P2-B-1 | `PerformanceReport` 기본·AI 추출 스키마, `DocumentType.PERFORMANCE_REPORT` 경계 | `source_document_id`, 근거, null·0 구분, 파일 검증 테스트 |
| P2-B-2 | 기반 migration·repository·mock/live Storage | 계약·월·source Document 고유 제약, multipart fingerprint, 소유권, 중복 409, 업로드 롤백·응답 유실 테스트 |
| P2-B-3 | 리포트 업로드 API | Document·report·`UPLOADED` 감사 이벤트 원자 저장, 멱등 재생, 경로 비노출 |
| P2-B-4 | Upstage Parse·Solar 매핑·추출 API | attempt claim·stale 복구, `published_content_count` 후보, 근거·confidence, strict schema, 실패 매핑 |
| P2-B-5 | AI fixture·mock/live 분리·`AI_USAGE.md` | NOT_FOUND·null·0 fixture, 일반 테스트 무네트워크, 명시적 live 재현 절차 |

### 18.3 P2-C 작업 순서

| 순서 | 작업 | 완료 조건 |
| --- | --- | --- |
| P2-C-1 | `PerformanceReportRevision`·revision별 `PerformanceFlag`·문의 snapshot·현재 projection | 추출값과 확정값 분리, 과거 revision 불변 테스트 |
| P2-C-2 | 반응률·수량 부족·전월 대비 결정 규칙 | 1,000 노출·1.0%p·25%·월 공백·saves/shares 구성·약정 초과 경계 테스트 |
| P2-C-3 | 최초 확정·정정 PATCH와 migration/RPC | replay 우선, row lock, `expected_revision`, 최신 월 제한, 정정 사유, revision·flag·문안·감사 이벤트 원자 저장 |
| P2-C-4 | 월별 조회·집계·계약 대조 | 미확정·과거 revision 제외, 정렬·소유권·`basis_extracted_term_ids` 테스트 |
| P2-C-5 | 결정적 문의 문안 snapshot·재계약 근거 연결 | template version, GET 무생성·무AI, 미발송·비판정 톤, 과거 이력 보존 |

### 18.4 병렬 개발·명세 충돌 방지

- P2-0 공통 계약 PR에서 확정한 필드명·enum·임계값·revision 규칙을 각자 runtime에서
  다르게 바꾸지 않는다.
- 신규 router는 기존의 큰 `contracts.py`에 섞지 않고 `endpoints/performance.py`로
  분리한다.
- B는 업로드·추출 service, C는 확인·집계 service와 규칙 파일을 별도로 두어
  같은 파일을 동시 편집하지 않는다.
- `openapi.yaml`, `api-data-contract.md`, `DocumentType`, 공통 enum·오류, performance
  schema, router include, `SupabaseAdapter`는 병합 충돌 위험이 크므로 계약 PR 담당 1명이
  통합하고 나머지 1명이 교차 리뷰한다.
- migration은 B가 `PERFORMANCE_REPORT` Document type·report identity·계약/월 고유
  제약을 먼저 배치하고, C가 revision·flag·문의 snapshot·현재 projection·PATCH RPC를
  후속 migration으로 더한다. 이미 merge된 migration 파일을 수정하지 않는다.
- C는 B 기반 merge 전에 repository fake로 최초 확정·정정 동시성·최신 revision
  계산·상태·집계 테스트를 진행하고, merge 후 실제 저장 연결만 작은 PR로 추가한다.

## 19. P2 구현 완료 기준

- [x] 17.4 확정값 7개를 기획안·API 명세·OpenAPI·데이터 계약·공통 enum·오류·Pydantic에 같은 값으로 반영
- [x] 계획 OpenAPI 4개를 active로 전환하고 FastAPI runtime method·path·operationId·응답 일치
- [x] 구현 후 활성 API 34개, B 13개, C 21개 담당표 일치
- [x] `Document.type=PERFORMANCE_REPORT`, source Document 고유 FK, `PerformanceReport`, revision·basis 연결·flag·문의 snapshot·현재 projection DB 제약 일치
- [x] `REPORT_PERIOD_ALREADY_EXISTS`, `REPORT_PERIOD_ORDER_CONFLICT`, `REPORT_REVISION_CONFLICT`, `REPORT_CORRECTION_DEPENDENCY_EXISTS`, `REPORT_EXTRACTION_IN_PROGRESS`, `REPORT_EXTRACT_FAILED` 상태·재시도·멱등 테스트
- [x] 원본 Document·AI 추출값·소유자 확정 revision·과거 revision 교차 혼용 금지
- [x] `UPLOADED → EXTRACTED → CONFIRMED / FLAGGED`, 추출 attempt claim·15분 stale 복구·늦은 응답 거부, terminal PATCH 최신 월 revision 추가·stale/dependency 409 테스트
- [x] 각 월의 최신 확정 revision만 광고효과 화면·계약 대조·재계약 근거에 집계
- [x] 수량 부족만 신호, 검증된 수량·월 주기 근거, 양월 1,000 노출·1.0%p·25%·saves/shares 구성 경계 테스트
- [x] 문의 문안 3종 exact template·길이·포맷·snapshot·GET 무생성·무AI·미발송·비판정 톤 테스트
- [x] 소유권·private Storage·문서 접근·`no-store`·multipart 멱등 fingerprint·로그 마스킹 테스트
- [x] revision·flag·문의 snapshot·현재 projection·감사 이벤트 원자 저장과 중복 방지
- [x] B·C 단위·통합·API 테스트와 기존 P0 전체 회귀 통과
- [x] Upstage·Solar mock/live 분리, 명시적 live 결과, `AI_USAGE.md` 갱신
- [ ] 프론트 목업의 임시 데이터를 실제 API로 교체하고 최초 확정·정정·최신 조회·과거 이력 보존 E2E 통과
