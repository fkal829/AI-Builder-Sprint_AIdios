# 안심홍보계약 API 명세서

<!-- markdownlint-configure-file {"MD013": false} -->

> 버전: `0.2.0`  
> Base URL: `/api/v1`  
> 상세 기계 판독 명세: `packages/contracts/openapi/openapi.yaml`
> 적용 범위: 해커톤 P0

이 문서는 `openapi-final.yaml`을 사람이 읽고 개발 순서를 정할 수 있도록 정리한
백엔드 API 명세다. 필드·enum·응답이 이 문서와 YAML에서 다르면 `packages/contracts/openapi/openapi.yaml`을
우선하고 두 문서를 같은 변경에서 다시 맞춘다.

## 1. 담당 구분

최종 기획안의 역할을 그대로 적용한다.

- **B — 문서·AI:** 문서 업로드, 사용자 이해조건, Upstage 분석, 검토 항목
- **C — 계약·모두싸인:** 계약 생애주기, 조정, 합의서, 모두싸인, 이행, 대시보드

API 개수는 B 5개, C 22개다. B는 endpoint 수는 적지만 Parse·Extract·Solar,
Evaluator Loop와 평가 데이터까지 담당하므로 구현량이 작은 것이 아니다.

### 1.1 전체 API 담당표

| 담당 | Method | Path | 기능 |
| --- | --- | --- | --- |
| C | `GET` | `/health` | 서버 상태 확인 |
| C | `GET` | `/contracts` | 계약 목록·만료 D-day 조회 |
| C | `POST` | `/contracts` | 계약 생성 |
| C | `GET` | `/contracts/{contract_id}` | 계약 상세 조회 |
| C | `GET` | `/contracts/{contract_id}/timeline` | 감사 타임라인 조회 |
| B | `POST` | `/contracts/{contract_id}/documents` | 계약 문서 업로드 |
| B | `PUT` | `/contracts/{contract_id}/understood-terms` | 사용자 이해조건 5문항 저장 |
| B | `POST` | `/contracts/{contract_id}/analysis` | 분석 작업 시작 |
| B | `GET` | `/contracts/{contract_id}/analysis` | 최근 분석 상태·결과 조회 |
| B | `PATCH` | `/contracts/{contract_id}/review-items/{item_id}` | 검토 항목 선택 저장 |
| C | `POST` | `/contracts/{contract_id}/adjustment-requests` | 조정 요청 초안 생성 |
| C | `GET` | `/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}` | 소유자용 조정 상세 조회 |
| C | `POST` | `/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}/send` | 조정 링크 활성화 |
| C | `GET` | `/public/adjustment-requests/{token}` | 대행사용 조정 요청 조회 |
| C | `POST` | `/public/adjustment-requests/{token}/responses` | 대행사 1회 응답 제출 |
| C | `POST` | `/contracts/{contract_id}/adjustment-confirmation` | 최종 조정 결과 확정 |
| C | `POST` | `/contracts/{contract_id}/agreement` | 변경·확인 합의서 생성 |
| C | `GET` | `/contracts/{contract_id}/agreement` | 변경·확인 합의서 조회 |
| C | `POST` | `/contracts/{contract_id}/signature-requests` | 모두싸인 서명 요청 |
| C | `GET` | `/contracts/{contract_id}/signature` | 서명 상태 조회 |
| C | `POST` | `/webhooks/modusign` | 모두싸인 웹훅 수신 |
| C | `GET` | `/contracts/{contract_id}/obligations` | 이행 항목 목록 조회 |
| C | `POST` | `/contracts/{contract_id}/obligations` | 대표 산출물 생성 |
| C | `POST` | `/contracts/{contract_id}/obligations/{obligation_id}/evidence-link` | 증빙 제출 링크 생성 |
| C | `POST` | `/public/obligations/{token}/evidence` | 대행사 증빙 URL 제출 |
| C | `PATCH` | `/contracts/{contract_id}/obligations/{obligation_id}` | 증빙 승인·이의 처리 |
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
- 모두싸인 서명 요청
- 대표 산출물 생성
- 증빙 제출 링크 생성

같은 키와 같은 요청은 최초 결과를 재생한다. 같은 키에 다른 요청을 사용하면
`409 IDEMPOTENCY_CONFLICT`다.

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
| `502` | 모두싸인 요청 실패 |
| `503` | 분석 작업 접수 실패 |

### 2.6 공통 경로 변수

| 이름 | 형식 |
| --- | --- |
| `contract_id` | UUID |
| `item_id` | UUID |
| `adjustment_request_id` | UUID |
| `obligation_id` | UUID |
| `token` | 최소 32자 공개 토큰 |

## 3. 공통·계약 API — C

### 3.1 서버 상태 확인

`GET /api/v1/health`

- 인증: 없음
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

Query:

| 필드 | 필수 | 규칙 |
| --- | --- | --- |
| `renewal_due_within_days` | 아니오 | 1~365 |
| `status` | 아니오 | `ContractStatus` |

목록은 만료일 오름차순, 만료일이 없으면 마지막, 같은 값이면 `id` 오름차순이다.

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

오류: `401`

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

오류: `401`, `422`

### 3.4 계약 상세 조회

`GET /api/v1/contracts/{contract_id}`

- 인증: Bearer
- 담당: C
- 성공: `200 ContractResponse`
- 오류: `401`, `404`

주요 응답 필드:

```json
{
  "id": "contract_uuid",
  "title": "광안리 카페 SNS 광고대행 계약",
  "counterparty_name": "부산홍보대행",
  "status": "REVIEW_REQUIRED",
  "start_date": "2026-08-01",
  "end_date": "2027-07-31",
  "termination_notice_date": "2027-06-30",
  "renewal_type": "AUTO",
  "total_amount": 6000000,
  "modusign_document_id": null,
  "created_at": "2026-07-29T09:00:00Z",
  "updated_at": "2026-07-29T09:10:00Z"
}
```

### 3.5 계약 감사 타임라인 조회

`GET /api/v1/contracts/{contract_id}/timeline`

- 인증: Bearer
- 담당: C
- 성공: `200 TimelineResponse`
- 정렬: `created_at`, `id` 오름차순
- 오류: `401`, `404`

`AuditEvent`는 `id`, `event_type`, `actor_type`, `summary`, `created_at`만 외부에 제공한다.
민감한 내부 payload는 반환하지 않는다.

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
| `file` | binary | 예 | PDF 검증 후 저장 |
| `type` | enum | 예 | `CONTRACT`, `PROPOSAL`, `ESTIMATE`, `MESSAGE` |

P0 분석 대상은 `type=CONTRACT` 문서다. 확장자만 신뢰하지 않고 MIME, magic bytes,
빈 파일, 암호화 여부와 설정된 크기·페이지 제한을 검사한다.

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

### 4.2 사용자 이해조건 저장

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

### 4.3 분석 작업 시작

`POST /api/v1/contracts/{contract_id}/analysis`

- 인증: Bearer
- 담당: B
- 필수 헤더: `Idempotency-Key`
- 성공: `202 AnalysisTaskResponse`
- 오류: `401`, `404`, `409`, `422`, `503`

요청:

```json
{
  "document_id": "document_uuid"
}
```

`document_id`는 같은 계약의 `CONTRACT` 문서여야 한다. 실행 중인 분석이 있으면 중복
작업을 만들지 않는다.

### 4.4 최근 분석 상태·결과 조회

`GET /api/v1/contracts/{contract_id}/analysis`

- 인증: Bearer
- 담당: B
- 성공: `200 AnalysisTaskResponse`
- 반환 기준: 가장 최근에 생성된 분석 작업 한 건
- 오류: `401`, `404`

작업 상태:

| 상태 | `result` | `error_code` |
| --- | --- | --- |
| `QUEUED` | null | null |
| `PROCESSING` | null | null |
| `COMPLETED` | `Analysis` | null |
| `FAILED` | null | `DOCUMENT_PARSE_FAILED` 또는 `ANALYSIS_SCHEMA_INVALID` |

완료 예시:

```json
{
  "data": {
    "id": "analysis_uuid",
    "contract_id": "contract_uuid",
    "document_id": "document_uuid",
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

### 4.5 검토 항목 선택 저장

`PATCH /api/v1/contracts/{contract_id}/review-items/{item_id}`

- 인증: Bearer
- 담당: B
- 성공: `200 ReviewItemResponse`
- 오류: `401`, `404`, `422`

요청:

```json
{
  "user_choice": "REQUEST"
}
```

`user_choice`: `ACCEPT`, `COMPROMISE`, `REQUEST`

AI 재실행은 사용자가 확정한 선택을 덮어쓰지 않는다.

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

- 항목은 중복 없이 1~4개다.
- 응답 `items`에는 `review_item_id`, `user_choice`, 실제 `request_text`가 들어간다.
- 초안에는 `public_url`이 없으며 사용자가 발송 전 문구를 확인한다.

### 5.2 소유자용 조정 상세 조회

`GET /api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}`

- 인증: Bearer
- 담당: C
- 성공: `200 OwnerAdjustmentDetailResponse`
- 오류: `401`, `404`

응답:

- `request`: 실제 요청 문구와 상태
- `responses`: 대행사의 수락·거절·역제안
- `comparisons`: 역제안 변화 요약과 남은 확인사항

endpoint와 저장 책임은 C가 맡고, Solar 기반 비교 문구가 필요하면 B의 내부 비교 서비스를
호출한다.

### 5.3 조정 링크 활성화

`POST /api/v1/contracts/{contract_id}/adjustment-requests/{adjustment_request_id}/send`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 성공: `200 AdjustmentRequestSentResponse`
- 성공 헤더: `Cache-Control: no-store`
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

### 5.4 대행사용 공개 조정 요청 조회

`GET /api/v1/public/adjustment-requests/{token}`

- 인증: Bearer 없음, 조정 scope 공개 토큰 사용
- 담당: C
- 성공: `200 PublicAdjustmentResponse`
- 모든 응답: `Cache-Control: no-store`
- 오류: `404`, `410`

내부 `review_item_id` 대신 토큰 범위에서만 유효한 `item_id`를 반환한다.

### 5.5 대행사 1회 응답 제출

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
- `REJECT`: `reason` 필수
- `COUNTER`: `counter_text`, `reason` 필수
- 공개 요청의 모든 항목을 정확히 한 번씩 제출
- 전체 응답은 한 번만 원자적으로 확정

### 5.6 최종 조정 결과 확정

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
결정한다.

## 6. 합의서·모두싸인 — C

### 6.1 합의서 생성

`POST /api/v1/contracts/{contract_id}/agreement`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 요청 body: 없음
- 성공: `201 AgreementResponse`
- 오류: `401`, `404`, `409`

합의서는 현재 확정된 조정 결과로 최대 4개 조항을 만들며 `id`, `version`을 갖는다.

### 6.2 합의서 조회

`GET /api/v1/contracts/{contract_id}/agreement`

- 인증: Bearer
- 담당: C
- 성공: `200 AgreementResponse`
- 오류: `401`, `404`

### 6.3 모두싸인 서명 요청

`POST /api/v1/contracts/{contract_id}/signature-requests`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 성공: `201 SignatureResponse`
- 오류: `401`, `404`, `409`, `422`, `502`

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
- 연락처 원문을 응답과 로그에 재노출하지 않음

### 6.4 서명 상태 조회

`GET /api/v1/contracts/{contract_id}/signature`

- 인증: Bearer
- 담당: C
- 성공: `200 SignatureResponse`
- 오류: `401`, `404`

내부 상태:

`REQUEST_READY`, `REQUESTING`, `SIGNING`, `COMPLETED`, `ABORTED`, `FAILED`

모두싸인 원본 상태:

`DRAFT`, `SCHEDULED`, `ON_PROCESSING`, `ON_GOING`, `COMPLETED`, `ABORTED`,
`PROCESSING_FAILED`

두 상태는 별도 필드로 저장한다.

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
전이는 응답 이후 비동기로 처리한다. `requester.email`은 인증에 사용하지 않는다.

## 7. 이행 항목·증빙 — C

### 7.1 이행 항목 목록

`GET /api/v1/contracts/{contract_id}/obligations`

- 인증: Bearer
- 담당: C
- 성공: `200 ObligationListResponse`
- 정렬: `due_date`, `id` 오름차순
- 오류: `401`, `404`

### 7.2 대표 산출물 생성

`POST /api/v1/contracts/{contract_id}/obligations`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 성공: `201 ObligationResponse`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "title": "인스타그램 대표 게시물 1건",
  "due_date": "2026-08-15"
}
```

P0에서는 계약당 대표 산출물 한 건만 만든다.

### 7.3 증빙 제출 링크 생성

`POST /api/v1/contracts/{contract_id}/obligations/{obligation_id}/evidence-link`

- 인증: Bearer
- 담당: C
- 필수 헤더: `Idempotency-Key`
- 성공: `201 PublicLinkResponse`
- 성공 헤더: `Cache-Control: no-store`
- 오류: `401`, `404`, `409`, `422`

요청:

```json
{
  "expires_in_hours": 72
}
```

응답의 `scope`는 `OBLIGATION_EVIDENCE`로 고정한다.

### 7.4 대행사 증빙 URL 제출

`POST /api/v1/public/obligations/{token}/evidence`

- 인증: 증빙 scope 공개 토큰
- 담당: C
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
실재 여부를 판정하지 않는다.

### 7.5 증빙 승인·이의 처리

`PATCH /api/v1/contracts/{contract_id}/obligations/{obligation_id}`

- 인증: Bearer
- 담당: C
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
| `signing` | 서명 중 계약 수 |
| `in_progress` | 이행 중 계약 수 |
| `completed` | 완료 계약 수 |
| `expiring_soon` | 만료 임박 계약 수 |
| `unresolved_signals` | 미해결 검토 신호 수 |
| `obligation_pending` | 증빙 대기 수 |
| `obligation_submitted` | 증빙 제출 수 |
| `obligation_approved` | 승인된 증빙 수 |
| `total_committed` | 전체 확정 계약금액 합계, integer KRW |
| `most_common_signal` | 가장 자주 발생한 검토 신호 또는 null |

지급 조건 충족 금액은 배분 규칙이 확정되지 않았으므로 P0 대시보드에서 제공하지 않는다.

## 9. 상태 머신

### 9.1 계약

`DRAFT → ANALYZING → REVIEW_REQUIRED → NEGOTIATING → READY_TO_SIGN → SIGNING → SIGNED → IN_PROGRESS → COMPLETED / RENEWAL_DUE`

### 9.2 조정 요청

`DRAFT → SENT → OPENED → RESPONDED → CONFIRMED / EXPIRED`

### 9.3 분석 작업

`QUEUED → PROCESSING → COMPLETED / FAILED`

### 9.4 이행 항목

`PENDING → SUBMITTED → APPROVED / DISPUTED`

상태를 router, repository, Adapter 또는 웹훅에서 직접 대입하지 않는다. domain/service의
전이 함수가 검증하고 상태 변경과 `AuditEvent`를 하나의 트랜잭션으로 기록한다.

## 10. B 개발 순서

B는 C의 전체 기능이 완성될 때까지 기다리지 않고 `StoragePort`, 계약 상태 서비스와
repository fake를 사용해 먼저 개발한다.

| 순서 | 구현 내용 | 연결 API·완료 조건 |
| --- | --- | --- |
| B-1 | `ExtractedTerm`, `ReviewItem`, `AnalysisTask` Pydantic 스키마와 평가 fixture 작성 | 잘못된 타입·근거 누락이 검증에서 거부됨 |
| B-2 | Upstage `mock/live` Adapter와 Document Parse 정규화 | 샘플 PDF의 페이지·문장이 내부 형식으로 변환됨 |
| B-3 | 문서 검증·업로드 흐름 | `POST /documents`; C의 StoragePort fake로 테스트 통과 |
| B-4 | 사용자 이해조건 5문항 저장 | `PUT /understood-terms`; 계약 근거와 별도 저장 |
| B-5 | Information Extract와 결정적 값 정규화 | 날짜·KRW·비율·Boolean 타입 검증 |
| B-6 | 분석 작업 생성·상태 조회 | `POST/GET /analysis`; 진행·완료·실패 상태 확인 |
| B-7 | 기간·총액·해지·환불 불일치와 누락 검출 | 대표 문제 4종 테스트 통과 |
| B-8 | Solar 쉬운 설명과 수용·절충·요청 3종 문구 | 모든 문구가 원문 근거와 연결됨 |
| B-9 | 최대 2회의 Evaluator Loop | 필요한 필드만 한 번 재추출하고 종료 |
| B-10 | 사용자 검토 선택 저장 | `PATCH /review-items/{item_id}`; AI 재실행 덮어쓰기 방지 |
| B-11 | 역제안 비교 내부 서비스 | C가 `CounterproposalComparator`를 fake 없이 호출 가능 |
| B-12 | 고정 계약 10건 평가와 live 분리 테스트 | 일반 `pytest`가 외부 네트워크 없이 통과 |

## 11. C 개발 순서

C는 B의 분석 결과가 완성될 때까지 기다리지 않고 고정 `ReviewItem` fixture와 가짜
역제안 비교 서비스를 사용한다.

| 순서 | 구현 내용 | 연결 API·완료 조건 |
| --- | --- | --- |
| C-1 | FastAPI 공통 골격, 설정, request ID, 오류 envelope, 인증 컨텍스트 | `GET /health`, `/docs` 정상 |
| C-2 | Supabase DB·Storage Adapter, repository, 마이그레이션 골격 | B가 사용할 StoragePort·Document repository 제공 |
| C-3 | 계약 상태 머신과 감사 이벤트 원자 기록 | 잘못된 전이는 `409`로 거부 |
| C-4 | 계약 생성·목록·상세·타임라인 | 계약 API 4개와 정렬 테스트 통과 |
| C-5 | 공개 토큰·멱등 키 기반 | hash·scope·만료·동일 요청 재생 테스트 통과 |
| C-6 | 조정 초안·상세·발송 | B의 ReviewItem fixture로 미리보기와 `/send` 동작 |
| C-7 | 대행사 공개 조회·1회 응답 | 전체 항목 정확히 한 번 제출, 동시 중복 방지 |
| C-8 | 최종 확정·합의서 생성·조회 | 임의 최종 문구 거부, 합의서 최대 4조항 |
| C-9 | 모두싸인 `mock/live` Adapter와 서명 요청 | 합의서 ID·버전, 서명자 2명, 멱등 요청 검증 |
| C-10 | 웹훅 인증·중복·순서 역전 처리 | 즉시 204, 종료 상태 회귀 방지 |
| C-11 | 대표 산출물·증빙 링크·제출·검토 | 계약당 1건, 별도 scope, HTTP(S) URL만 허용 |
| C-12 | D-day·대시보드·타임라인 집계 | 한국 날짜 경계와 정렬 테스트 통과 |
| C-13 | 전체 동시성·통합 테스트 | 공개 제출·서명·웹훅 멱등성 검증 |

## 12. B·C 교차 의존성

| 제공자 | 제공 내용 | 소비자 |
| --- | --- | --- |
| C | 계약 생성·소유자 권한·StoragePort | B 문서 업로드 |
| C | 계약 상태 전이 함수 | B 분석 시작·완료·실패 |
| B | 완료된 `ReviewItem`과 실제 3종 문구 | C 조정 초안 |
| B | `CounterproposalComparator` | C 소유자 조정 상세 |
| B | 검증된 추출 날짜·금액 후보 | C 계약 canonical 값과 대시보드 |
| C | 대행사 응답 원본 | B 역제안 비교 |

중요 규칙:

- B가 계약 상태 enum을 DB에 직접 대입하지 않는다.
- C가 AI 추출값을 검증 없이 계약 확정값에 덮어쓰지 않는다.
- C는 대행사 응답을 먼저 저장한 후 B 비교 서비스를 호출한다. 비교 실패로 응답 원본을
  잃으면 안 된다.
- B·C는 별도 백엔드를 만들지 않고 `apps/api` 하나를 사용한다.
- 공통 파일 변경 전 API·스키마를 먼저 합의하고 작은 PR로 통합한다.

## 13. 병렬 개발 체크포인트

| 시점 | 반드시 연결해 볼 흐름 |
| --- | --- |
| Day 1 | 단일 서버, `/docs`, `/health`, DB 연결, Upstage Parse와 모두싸인 QuickStart smoke test |
| Day 2 | `계약 생성(C) → 문서 업로드(B) → 5문항(B) → 분석 시작·조회(B)` |
| Day 3 | `ReviewItem 생성·선택(B) → 조정 초안(C)` |
| Day 4 | `공개 링크·응답(C) → 역제안 비교(B) → 최종 확정·합의서(C)` |
| Day 5 | `합의서 → 모두싸인 요청 → 웹훅 완료 → 대표 산출물 → 증빙 승인` |
| Day 6 | 계약 목록·D-day·대시보드·타임라인과 전체 P0 E2E |
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
