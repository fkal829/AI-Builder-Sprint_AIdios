# 안심홍보계약 API 명세서

<!-- markdownlint-configure-file {"MD013": false} -->

> 버전: `0.2.0`<br>
> Base URL: `/api/v1`<br>
> 상세 기계 판독 명세: `packages/contracts/openapi/openapi.yaml`<br>
> 적용 범위: 해커톤 P0

이 문서는 백엔드 API와 개발 순서를 사람이 읽을 수 있도록 정리한다. 제품 범위와 사용자
흐름의 최상위 기준은 저장소 상위의 `../기획안.md`이며 이 파일은 수정하지 않는다.
그 범위 안에서 필드·enum·응답의 기계 판독 기준은
`packages/contracts/openapi/openapi.yaml`, 영속·전이 불변식의 기준은
`docs/api-data-contract.md`다. 세 문서는 같은 변경에서 함께 맞춘다. 이 문서의 파일
경로 표기는 모두 저장소 루트 기준이다.

## 1. 담당 구분

제품 범위와 사용자 흐름은 최종 기획안을 그대로 적용한다. 다만 최신 팀 실행 결정에 따라
기획안에서 D에게 배정했던 백엔드 구현은 B와 C가 나누어 맡고, D는 백엔드 코드를 직접
개발하지 않고 배포·E2E·데모 검증을 담당한다.

- **B — 문서·AI·공통 기반·이행:** FastAPI 공통 기반, DB·Storage, 문서·분석,
  이행 항목과 증빙 API
- **C — 계약·모두싸인·대시보드:** 계약 생애주기, 조정, 합의서, 모두싸인, 일정·집계
- **D — 배포·QA 검증:** 배포·환경변수 확인, E2E 실행, 데모 데이터와 테스트 증빙;
  백엔드 endpoint·service·repository 구현은 맡지 않음

API 29개의 구현 주 담당은 B 11개, C 18개이며 D가 직접 구현하는 API는 0개다.
B는 기존 6개 문서·AI API에 공통 health와 이행·증빙 4개를 더 맡고, C는 기존 17개
계약 API에 대시보드 1개를 더 맡는다. D는 모든 endpoint의 배포본 E2E와 데모 검증
결과를 제공하지만 코드 구현 소유자는 아니다.

### 1.1 전체 API 담당표

| 담당 | Method | Path | 기능 |
| --- | --- | --- | --- |
| B | `GET` | `/health` | 서버 상태 확인 |
| C | `GET` | `/contracts` | 계약 목록·만료 D-day 조회 |
| C | `POST` | `/contracts` | 계약 생성 |
| C | `GET` | `/contracts/{contract_id}` | 계약 상세 조회 |
| C | `GET` | `/contracts/{contract_id}/timeline` | 감사 타임라인 조회 |
| C | `PUT` | `/contracts/{contract_id}/renewal-decision` | 갱신·조건 변경·종료 의사 저장 |
| B | `POST` | `/contracts/{contract_id}/documents` | 계약 문서 업로드 |
| B | `GET` | `/contracts/{contract_id}/documents/{document_id}/access` | 원문 페이지 임시 접근 |
| B | `PUT` | `/contracts/{contract_id}/understood-terms` | 사용자 이해조건 5문항 저장 |
| B | `POST` | `/contracts/{contract_id}/analysis` | 분석 작업 시작 |
| B | `GET` | `/contracts/{contract_id}/analysis` | 최근 분석 상태·결과 조회 |
| B | `PATCH` | `/contracts/{contract_id}/review-items/{item_id}` | 검토 항목 선택 저장 |
| C | `POST` | `/contracts/{contract_id}/adjustment-requests` | 조정 요청 초안 생성 |
| C | `GET` | `/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}` | 소유자용 조정 상세 조회 |
| C | `POST` | `/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}/send` | 조정 링크 활성화 |
| C | `GET` | `/public/adjustment-requests/{token}` | 대행사용 조정 요청 조회 |
| C | `POST` | `/public/adjustment-requests/{token}/open` | 대행사 최초 열람 기록 |
| C | `POST` | `/public/adjustment-requests/{token}/responses` | 대행사 1회 응답 제출 |
| C | `POST` | `/contracts/{contract_id}/adjustment-confirmation` | 최종 조정 결과 확정 |
| C | `POST` | `/contracts/{contract_id}/agreement` | 변경·확인 합의서 생성 |
| C | `GET` | `/contracts/{contract_id}/agreement` | 변경·확인 합의서 조회 |
| C | `POST` | `/contracts/{contract_id}/signature-embedded-drafts` | 모두싸인 임베디드 서명 초안 생성 |
| C | `GET` | `/contracts/{contract_id}/signature` | 서명 상태 조회 |
| C | `POST` | `/webhooks/modusign` | 모두싸인 웹훅 수신 |
| B | `GET` | `/contracts/{contract_id}/obligations` | 이행 항목 목록 조회 |
| B | `POST` | `/contracts/{contract_id}/obligations/{obligation_id}/evidence-link` | 증빙 제출 링크 생성 |
| B | `POST` | `/public/obligations/{token}/evidence` | 대행사 증빙 URL 제출 |
| B | `PATCH` | `/contracts/{contract_id}/obligations/{obligation_id}` | 증빙 승인·이의 처리 |
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
- 합의서 생성
- 모두싸인 임베디드 서명 초안 생성
- 증빙 제출 링크 생성

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
| `503` | 분석 작업 접수 실패 |

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

### 3.5 계약 감사 타임라인 조회

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
ADJUSTMENT_EXPIRED, AGREEMENT_CREATED, SIGNATURE_DRAFT_CREATED,
SIGNATURE_REQUESTED, SIGNATURE_STARTED,
SIGNATURE_COMPLETED, SIGNATURE_ABORTED, SIGNATURE_FAILED, OBLIGATION_CREATED,
EVIDENCE_LINK_CREATED, EVIDENCE_SUBMITTED, EVIDENCE_APPROVED,
EVIDENCE_DISPUTED, RENEWAL_DECISION_SAVED
```

상태나 사용자 의사가 실제로 바뀌는 쓰기는 대응 이벤트와 원자적으로 기록한다. 멱등
재생처럼 상태가 바뀌지 않으면 새 이벤트를 만들지 않는다.

### 3.6 만료·재계약 의사 저장

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

최신 작업이 `FAILED`이고 실행 중 작업이 없으면 사용자가 새 `Idempotency-Key`와 최신
계약 문서 ID로 수동 재시작할 수 있다. 계약은 `ANALYZING`을 유지하고 새 `QUEUED`
작업과 `ANALYSIS_RESTARTED` 감사 이벤트를 만든다. 기존 멱등 키 재호출은 최초 HTTP
결과(보통 `202` 접수, 접수 자체 실패 시 `503`)를 재생하고 새 작업을 만들지 않는다.
비동기 `FAILED` 상태는 조회 API에서 확인하며 자동 무한 재시도는 하지 않는다.

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
  "expires_in_hours": 72
}
```

- 항목은 중복 없이 1~4개이며 `SELECTED` 상태인 `COMPROMISE`·`REQUEST`만 허용한다.
  원안 수용인 `ACCEPT` 항목은 발송하지 않는다.
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
    "public_url": "https://example.com/adjustments/raw-token",
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

## 6. 합의서·모두싸인 — C

### 6.1 합의서 생성

`POST /api/v1/contracts/{contract_id}/agreement`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 요청 body: 없음
- 성공: `201 AgreementResponse`
- 오류: `401`, `404`, `409`, `422`

합의서는 현재 확정된 조정 결과로 1~4개 조항을 만든다. 원계약 문서 ID와 검증된
canonical `signed_date`가 없으면 `409 INVALID_STATUS_TRANSITION`으로 거부한다.
합의서는 다음을 포함한다.

- `id`, `version`, `contract_id`
- 제목 `광고대행 계약조건 변경·확인 합의서`
- 원계약 제목·체결일·문서 ID
- 필수 `condition_summary` 네 그룹: 계약기간·총액·결제, 산출물·채널·보고,
  해지·환불·자동갱신, 권리·촬영 안전·시설 파손·손해 책임·초상권·개인정보
- 조항별 분류, 변경 전·후 문구, 사유와 `AGREED`/`KEPT_ORIGINAL` 결과
- `disposition=AGREED/REJECTED/WITHDRAWN`으로 합의·대행사 거절·소유자 철회 구분
- 변경하지 않은 원계약 조건의 유지 방침
- `OWNER`, `AGENCY` 양측 서명란

`condition_summary`는 검증된 원계약 값과 확정 조항으로 결정적으로 만들고, 근거가 없는
조건은 `원계약에서 확인되지 않아 추가 확인 필요`라고 명시하며 임의로 채우지 않는다.
`KEPT_ORIGINAL` 조항은 `REJECTED` 또는 `WITHDRAWN`이고, 대행사 거절이면 비어 있지 않은
`reason`을 보존한다.
생성된 합의서 버전과 `AGREEMENT_CREATED` 감사 이벤트를 하나의 트랜잭션으로 기록한다.

### 6.2 합의서 조회

`GET /api/v1/contracts/{contract_id}/agreement`

- 인증: Bearer
- 담당: C
- 성공: `200 AgreementResponse`
- 오류: `401`, `404`, `422`

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
  "agreement_id": "agreement_uuid",
  "agreement_version": 1,
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
- 서버가 확정 합의서를 메모리에서 PDF로 생성하고 모두싸인
  `POST /embedded-drafts`에 Base64 PDF로 전달
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
현재 합의서를 다시 확인하고 새 `Idempotency-Key`와 `confirmed=true`로 요청해야 한다.

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
`expires_at`은 최초 성공 시각에 `expires_in_hours`를 더해 계산한다. 같은 멱등
요청은 최초 `public_url`과 `expires_at`을 그대로 재생한다. 최초 생성 시
`EVIDENCE_LINK_CREATED` 감사 이벤트를 같은 트랜잭션에 기록한다.

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
- 원본 enum: `DRAFT`, `SCHEDULED`, `ON_PROCESSING`, `ON_GOING`, `COMPLETED`,
  `ABORTED`, `PROCESSING_FAILED`
- 정상 원본 흐름:
  `DRAFT → ON_PROCESSING → ON_GOING → COMPLETED / ABORTED / PROCESSING_FAILED`
- 초안 생성 동안 Contract는 `READY_TO_SIGN`을 유지한다. 인증된 최신 `ON_GOING`은
  Contract `READY_TO_SIGN → SIGNING`, 최신 `COMPLETED`는 `SIGNING → SIGNED`,
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
| C-2 | 계약 생성·목록·상세·타임라인·갱신 의사 | 계약 API 5개, 무부작용 갱신 저장, 정렬 테스트 통과 |
| C-3 | 공개 토큰·멱등 키 기반 | B의 공통 저장 기반으로 hash·scope·만료·동일 요청 재생 테스트 통과 |
| C-4 | 조정 초안·상세·발송 | B의 ReviewItem fixture로 미리보기와 계약당 1회 `/send` |
| C-5 | 대행사 공개 조회·열람 기록·1회 응답 | GET 무변경, `/open` 최초 시각 유지, 전체 항목 정확히 한 번 제출 |
| C-6 | 최종 확정·합의서 생성·조회 | 임의 최종 문구 거부, 원계약 체결일, 합의서 최대 4조항 |
| C-7 | 모두싸인 `mock/live` Adapter와 임베디드 초안 | 합의서 PDF, 서명자 2명, `EDITING`, 민감 URL 비저장 검증 |
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
| Day 4 | `공개 조정 링크·응답(C) → 역제안 비교(B) → 최종 확정·합의서(C)`, 공개 흐름 검증(D) |
| Day 5 | `합의서(C) → 모두싸인 임베디드 편집·사용자 발송·웹훅(C) → 대표 산출물·증빙 승인(B)`, 전체 E2E 실행(D) |
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
