# 안심홍보계약 P0 API·데이터 계약

<!-- markdownlint-configure-file {"MD013": false} -->

이 문서는 백엔드 담당 B와 C가 하나의 FastAPI 프로젝트에서 공유하는 데이터 경계와
불변 규칙을 정리한다. HTTP endpoint와 요청·응답 스키마의 최종 기준은 저장소 루트의
`openapi.yaml`이다. 이번에 확정한 `openapi-final.yaml`을 저장소에 반영할 때는
`openapi.yaml`로 사용한다. 모든 endpoint의 Base path는 `/api/v1`이다.

문서와 코드가 충돌하면 임의로 한쪽에 맞추지 않는다. OpenAPI, Pydantic 스키마,
DB 마이그레이션과 테스트를 같은 변경 단위에서 함께 수정한다.

## 1. 명명과 기본 타입

| 경계 | 규칙 | 예시 |
| --- | --- | --- |
| HTTP JSON | 기본 `snake_case` | `counterparty_name`, `source_page` |
| 공통 envelope 식별자 | `requestId` | `req_123abc` |
| FastAPI·Pydantic | `snake_case` | `termination_notice_date` |
| PostgreSQL | `snake_case` | `adjustment_request_id` |
| 프런트 도메인 모델 | adapter에서만 `camelCase` 변환 가능 | `counterpartyName` |

- 원화 금액은 부동소수점이 아닌 0 이상의 정수 KRW로 주고받는다.
- 계약상 날짜는 `date`, 실행 시각은 timezone-aware UTC `date-time`으로 저장한다.
- 한국 사용자용 D-day는 `Asia/Seoul` 날짜를 기준으로 계산한다.
- 외부 SDK 객체와 ORM 모델을 API 응답으로 직접 반환하지 않는다.

```yaml
type: integer
format: int64
minimum: 0
```

## 2. 공통 응답

성공:

```json
{
  "data": {},
  "error": null,
  "requestId": "req_123abc"
}
```

실패:

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

- 모든 일반 API의 성공·실패 응답에 `requestId`를 포함한다.
- 오류의 `error`에는 OpenAPI에 정의된 `code`, 사용자에게 안전한 `message`만 넣는다.
- 내부 예외, SQL, 계약 전문, 연락처, 토큰, 서명 URL, 외부 응답 전문을 노출하지 않는다.
- 모두싸인 웹훅은 vendor endpoint이므로 공통 envelope 대신 `204 No Content`를 반환한다.

주요 오류 코드:

| 코드 | 의미 |
| --- | --- |
| `DOCUMENT_PARSE_FAILED` | 문서 파싱 실패 |
| `ANALYSIS_SCHEMA_INVALID` | AI 구조화 출력 검증 실패 |
| `ANALYSIS_START_FAILED` | 분석 작업 접수 실패 |
| `ADJUSTMENT_LINK_EXPIRED` | 조정 링크 만료 |
| `OBLIGATION_LINK_EXPIRED` | 산출물 증빙 링크 만료 |
| `INVALID_STATUS_TRANSITION` | 허용되지 않은 상태 전환 또는 중복 제출 |
| `MODUSIGN_REQUEST_FAILED` | 모두싸인 서명 요청 실패 |
| `WEBHOOK_DUPLICATED` | 내부 관측용 중복 웹훅 분류 |
| `WEBHOOK_AUTH_FAILED` | 웹훅 비밀 헤더 검증 실패 |
| `UNAUTHORIZED_ACCESS` | 인증 또는 객체 권한 검증 실패 |
| `IDEMPOTENCY_CONFLICT` | 같은 멱등 키에 다른 요청 사용 |
| `NOT_FOUND` | 리소스를 찾을 수 없음 |
| `VALIDATION_ERROR` | 요청 검증 실패 |

## 3. 인증·권한·공개 토큰

- `/contracts`, `/dashboard` 등 소유자 API는 `Authorization: Bearer <token>`을 사용한다.
- `owner_id`는 요청 body가 아니라 검증된 서버 인증 컨텍스트에서 가져온다.
- 소유자가 아닌 사용자의 객체 접근은 리소스 존재 여부가 노출되지 않도록 처리한다.
- `/public/adjustment-requests/*`는 `ADJUSTMENT_RESPONSE` scope 토큰만 허용한다.
- `/public/obligations/*`는 `OBLIGATION_EVIDENCE` scope 토큰만 허용한다.
- 두 공개 토큰은 서로 교환해 사용할 수 없다.
- 토큰 원문은 생성 응답에서만 반환하고 DB에는 hash, scope, resource ID,
  `expires_at`, `revoked_at`을 저장한다.
- `public_url`은 조정 발송 응답과 증빙 링크 생성 응답에서만 반환한다. 이후 상세·목록
  응답에는 넣지 않는다.
- 동일 멱등 키 재시도에서 최초 생성 응답을 재생하는 경우는 같은 생성 요청의 연장으로
  본다. 일반 조회 API를 통해 토큰 URL을 다시 노출해서는 안 된다.
- 공개 API의 성공·오류 응답과 토큰 생성 응답에는 `Cache-Control: no-store`를 적용한다.

## 4. 멱등성

다음 작업은 `Idempotency-Key: <UUID>` 헤더가 필수다.

- 분석 시작
- 조정 요청 초안 생성
- 조정 링크 활성화
- 합의서 생성
- 모두싸인 서명 요청
- 대표 산출물 생성
- 산출물 증빙 링크 생성

멱등 키는 소유자·operation·resource 범위로 관리한다.

- 같은 키와 같은 요청: 최초 상태 코드와 응답을 재생한다.
- 같은 키와 다른 요청: `409 IDEMPOTENCY_CONFLICT`를 반환한다.
- 서명 요청처럼 외부 부작용이 있는 호출은 외부 문서 ID와 DB 유일성 제약도 함께 사용한다.

## 5. 정렬 규칙

목록 응답은 동일한 데이터에서 항상 같은 순서를 반환한다.

| 응답 | 정렬 |
| --- | --- |
| 계약 목록 | `end_date` 오름차순, null은 마지막, 같은 값은 `id` 오름차순 |
| 계약 타임라인 | `created_at` 오름차순, `id` 오름차순 |
| 이행 항목 목록 | `due_date` 오름차순, `id` 오름차순 |

## 6. 문서·AI 분석 계약

### 6.1 분석 작업

분석 시작 요청은 같은 계약에 속하고 `type=CONTRACT`인 `document_id`를 명시한다.
계약에 실행 중인 분석이 있으면 새 작업을 만들지 않으며, 조회 API는 가장 최근에 생성된
분석 작업 한 건을 반환한다.

`AnalysisTask.status`:

| 상태 | `result` | `error_code` |
| --- | --- | --- |
| `QUEUED` | `null` | `null` |
| `PROCESSING` | `null` | `null` |
| `COMPLETED` | `Analysis` | `null` |
| `FAILED` | `null` | `DOCUMENT_PARSE_FAILED` 또는 `ANALYSIS_SCHEMA_INVALID` |

`attempt_count`는 초기 추출을 1회차로 계산하며 최대 2다. 해결되지 않은 결과는 반복하지
않고 `NEEDS_CHECK`로 종료한다.

### 6.2 원문 근거

모든 `ExtractedTerm`에는 다음 필드를 보존한다.

- `field`
- `value_type`
- `value`
- `source_page`
- `source_text`
- `confidence`
- `verification_status`

`verification_status`:

| 값 | 규칙 |
| --- | --- |
| `VERIFIED` | `value`, `source_page`, `source_text`가 모두 있어야 함 |
| `NOT_FOUND` | `value`, `source_page`, `source_text`가 모두 `null` |
| `MISSING_EVIDENCE` | 결과는 있으나 원문 연결 실패, 확정값 표시 금지 |
| `NEEDS_CHECK` | 모순·낮은 확신도·검증 실패로 사용자 확인 필요 |

### 6.3 추출 필드와 값 타입

| `value_type` | 값 |
| --- | --- |
| `TEXT` | 문자열 |
| `DATE` | ISO 8601 date |
| `MONEY_KRW` | 0 이상의 원화 정수 |
| `INTEGER` | 0 이상의 정수 |
| `PERCENT` | 0~100 정수 |
| `BOOLEAN` | `YES`, `NO`, `UNKNOWN` |

필드와 값 타입은 서버에서 다음처럼 함께 검증한다.

- 날짜: `contract_start_date`, `contract_end_date`, `termination_notice_date`
- 금액: `monthly_amount`, `contract_total_amount`
- 정수: `content_quantity`
- 비율: `termination_penalty_rate`
- Boolean: `auto_renewal`, `early_termination_allowed`
- 나머지 설명·책임·산출물 필드: `TEXT`

### 6.4 검토 항목

- 규칙 기반 결과는 `detection_method=DETERMINISTIC`, `model_confidence=null`이다.
- 모델 기반 또는 혼합 결과만 `model_confidence`를 갖는다.
- 사용자 이해조건은 객관적 증거가 아니라 사용자가 기억하고 이해한 설명으로 분리한다.
- AI가 날짜·금액·D-day·상태 전이를 확정하지 않는다. 계산과 전이는 결정적 코드가 한다.

## 7. 조정·합의 계약

- 조정 요청 초안은 1~4개의 `review_item_id`로 생성한다.
- 초안 응답의 `items`에는 `review_item_id`, `user_choice`, 실제 `request_text`를 포함해
  사용자가 발송 전에 확인할 수 있어야 한다.
- 외부 공개 화면은 내부 UUID 대신 해당 공개 요청에서만 유효한 불투명 `item_id`를 쓴다.
- 대행사 응답은 공개 요청의 모든 항목을 빠짐없이 정확히 한 번씩 제출해야 한다.
- `REJECT`에는 `reason`, `COUNTER`에는 `counter_text`와 `reason`이 필수다.
- 조정 응답 전체는 한 번만 확정하며 DB 유일성 제약과 트랜잭션으로 동시 제출을 막는다.

최종 확정에서 클라이언트가 임의의 합의 문구를 보내지 않는다. 각 항목은 다음 중 하나만
선택한다.

| `resolution` | 허용 조건 |
| --- | --- |
| `ACCEPT_REQUEST` | 대행사가 요청 문구를 수락함 |
| `ACCEPT_COUNTERPROPOSAL` | 대행사가 역제안 문구를 제출함 |
| `KEEP_ORIGINAL` | 기존 조건 유지 |

최종 문구는 서버가 저장된 요청·응답에서 결정한다. 합의서는 확정된 항목만 사용하며 최대
4개 조항으로 생성한다.

## 8. 모두싸인 계약

- 서명 요청에는 확정된 `agreement_id`, `agreement_version`, `confirmed=true`가 필요하다.
- 서명자는 `OWNER` 한 명과 `AGENCY` 한 명으로 정확히 두 명이다.
- 이름은 2~30자다.
- `EMAIL`은 email 형식, `KAKAO`는 하이픈 없는 국내 휴대전화 번호 형식을 사용한다.
- 두 서명자의 역할과 연락처는 중복될 수 없다.
- 연락처 원문은 모두싸인 Adapter 전달에만 사용하고 응답과 로그에 다시 노출하지 않는다.
- 모두싸인 원본 상태 `modusign_status`와 내부 `Signature.status`를 분리한다.

웹훅 처리:

1. 웹훅 등록의 custom headers에 설정한 `X-Modusign-Webhook-Secret`을 검증한다.
2. `event.type`, `document.id`, payload hash로 이벤트를 멱등 저장한다.
3. 즉시 `204 No Content`를 반환한다.
4. 문서 상태 조회와 계약 상태 전이는 응답 이후 비동기로 수행한다.
5. 종료 상태를 오래되거나 순서가 뒤바뀐 이벤트로 되돌리지 않는다.

## 9. 이행 항목·증빙 계약

- P0에서는 계약당 대표 산출물 한 건만 생성한다.
- 대표 산출물 생성 후 별도 endpoint에서 `OBLIGATION_EVIDENCE` scope 제출 링크를 만든다.
- 계약서에 due date 근거가 있으면 그 날짜를 사용하고, 없으면 사용자가 확인해 입력한다.
- 증빙 URL은 길이 2,048 이하의 `http://` 또는 `https://` URL만 허용한다.
- P0에서는 URL 문자열을 증빙으로 저장할 뿐 서버가 URL을 가져오거나 진위를 판정하지 않는다.
- `APPROVED`일 때만 `payment_condition_met=true`다. 이는 실제 지급 승인이나 법적 이행
  판정이 아니다.

## 10. 상태와 감사 이벤트

### 계약

`DRAFT → ANALYZING → REVIEW_REQUIRED → NEGOTIATING → READY_TO_SIGN → SIGNING → SIGNED → IN_PROGRESS → COMPLETED / RENEWAL_DUE`

### 조정 요청

`DRAFT → SENT → OPENED → RESPONDED → CONFIRMED / EXPIRED`

### 내부 서명

`REQUEST_READY → REQUESTING → SIGNING → COMPLETED / ABORTED / FAILED`

### 모두싸인 원본 상태

`ON_PROCESSING → ON_GOING → COMPLETED / ABORTED / PROCESSING_FAILED`

### 이행 항목

`PENDING → SUBMITTED → APPROVED / DISPUTED`

- 프런트나 Adapter가 상태 enum을 직접 대입하지 않는다.
- 상태 전이와 권한 검사는 service/domain 계층에서 수행한다.
- 허용되지 않은 전이는 `INVALID_STATUS_TRANSITION`으로 거부한다.
- 로컬 상태 변경과 `AuditEvent` 추가는 하나의 DB 트랜잭션으로 처리한다.
- 감사 이벤트에는 계약 전문, 연락처, 토큰, 서명 링크를 넣지 않는다.

## 11. B·C 생산·소비 경계

| 담당 | API·데이터 생산 | 주요 소비 |
| --- | --- | --- |
| B — 문서·AI | `Document`, `UnderstoodTerm`, `AnalysisTask`, `ExtractedTerm`, `ReviewItem` | C가 만든 `Contract`, 문서 저장소 인터페이스 |
| C — 계약·모두싸인 | `Contract`, `AuditEvent`, `AdjustmentRequest`, `Agreement`, `Signature`, `Obligation`, `Dashboard` | B가 만든 확정 `ReviewItem`과 비교 결과 |

교차 규칙:

- B가 문서 업로드 endpoint를 담당하지만 실제 Supabase Storage Adapter와 객체 권한 기반은
  C가 제공한다.
- C가 조정 상세 endpoint를 담당하지만 역제안 쉬운 설명이 AI를 사용하면 B의 내부
  비교 서비스를 호출한다.
- `app/core/config.py`, `app/schemas/common.py`, `packages/contracts`,
  `openapi.yaml`, 공통 마이그레이션은 변경 전에 B·C가 합의한다.
- 두 담당자는 별도 백엔드를 만들지 않고 `apps/api` 하나를 함께 사용한다.

## 12. 계약 변경 체크리스트

공개 API, 영속 상태 또는 AI 출력이 바뀌면 다음을 한 변경 단위에서 확인한다.

- [ ] `openapi.yaml`
- [ ] Pydantic 요청·응답 스키마
- [ ] service/domain 상태 전이
- [ ] repository와 새 마이그레이션
- [ ] 공개 토큰 scope·만료·`no-store`
- [ ] API envelope와 오류 코드
- [ ] 단위·통합·API 테스트
- [ ] README와 `.env.example`
- [ ] AI 변경이면 fixture, 프롬프트 버전, `AI_USAGE.md`
