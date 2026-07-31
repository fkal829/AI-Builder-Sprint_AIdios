# 단디계약 P0 및 6.14 P2-0 API·데이터 계약

<!-- markdownlint-configure-file {"MD013": false} -->

이 문서는 백엔드를 구현하는 B·C와 배포·E2E를 검증하는 D가 공유하는 데이터 경계와
불변 규칙을 정리한다. 1~13절의 P0 제품 범위와 사용자 흐름은 `docs/기획안.md`,
14절의 광고효과 P2-0 범위는 `docs/단디계약최종기획안.md` 6.14를 제품 기준으로 삼는다.
HTTP endpoint와 요청·응답 스키마의
기준은 `packages/contracts/openapi/openapi.yaml`이다. 모든 endpoint의 Base path는
`/api/v1`이다. 이 문서의 파일 경로 표기는 모두 저장소 루트 기준이다.

1~13절은 현재 P0 구현 계약이고 14절은 기획안 6.14의 P2-0 확정 설계다. 14절의
runtime과 migration은 아직 구현되지 않았으며, 설계가 문서에 반영됐다는 사실을 구현
완료로 해석하지 않는다.

기획안의 제품 기능과 P0 범위는 유지하되, 구현 담당만 최신 팀 결정에 따라 D의 백엔드
항목을 B·C로 재배정한다.

문서와 코드가 충돌하면 변경 범위에 해당하는 위 제품 기준을 먼저 적용하고 임의로 기능을
넓히지 않는다. 그 범위 안에서 OpenAPI, 이 문서, `docs/api-명세서.md`, Pydantic
스키마, DB 마이그레이션과 테스트를 같은 변경 단위에서 함께 수정한다.

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
| `MODUSIGN_REQUEST_FAILED` | 모두싸인 임베디드 초안 또는 후속 문서 처리 실패 |
| `WEBHOOK_AUTH_FAILED` | 웹훅 비밀 헤더 검증 실패 |
| `UNAUTHORIZED_ACCESS` | 인증 또는 객체 권한 검증 실패 |
| `IDEMPOTENCY_CONFLICT` | 같은 멱등 키에 다른 요청 사용 |
| `NOT_FOUND` | 리소스를 찾을 수 없음 |
| `VALIDATION_ERROR` | 요청 검증 실패 |

## 3. 인증·권한·공개 토큰

- `/contracts`, `/dashboard` 등 소유자 API는 `Authorization: Bearer <token>`을 사용한다.
- `owner_id`는 요청 body가 아니라 검증된 서버 인증 컨텍스트에서 가져온다.
- 소유자가 아닌 사용자의 객체 접근은 리소스 존재 여부가 노출되지 않도록 처리한다.
- `Document.file_url`과 Storage 경로는 private 영속 데이터이며 일반 `Document`
  응답에 노출하지 않는다. 원문 근거 클릭은 계약·문서 소유권 확인 후 최대 5분 유효한
  `access_url`과 요청한 `source_page`를 반환하는 전용 endpoint를 사용하고
  `Cache-Control: no-store`를 적용한다. `source_page`는 1-based이며 해당 문서의
  `page_count`를 초과하면 접근 URL을 발급하지 않고 `422 VALIDATION_ERROR`로 거부한다.
- `/public/adjustment-requests/*`는 `ADJUSTMENT_RESPONSE` scope 토큰만 허용한다.
- `/public/obligations/*`는 `OBLIGATION_EVIDENCE` scope 토큰만 허용한다.
- 두 공개 토큰은 서로 교환해 사용할 수 없다.
- 소유자 API의 UUID path 변수가 문법적으로 잘못되면 `422 VALIDATION_ERROR`를
  반환한다. 공개 토큰은 열거 방지를 우선해 형식·길이·scope·대상 불일치를 모두
  `404 NOT_FOUND`로 처리하고, 유효하지만 만료된 토큰만 `410`으로 처리한다.
  scope 불일치는 내부 telemetry에서만 구분하고 공개 `ApiError.code`로 노출하지 않는다.
- 토큰 원문은 생성 응답에서만 반환하고 DB에는 hash, scope, resource ID,
  `expires_at`, `revoked_at`을 저장한다.
- `public_url`은 조정 발송 응답과 증빙 링크 생성 응답에서만 반환한다. 이후 상세·목록
  응답에는 넣지 않는다.
- 증빙 링크의 `expires_at`은 `/evidence-link` 최초 성공 시각에
  `expires_in_hours`를 더해 계산한다.
- 동일 멱등 키 재시도에서 최초 생성 응답을 재생하는 경우는 같은 생성 요청의 연장으로
  보고 최초 URL과 `expires_at`을 유지한다. 일반 조회 API를 통해 토큰 URL을 다시
  노출해서는 안 된다.
- 공개 API의 성공·오류 응답과 토큰 생성 응답에는 `Cache-Control: no-store`를 적용한다.

문서 업로드는 기본적으로 파일당 20 MiB, PDF 100페이지로 제한한다. 선언 MIME과 magic
bytes를 함께 검증하고 빈 파일·손상된 PDF·암호화 PDF는 저장하지 않는다. 원본 파일명은
Storage 경로에 사용하지 않으며 owner·contract·document UUID로 서버가 경로를 만든다.
`SUPABASE_MODE=mock`의 고정 데모 인증은 로컬 전용이며 production에서는 사용할 수 없다.

## 4. 멱등성

다음 작업은 `Idempotency-Key: <UUID>` 헤더가 필수다.

- 분석 시작
- 조정 요청 초안 생성
- 조정 링크 활성화
- 수정 계약서 대조 생성·최종 확인
- 모두싸인 임베디드 서명 초안 생성
- 산출물 증빙 링크 생성

멱등 키는 소유자·operation·resource 범위로 관리한다.

- 같은 키와 같은 요청: 최초 상태 코드와 응답을 재생한다.
- 같은 키와 다른 요청: `409 IDEMPOTENCY_CONFLICT`를 반환한다.
- 임베디드 초안 생성 응답의 `editor_url`은 민감한 단기 URL이라 멱등 응답에 저장하지
  않는다. 같은 키의 재호출은 URL을 재생·재발급하지 않고 `409`를 반환한다.
- 외부 부작용이 있는 호출은 `modusign_draft_id`·외부 문서 ID와 DB 유일성 제약도
  함께 사용한다.

## 5. 정렬 규칙

목록 응답은 동일한 데이터에서 항상 같은 순서를 반환한다.

| 응답 | 정렬 |
| --- | --- |
| 계약 목록 | `end_date` 오름차순, null은 마지막, 같은 값은 `id` 오름차순 |
| 계약 타임라인 | `created_at` 오름차순, `id` 오름차순 |
| 이행 항목 목록 | `due_date` 오름차순, `id` 오름차순 |

## 6. 문서·AI 분석 계약

### 6.1 분석 작업

분석 시작 요청은 같은 계약에 속한 최신 `type=CONTRACT` 문서의 `document_id`를 명시한다.
계약에 실행 중인 분석이 있으면 새 작업을 만들지 않으며, 조회 API는 가장 최근에 생성된
분석 작업 한 건을 반환한다.

`AnalysisTask.status`:

| 상태 | `result` | `error_code` |
| --- | --- | --- |
| `QUEUED` | `null` | `null` |
| `PROCESSING` | `null` | `null` |
| `COMPLETED` | `Analysis` | `null` |
| `FAILED` | `null` | `DOCUMENT_PARSE_FAILED` 또는 `ANALYSIS_SCHEMA_INVALID` |

`attempt_count`는 아직 추출을 시작하지 않은 `QUEUED` 작업만 0일 수 있다. 초기
추출을 1회차로 계산하고 `PROCESSING`, `COMPLETED`, `FAILED` 작업은 1~2이며 최대
2다. 해결되지 않은 결과는 반복하지 않고 `NEEDS_CHECK`로 종료한다.

작업이 `FAILED`로 끝나면 계약은 `ANALYZING`을 유지하고 `ANALYSIS_FAILED`
`AuditEvent`를 기록한다. 실행 중 작업이 없을 때 사용자가 새 `Idempotency-Key`로
수동 재시작할 수 있으며, 같은 계약의 최신 `CONTRACT` 문서 또는 사용자가 새로 업로드한
최신 문서를 명시한다. 새 `AnalysisTask=QUEUED`와 `ANALYSIS_RESTARTED` 이벤트를 만들고
각 작업의 Evaluator Loop는 다시 최대 2회로 제한한다. 기존 멱등 키 재호출은 최초 HTTP
결과(보통 `202` 접수, 접수 자체 실패 시 `503`)를 재생할 뿐 새 작업을 만들지 않는다.
비동기 `FAILED` 상태는 조회 API에서 확인하며 자동 무한 재시도는 하지 않는다.
내구성 worker는 짧은 cutoff보다 오래된 `QUEUED`만 다시 처리하며, `PROCESSING`은
별도 처리 timeout(기본 14,400초)을 넘긴 경우에만 실패로 마감한다. 해당 행을
잠그고 `status=PROCESSING` 및 `updated_at <= cutoff`를 재검증한 뒤
`FAILED/DOCUMENT_PARSE_FAILED`, 주 계약 문서와 선택 자료 `parse_status=FAILED`,
`ANALYSIS_FAILED` 감사 이벤트를 한 트랜잭션에 기록한다. 계약은 `ANALYZING`을
유지하므로 위 수동 재시작 규칙을 그대로 사용한다.

### 6.2 원문 근거

모든 `ExtractedTerm`에는 다음 필드를 보존한다.

- `id`
- `contract_id`
- `document_id`
- `source_type`
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
| `MISSING_EVIDENCE` | `value`는 있으나 `source_page`, `source_text`가 모두 `null`; 확정값 표시 금지 |
| `NEEDS_CHECK` | `source_page`, `source_text`는 모두 있고 모순·낮은 확신도·검증 실패로 사용자 확인 필요 |

`ExtractedTerm.source_page`와 `source_text`는 항상 함께 존재하거나 함께 `null`이어야
한다. `ReviewItem`에서는 `source_document_id`, `source_page`, `source_text`,
`source_confidence` 네 필드가 항상 함께 존재하거나 함께 `null`이어야 한다.

`source_type`은 `CONTRACT` 문서의 추출값이면 `CONTRACT_DOCUMENT`, 같은 계약의
`PROPOSAL`, `ESTIMATE`, `MESSAGE` 선택 자료이면 `DOCUMENTED_EXPLANATION`이다.
페이지 개념이 없는 이미지·text `MESSAGE`는 단일 가상 페이지 `source_page=1`로
정규화한다.

Upstage live 모드는 Universal Extraction의 1-based `page`와 정규화 location 좌표를
같은 요청의 Document Parse 요소 좌표에 연결한다. 좌표가 겹친 요소의 원문만
`source_text`로 인정하며 연결되지 않은 값은 `MISSING_EVIDENCE`다. Upstage가 반환하는
confidence 범주 `high`, `low`는 number 저장 계약을 위해 각각 `0.9`, `0.4`로
정규화한다. `low`는 근거를 보존하되 `NEEDS_CHECK`로 분류한다. 이 값은 별도 보정된
확률이나 검토 판단의 `model_confidence`가 아니다.

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

- 날짜: `contract_signed_date`, `contract_start_date`, `contract_end_date`,
  `termination_notice_date`, `deliverable_due_date`
- 금액: `monthly_amount`, `contract_total_amount`
- 정수: `content_quantity`
- 비율: `termination_penalty_rate`
- Boolean: `auto_renewal`, `early_termination_allowed`
- 나머지 설명·책임·산출물 필드: `TEXT`

non-null `TEXT` 값은 빈 문자열일 수 없다. `contract_renewal_type`도 `TEXT`이며 값은
`AUTO`, `MANUAL`, `NONE`, `UNKNOWN` 중 하나다. `auto_renewal=YES`이면
`contract_renewal_type=AUTO`로 정규화하고, `NO`만으로는 `MANUAL`과 `NONE`을
추정하지 않는다. 원문에 갱신 방식이 명확할 때만 해당 값으로 검증하며 불명확하면
`UNKNOWN`과 `NEEDS_CHECK`를 사용한다. Boolean `UNKNOWN`도 `NEEDS_CHECK`여야 하며
`VERIFIED`로 승격할 수 없다.

기획안의 결합 표현을 축소하지 않도록 `advertising_account_ownership`과
`content_ownership`, `shooting_safety`와 `facility_damage_liability`,
`portrait_rights`와 `personal_information_handling`을 각각 별도의 `TEXT` 필드로
추출한다.

### 6.4 검토 항목

- 모든 `ReviewItem`은 `id`, `contract_id`와 근거 상태를 가진다.
- 조항 카드의 기준은 `basis_type=OFFICIAL_SOURCE` 또는 `INTERNAL_RULE`로 구분하고
  비어 있지 않은 `basis_text`를 원문·사용자 이해·제안 문구와 분리해 반환한다.
  공식 기준이면 `basis_citation`에 기관·문서명과 nullable URL·버전·시행일을 보존하고,
  내부 확인 규칙이면 `basis_citation=null`이다. 출처 없는 규칙을 공식 기준으로
  표시하지 않는다.
- `source_document_id`, `source_page`, `source_text`, `source_confidence`는 모두 함께
  존재하거나 함께 `null`이다. `related_extracted_term_ids`에는 계약 원문과 선택 자료
  비교에 사용한 1~11개 `ExtractedTerm` ID를 연결한다. `source_*`는 그중 기본 계약
  원문 근거 한 건을 가리키며 `source_document_id`는 해당
  `ExtractedTerm.document_id`, `source_confidence`는 해당
  `ExtractedTerm.confidence`와 같아야 한다.
- `UNREVIEWED`의 `user_choice`는 `null`이고 `SELECTED`, `SENT`, `RESOLVED`,
  `KEPT_ORIGINAL`에서는 `ACCEPT`, `COMPROMISE`, `REQUEST` 중 하나를 보존한다.
- 선택 PATCH는 `UNREVIEWED`, `SELECTED`에서만 허용한다. 조정 요청이 발송되어
  `SENT` 이상이 된 항목은 발송 스냅샷과 달라지지 않도록
  `409 INVALID_STATUS_TRANSITION`으로 거부한다.
- `ACCEPT` 선택은 원안 수용이므로 즉시 `RESOLVED`, `COMPROMISE`·`REQUEST`는
  `SELECTED`로 바꾼다. 조정 초안에는 `SELECTED`이면서 선택값이 `COMPROMISE` 또는
  `REQUEST`인 항목만 넣을 수 있고, `/send` 트랜잭션에서 포함 항목을 `SENT`로 동결한다.
- 규칙 기반 결과는 `detection_method=DETERMINISTIC`, `model_confidence=null`이다.
- 규칙 기반 결과의 `model_limitations`도 `null`이다. 모델 기반 또는 혼합 결과는
  `model_confidence`와 비어 있지 않은 `model_limitations`를 함께 반환해 조항 카드에
  확신도와 한계를 분리 표시한다.
- Solar Chat은 보정된 confidence를 별도로 제공하지 않는다. Solar 검토 문구가 포함된
  `HYBRID` 결과의 `model_confidence`는 제공된 입력을 반영했다는 비보정
  자기평가값이며, 이 의미와 한계를 `model_limitations`에 함께 표시한다.
- `VERIFIED`와 `NEEDS_CHECK`는 `source_document_id`, `source_page`, `source_text`,
  `source_confidence`가 모두 필요하고 `NOT_FOUND`, `MISSING_EVIDENCE`에서는 네 필드가
  모두 `null`이다. `source_confidence`는 원문 추출 근거의 확신도이며 검토 판단의
  `model_confidence`와 의미가 다르다.
- 사용자 이해조건은 객관적 증거가 아니라 사용자가 기억하고 이해한 설명으로 분리하며
  `UnderstoodTerm.source_type`은 항상 `USER_MEMORY`다.
- 이해조건 요청에는 `contract_id`를 받지 않고 경로와 소유권 컨텍스트에서 정한다.
  저장된 `UnderstoodTerm` 응답에는 서버가 정한 `contract_id`를 포함한다.
- `UnderstoodTerm`은 계약당 한 행이며 PUT은 다섯 조건 전체를 교체한다.
  `monthly_amount`, `total_amount`는 필수 nullable 필드로서 기억하지 못하면 `null`이며
  사용자 답변끼리 계산하거나 보정하지 않는다. 값이 실제로 바뀐 저장만
  `UNDERSTOOD_TERMS_SAVED` 감사 이벤트를 같은 트랜잭션에 기록하고 동일 PUT 재시도는
  이벤트를 중복 생성하지 않는다.
- 계약 상세의 필수 nullable `understood_term`은 5문항 저장 전에는 `null`, 저장 후에는
  같은 `UnderstoodTerm`을 반환한다. 조항 카드는 이를 재조회해 `내가 이해한 조건`을
  별도로 표시한다.
- AI가 날짜·금액·D-day·상태 전이를 확정하지 않는다. 계산과 전이는 결정적 코드가 한다.

### 6.5 canonical 값 승격

분석 요청은 주 계약 `document_id`와 같은 계약의 선택
`supporting_document_ids` 배열을 받는다. 선택 자료에서 얻은
`DOCUMENTED_EXPLANATION` 값은 비교·표시에만 사용하고 canonical 값이나 대표 의무로
승격하지 않는다. `AnalysisTask`는 실패한 경우에도 사용한 두 문서 ID 집합을 보존한다.

같은 `field`의 계약 원문과 선택 자료 값은 서버가 `value_type`에 따라 결정적으로
비교한다. 날짜는 ISO date, 금액·정수·비율은 정수, Boolean·갱신 유형은 enum,
일반 TEXT는 공백·대소문자를 정규화한다. 계약과 모든 선택 자료의 근거가
`VERIFIED`이고 선택 자료끼리 같은 값일 때만 `MISMATCH`를 확정한다. 선택 자료끼리
충돌하거나 어느 한쪽 근거가 미검증이면 `NEEDS_CHECK`, 계약 원문이 `NOT_FOUND`이고
선택 자료에 검증된 설명이 있으면 `NO_BASIS`로 둔다. 선택 자료의 `NOT_FOUND`만으로는
비교 신호를 추가하지 않는다. 비교 항목의 `related_extracted_term_ids`는 계약 원문을
먼저 두고 요청된 선택 자료 순서를 유지한다.

분석 완료 시 같은 계약의 최신 `CONTRACT` 문서에서 나온 후보 중 다음 조건을 모두 만족한
값만 비어 있는 `Contract.signed_date`, `start_date`, `end_date`,
`termination_notice_date`, `renewal_type`, `total_amount`에 승격한다.

- `verification_status=VERIFIED`
- 추출 필드와 `value_type`이 일치
- 날짜와 정수 KRW가 서버 규칙으로 정규화됨
- 같은 필드 후보가 하나이고 서로 모순되지 않음

기존 canonical 값이 non-null이면 AI 결과로 덮어쓰지 않는다. 값이 다르면 확인용
`ReviewItem`을 만든다. `NOT_FOUND`, `MISSING_EVIDENCE`, `NEEDS_CHECK`는 승격하지
않는다. canonical 승격, 근거가 있을 때의 대표 `Obligation` 자동 생성,
`AnalysisTask=COMPLETED`, `AuditEvent` 기록은 한 트랜잭션으로 처리하고 원본
`ExtractedTerm.id`와 분석 버전을 추적한다.

## 7. 조정·수정 계약서 대조

- 조정 요청 초안은 1~4개의 `review_item_id`로 생성한다.
- 초안 항목은 모두 `ReviewItem.status=SELECTED`이고 `user_choice`가 `COMPROMISE`
  또는 `REQUEST`여야 한다. 원안 수용인 `ACCEPT` 항목은 외부 요청으로 발송하지 않는다.
- 초안 응답의 `items`에는 `review_item_id`, `user_choice`, 실제 `request_text`를 포함해
  사용자가 발송 전에 확인할 수 있어야 한다.
- 초안은 `expires_in_hours` 정책값만 가지며 `sent_at`, `expires_at`은 `null`이다.
  사용자가 `confirmed=true`로 `/send`를 호출하면 성공 시각을 `sent_at`으로 기록하고
  `expires_at = sent_at + expires_in_hours`로 계산한다.
- P0에서는 계약당 실제 발송·응답 라운드를 한 번만 허용한다. 이미 발송한 조정 요청이
  있으면 다른 초안의 `/send`를 `INVALID_STATUS_TRANSITION`으로 거부한다.
- 외부 공개 화면은 내부 UUID 대신 해당 공개 요청에서만 유효한 불투명 `item_id`를 쓴다.
- 공개 조회 성공 응답의 상태는 `SENT`, `OPENED`, `RESPONDED`, `CONFIRMED`만
  허용한다. `DRAFT`에는 공개 토큰이 없고 유효한 토큰의 `EXPIRED`는 `410`으로 처리한다.
- 공개 `GET`은 데이터를 조회할 뿐 상태를 바꾸지 않는다. 공개 화면이 실제로 열린 시각은
  `POST /public/adjustment-requests/{token}/open`에서 `SENT → OPENED`로 기록하며
  이미 `OPENED` 이후라면 같은 결과를 반환하는 멱등 동작으로 처리한다.
- `/open` 기록 없이 `SENT`에서 응답이 직접 제출되면 응답 트랜잭션에서
  `opened_at=responded_at`을 함께 기록해 열람 사실을 보존한다.
- 대행사 응답은 공개 요청의 모든 항목을 빠짐없이 정확히 한 번씩 제출해야 한다.
- `ACCEPT`는 `counter_text`, `reason`이 모두 `null`, `REJECT`는
  `counter_text=null`과 비어 있지 않은 `reason`, `COUNTER`는 비어 있지 않은
  `counter_text`와 `reason`이 필수다.
- 조정 응답 전체는 한 번만 확정하며 DB 유일성 제약과 트랜잭션으로 동시 제출을 막는다.

최종 확정에서 클라이언트가 임의의 합의 문구를 보내지 않는다. 각 항목은 다음 중 하나만
선택한다.

| `resolution` | 허용 조건 |
| --- | --- |
| `ACCEPT_REQUEST` | 대행사가 요청 문구를 수락함 |
| `ACCEPT_COUNTERPROPOSAL` | 대행사가 역제안 문구를 제출함 |
| `KEEP_ORIGINAL` | 기존 조건 유지 |

최종 문구는 서버가 저장된 요청·응답에서 결정한다. `ACCEPT_REQUEST`와
`ACCEPT_COUNTERPROPOSAL`은 관련 `ReviewItem`을 `SENT → RESOLVED`,
`KEEP_ORIGINAL`은 `SENT → KEPT_ORIGINAL`로 바꾼다. 항목 상태, 최종 문구와
`ADJUSTMENT_CONFIRMED` 감사 이벤트는 하나의 트랜잭션으로 기록한다. 이 시점의 Contract는
`NEGOTIATING`을 유지하며 서명 가능한 상태가 아니다.

대행사가 기존 채널로 보낸 수정본은 `Document.type=REVISED_CONTRACT` PDF로 업로드한다.
최신 수정본만 대조할 수 있으며 확정 조항 1~4개 각각에 `expected_text`, `match_status`,
`source_page`, `source_text`, `confidence`를 보존한다. 정규화한 정확 문구를 찾은 경우만
`MATCHED`와 결정적 `confidence=1.0`으로 표시한다. 찾지 못했거나 표현이 다르면
`NEEDS_CONFIRMATION`으로 두고 AI 또는 문자열 유사도만으로 합의 반영을 확정하지 않는다.

소유자는 최신 대조의 모든 `review_item_id`를 빠짐없이 명시적으로 확인해야 한다. 확인은
`RevisedContractReview=CONFIRMED`, 항목 `owner_confirmed=true`, Contract
`NEGOTIATING → READY_TO_SIGN`, `REVISED_CONTRACT_CONFIRMED`를 하나의 트랜잭션으로
기록한다. 새 수정본 업로드·대조는 이전 검토를 삭제하지 않으며 서명은 최신 CONFIRMED
대조의 문서 ID와 SHA-256에만 묶인다. 기존 합의서 생성 API와 테이블은 이력 호환을 위해
남기지만 새 P0 정상 경로에서는 사용하지 않는다.

## 8. 모두싸인 계약

> **C-7 변경(2026-07-31):** 템플릿 기반 즉시 발송을 제거하고
> `POST /contracts/{contract_id}/signature-embedded-drafts` 임베디드 초안 생성으로
> 대체했다. 초안 API는 외부 서명 요청을 발송하지 않으며 사용자가 모두싸인 편집기에서
> 서명란을 배치하고 직접 발송한다.

- 임베디드 초안 생성에는 최신 확정 `revised_contract_review_id`와 `confirmed=true`가
  필요하다.
- 서명자는 `OWNER` 한 명과 `AGENCY` 한 명으로 정확히 두 명이다.
- 이름은 2~30자다.
- `EMAIL`은 email 형식, `KAKAO`는 하이픈 없는 국내 휴대전화 번호 형식을 사용한다.
- 두 서명자의 역할과 연락처는 중복될 수 없다.
- 연락처 원문은 모두싸인 Adapter 전달에만 사용하고 API 응답·DB·로그에 저장하지 않는다.
- 서버는 대조에서 확정된 수정 계약서 PDF를 private Storage에서 읽고 SHA-256을 검증한 뒤,
  모두싸인 `POST /embedded-drafts`의 `file.base64`, `file.extension=pdf`로 전달한다.
  PDF를 다시 렌더링하지 않으며 계약서 원문을 로컬 임시 파일이나 로그에 남기지 않는다.
- 응답은 `signature`, `editor_url`, `expires_at`을 가진다. `editor_url`은 약 2시간
  유효한 민감 URL이며 `Cache-Control: no-store`로 한 번만 반환하고 DB·로그·멱등
  재생값에 저장하지 않는다.
- 임베디드 초안 생성 직후 내부 상태는 `EDITING`, 원본 상태는 `DRAFT`이고
  `modusign_draft_id`를 저장한다. `modusign_document_id`와 `last_event_id`는 아직
  `null`이며 Contract는 `READY_TO_SIGN`을 유지한다.
- 사용자가 임베디드 편집기에서 직접 발송한 뒤 인증된 모두싸인 이벤트·최신 조회 결과로
  외부 문서 ID를 연결하고 Contract `READY_TO_SIGN → SIGNING`을 처리한다.
- 모두싸인 원본 상태 `modusign_status`와 내부 `Signature.status`를 분리한다.
- 원본 상태 enum은 `DRAFT`, `SCHEDULED`, `ON_PROCESSING`, `ON_GOING`,
  `COMPLETED`, `ABORTED`, `PROCESSING_FAILED`를 보존한다. 임베디드 P0 흐름은
  `DRAFT → ON_PROCESSING → ON_GOING → COMPLETED / ABORTED /
  PROCESSING_FAILED`다.
- `Signature`는 내부 `id`와 마지막으로 반영한 웹훅 `last_event_id`를 보존한다.
  실제 payload에서 안정적인 vendor 이벤트 ID를 Adapter가 검증할 수 있으면 사용하고,
  없으면 `event.type + document.id + canonical payload hash` fingerprint를 사용한다.
- 내부 `SIGNING`은 원본 `ON_GOING`, 외부 문서 ID, 마지막 이벤트와 요청 시각이
  필요하다. 내부 `COMPLETED`는 원본 `COMPLETED`, 외부 문서 ID, 마지막 이벤트,
  요청·완료 시각을 모두 보존한다. `ABORTED`도 원본 `ABORTED`와 같은 추적 필드를
  보존한다.
- `REQUESTING`은 외부 초안 생성 호출 중인 내부 상태이며 원본 상태·초안 ID·문서 ID·
  이벤트 ID가 모두 `null`이다. `EDITING`은 원본 `DRAFT`, 초안 ID, 요청 시각을
  보존하고 문서 ID·이벤트 ID·완료 시각은 `null`이다.
- `FAILED`는 외부 문서 생성 전 로컬 실패이면 외부 상태·초안 ID·문서 ID·이벤트 ID가
  모두 `null`, 외부 처리
  실패이면 `modusign_status=PROCESSING_FAILED`와 문서·이벤트 ID를 모두 가진다.
  두 경우 모두 요청·완료 시각을 보존하며 `COMPLETED`, `ABORTED`, `ON_GOING`을
  `FAILED`와 조합하지 않는다.
- PDF 또는 외부 초안 생성 실패는 `Signature=FAILED`로 보존하고 계약은
  `READY_TO_SIGN`을 유지한다. 인증 후 최신 원본 상태가 `ABORTED` 또는
  `PROCESSING_FAILED`이면 계약을 `SIGNING → READY_TO_SIGN`으로 되돌리고 각각
  `SIGNATURE_ABORTED`, `SIGNATURE_FAILED`를 기록한다. 실패·중단 시도를 자동 재요청하지
  않으며 사용자가 현재 수정 계약서를 다시 확인하고 새 `Idempotency-Key`와
  `confirmed=true`로 요청해야 한다.
- 재요청은 새 `Signature` 시도를 만들고 이전 terminal 레코드와 외부 초안·문서 ID를
  보존한다. 단일 서명 조회는 가장 최근 시도를 반환한다. 같은 멱등 키 재생이나 활성
  시도가 있는 동안에는 새 외부 초안을 만들지 않는다.

웹훅 처리:

1. 웹훅 등록의 custom headers에 설정한 `X-Modusign-Webhook-Secret`을 검증한다.
2. 검증된 vendor 이벤트 ID 또는 `event.type`, `document.id`, canonical payload
   hash fingerprint로 이벤트를 멱등 저장한다.
3. 즉시 `204 No Content`를 반환한다.
4. 문서 상태 조회와 계약 상태 전이는 응답 이후 비동기로 수행한다.
5. 임베디드 초안에는 내부 Signature ID와 서버 secret으로 만든 HMAC 증명 metadata를 넣고,
   상태 조회 응답의 metadata를 검증해 해당 Signature에만 외부 문서 ID를 연결한다.
6. 종료 상태를 오래되거나 순서가 뒤바뀐 이벤트로 되돌리지 않는다. `COMPLETED`가
   `ON_GOING`보다 먼저 관측되면 최신 조회 상태를 우선하여
   `EDITING/READY_TO_SIGN → COMPLETED/SIGNED`를 한 트랜잭션으로 보정한다.

기획안의 `WEBHOOK_DUPLICATED`는 중복 수신을 위한 내부 관측·테스트 분류다. 공개
`ApiError.code`에는 포함하지 않으며 vendor 수신 endpoint는 공통 오류 envelope 대신
중복 요청에도 `204 No Content`를 반환한다.

## 9. 이행 항목·증빙 계약

- 분석이 `COMPLETED`될 때 제목 구성 필드와 `deliverable_due_date`가 같은 원문
  근거에서 명확하게 확인된 첫 번째 산출물 항목으로 계약당 대표 `Obligation` 한 건을
  자동 생성한다. `assignee=AGENCY`, `evidence_type=URL`로 고정한다. 수동 생성 API는
  없으며 재처리·동시 실행에도 계약당 한 건만 남도록 트랜잭션과 유일성 제약을 사용한다.
- 대표 산출물은 생성에 실제 사용한 `VERIFIED ExtractedTerm`의 원문 근거를 보존한다.
  `Obligation.source_document_id`에는 대표 근거 `ExtractedTerm.document_id`를,
  `source_page`와 `source_text`에는 같은 추출값의 원문 위치를 기록한다. 제목은 같은
  근거의 검증된 채널·유형·수량을 결정적 코드로 조합하고 `confidence`는 사용한
  `VERIFIED ExtractedTerm.confidence`의 최솟값이다. 명확한 근거가 없으면 임의로
  만들지 않고 확인 신호를 유지한다.
- 자동 생성 후 별도 endpoint에서 사용자의 명시적 요청으로
  `OBLIGATION_EVIDENCE` scope 제출 링크를 만든다.
- 증빙 제출 링크는 계약 상태가 `SIGNED` 또는 `IN_PROGRESS`이고 대표 의무가
  `PENDING`일 때만 만든다. 링크 생성은 계약 상태를 자동으로 전환하지 않는다.
- 증빙 제출 링크는 멱등 예약·요청 검증, 공개 토큰, 감사 이벤트, 안전한 재생값을 한
  DB 트랜잭션에 저장한다. DB 커밋 뒤 응답이 유실되어도 같은 키 재시도는 최초 링크를
  재생하며 토큰이나 감사 이벤트를 중복 생성하지 않는다.
- 이행 목록 응답은 P0에서 빈 배열 또는 대표 항목 한 건만 반환한다.
- 제목 또는 due date 근거가 없으면 대표 의무를 만들지 않고 확인 신호를 유지한다.
- 증빙 URL은 길이 2,048 이하의 `http://` 또는 `https://` URL만 허용한다.
- P0에서는 URL 문자열을 증빙으로 저장할 뿐 서버가 URL을 가져오거나 진위를 판정하지 않는다.
- `APPROVED`일 때만 `payment_condition_met=true`다. 이는 실제 지급 승인이나 법적 이행
  판정이 아니다.

상태별 필드 불변식:

| 상태 | 증빙·시각 | `payment_condition_met` |
| --- | --- | --- |
| `PENDING` | `evidence_url`, `submitted_at`, `reviewed_at` 모두 `null` | `false` |
| `SUBMITTED` | URL과 `submitted_at` 존재, `reviewed_at=null` | `false` |
| `APPROVED` | URL과 제출·검토 시각 모두 존재 | `true` |
| `DISPUTED` | URL과 제출·검토 시각 모두 존재 | `false` |

## 10. 대시보드 집계 계약

- `total`, `signing`, `in_progress`, `completed`, `expiring_soon`은 소유자의 같은
  계약 집합에서 결정적으로 계산한다. `signing`은 `SIGNING`, `completed`는
  `COMPLETED`, `in_progress`는 `IN_PROGRESS`와 `RENEWAL_DUE` 상태를 센다.
- `expiring_soon`은 `0 ≤ expiry_d_day ≤ 30`,
  `0 ≤ termination_notice_d_day ≤ 14`, `0 ≤ auto_renewal_d_day ≤ 7` 중 하나
  이상인 계약을 중복 없이 센다.
- `auto_renewal_d_day`는 canonical `renewal_type=AUTO`이고 `end_date`가 있을 때
  `end_date - 오늘`로 계산한다. `MANUAL`, `NONE` 또는 날짜가 없으면 `null`이다.
- `unresolved_signals`는 `ReviewItem.status`가 `UNREVIEWED`, `SELECTED`, `SENT`인
  항목 수다. 조정 요청·합의·거절 조항 수, 의무 `PENDING`·`SUBMITTED`·
  `APPROVED` 수와 `most_common_signal`을 반환한다. 각 조정 지표에서 같은 항목은
  한 번만 센다.
- `total_committed`는 `SIGNED`, `IN_PROGRESS`, `RENEWAL_DUE`, `COMPLETED` 계약 중
  canonical `total_amount`가 있는 금액을 계약당 한 번만 합산한다.
- `payment_condition_met_amount`는 대표 의무가 `APPROVED`이고 canonical
  `total_amount`가 있는 계약의 총액을 계약당 한 번만 합산한다. 실제 지급액이나 법적
  채권액을 뜻하지 않는 P0 조건 충족 지표다.
- `most_common_signal`은 같은 미해결 집합의 검토 신호 유형 최빈값이며 동률 해소 순서는 코드와
  테스트에 고정한다. 값은 `MISMATCH`, `NO_BASIS`, `UNCLEAR`, `MISSING`,
  `NEEDS_CHECK` 중 하나이며 미해결 신호가 없으면 `null`이다.

## 11. 상태와 감사 이벤트

`AuditEvent.event_type`은 P0에서 다음 값만 사용한다.

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

계약 생성, 문서 업로드와 사용자 조건 저장부터 각각 `CONTRACT_CREATED`,
`DOCUMENT_UPLOADED`, `UNDERSTOOD_TERMS_SAVED`를 기록한다. 분석의 최초 접수·수동
재시작·완료·실패, 조정 초안·발송·열람·응답·확정·만료, 수정 계약서 대조·확인, 서명 초안·
요청·진행·종료, 대표 의무 생성·증빙 링크·제출·검토, 재계약 의사 저장도 위 대응
이벤트를 상태 변경과 같은 트랜잭션에 기록한다. 같은 선택의 반복 저장이나 공개 `/open`
재호출처럼 상태가 바뀌지 않는 멱등 재생은 새 이벤트를 만들지 않는다.

### 계약

`DRAFT → ANALYZING → REVIEW_REQUIRED → NEGOTIATING → READY_TO_SIGN → SIGNING → SIGNED → IN_PROGRESS → COMPLETED / RENEWAL_DUE`

### 조정 요청

`DRAFT → SENT → OPENED → RESPONDED → CONFIRMED / EXPIRED`

### 내부 서명

`REQUEST_READY → REQUESTING → EDITING → SIGNING → COMPLETED / ABORTED / FAILED`

### 모두싸인 원본 상태

enum은 `DRAFT`, `SCHEDULED`, `ON_PROCESSING`, `ON_GOING`, `COMPLETED`, `ABORTED`,
`PROCESSING_FAILED`이며 임베디드 P0 흐름은
`DRAFT → ON_PROCESSING → ON_GOING → COMPLETED / ABORTED /
PROCESSING_FAILED`다.

### 이행 항목

`PENDING → SUBMITTED → APPROVED / DISPUTED`

P0에서 구현하는 상태 변경은 최소한 다음 전이 계약을 지킨다.

| 대상·전이 | actor·trigger | guard | 같은 트랜잭션/후속 처리 |
| --- | --- | --- | --- |
| Contract `DRAFT → ANALYZING` | OWNER의 분석 시작 | 소유 계약의 `CONTRACT` 문서, 실행 중 작업 없음 | `AnalysisTask=QUEUED`, `ANALYSIS_STARTED` |
| Contract `ANALYZING → REVIEW_REQUIRED` | SYSTEM의 분석 성공 | 검증된 분석 결과 | canonical 승격, 첫 명확한 대표 의무 자동 생성, `ANALYSIS_COMPLETED` |
| Contract `REVIEW_REQUIRED → NEGOTIATING` | OWNER의 조정 요청 발송 | 선택된 1~4개 항목, `confirmed=true` | 공개 토큰·만료시각, 항목 `SENT`, `ADJUSTMENT_SENT` |
| Contract `NEGOTIATING` 유지 | OWNER의 최종 조정 확정 | 응답 완료, 항목별 유효한 resolution | 수락 항목 `RESOLVED`, 원안 유지 항목 `KEPT_ORIGINAL`, 확정 문구, `ADJUSTMENT_CONFIRMED` |
| Contract `NEGOTIATING → READY_TO_SIGN` | OWNER의 수정본 대조 최종 확인 | 최신 수정본, 모든 대조 항목 명시 확인 | 대조 `CONFIRMED`, 문서 ID·SHA-256 고정, `REVISED_CONTRACT_CONFIRMED` |
| Contract `READY_TO_SIGN` 유지 | OWNER의 임베디드 초안 생성 | 최신 확정 수정본 일치, 서명자 2명, `confirmed=true` | `Signature=EDITING`, `modusign_draft_id`, `SIGNATURE_DRAFT_CREATED`; 발송 없음 |
| Contract `READY_TO_SIGN → SIGNING` | SYSTEM의 인증된 모두싸인 발송 상태 반영 | 초안과 외부 문서 연결, 최신 원본 `ON_GOING` | `Signature=SIGNING`, 외부 문서 ID, `SIGNATURE_STARTED` |
| Contract `SIGNING → SIGNED` | SYSTEM의 인증된 모두싸인 완료 반영 | 멱등 웹훅 저장 및 최신 상태 조회 결과 `COMPLETED` | Signature 완료와 `AuditEvent` |
| Contract `SIGNING → READY_TO_SIGN` | SYSTEM의 서명 중단·실패 반영 | 최신 인증 원본이 `ABORTED`·`PROCESSING_FAILED` | terminal Signature와 `SIGNATURE_ABORTED`·`SIGNATURE_FAILED` 보존, 자동 재요청 금지 |
| Adjustment `DRAFT → SENT` | OWNER의 `/send` | `confirmed=true`, 아직 발송 전 | 토큰, `sent_at`, `expires_at`, `AuditEvent` |
| Adjustment `SENT → OPENED` | AGENCY의 `/open` | scope·resource·만료 검증 | 최초 `opened_at`, `AuditEvent`; 재호출은 무변경 |
| Adjustment `SENT / OPENED → RESPONDED` | AGENCY의 `/responses` | 모든 항목의 최초이자 유효한 일괄 응답 | 응답·`responded_at`; SENT이면 같은 시각의 `opened_at`; `AuditEvent` |
| Adjustment `RESPONDED → CONFIRMED` | OWNER의 최종 확정 | 모든 항목의 유효한 resolution | 관련 ReviewItem 최종 상태, 최종 문구, `ADJUSTMENT_CONFIRMED` |
| Adjustment `SENT / OPENED → EXPIRED` | SYSTEM의 만료 판정 | 현재 시각이 `expires_at` 이상, 미응답 | 상태와 `AuditEvent`; 이후 응답 금지 |
| Signature `REQUEST_READY → REQUESTING` | OWNER의 초안 생성 | 확정 수정 계약서·서명자·명시 승인 | 저장 PDF 무결성 검증과 외부 초안 호출 시작 |
| Signature `REQUESTING → EDITING` | OWNER의 초안 생성 성공 | 원본 `DRAFT`, 초안 ID 존재 | `SIGNATURE_DRAFT_CREATED`, 민감 편집 URL은 비저장 |
| Signature `REQUESTING → FAILED` | SYSTEM의 PDF·초안 생성 실패 | 외부 문서 발송 전 실패 | 완료 시각과 `SIGNATURE_FAILED`, Contract는 `READY_TO_SIGN` 유지 |
| Signature `EDITING → SIGNING` | SYSTEM의 외부 상태 반영 | 사용자가 편집기에서 발송, 인증 이벤트와 최신 원본 `ON_GOING` | 외부 문서 ID·fingerprint·`SIGNATURE_STARTED` |
| Signature `EDITING / SIGNING → ABORTED / FAILED`, `SIGNING → COMPLETED` | SYSTEM의 외부 상태 반영 | 인증 이벤트와 최신 종료 상태 | 종료 상태를 과거 이벤트로 되돌리지 않음 |
| Signature `EDITING → COMPLETED`, Contract `READY_TO_SIGN → SIGNED` | SYSTEM의 순서 역전 보정 | `COMPLETED` 최신 조회가 `ON_GOING`보다 먼저 처리됨 | `SIGNATURE_COMPLETED`를 한 트랜잭션으로 기록 |
| Obligation `PENDING → SUBMITTED` | AGENCY의 증빙 제출 | 유효한 scope·resource·만료, 최초 제출 | URL·`submitted_at`, `AuditEvent` |
| Obligation `SUBMITTED → APPROVED / DISPUTED` | OWNER의 명시적 검토 API 호출 | 소유권과 유효한 decision | `reviewed_at`, 지급 조건 표시, `AuditEvent` |

`SIGNED → IN_PROGRESS → COMPLETED / RENEWAL_DUE`의 정확한 시점은 계약 시작·종료일과
이행 상태를 사용하는 결정적 규칙으로 구현 전에 고정한다. 기획안에 없는 자동 완료나
자동 재계약 전이를 임의로 추가하지 않는다.

- D-30 만료, D-14 해지 통보기한, D-7 자동갱신 신호를 서버가 날짜로 계산한다.
- 다음 선택 저장은 위 세 신호 중 하나의 검토 구간에서만 허용한다.
- 같은 선택의 반복 PUT은 기존 `decided_at`과 응답을 유지하고 새 `AuditEvent`를
  만들지 않는다. 다른 선택으로 변경할 때만 시각과 감사 이벤트를 갱신한다.
- 사용자는 `RENEW_SAME_TERMS`, `RENEW_WITH_CHANGES`, `TERMINATE` 중 하나를
  명시적으로 확정한다. 서버는 결정·`decided_at`·`AuditEvent`를 저장한다.
- `RENEW_WITH_CHANGES`이면 이전에 거절되거나 원안 유지된 검토 항목 ID를 다시 보여준다.
  다른 두 선택의 `revisit_review_item_ids`는 빈 배열이다.
  선택만으로 계약 상태를 바꾸거나 새 계약·문서·조정·서명을 만들지 않는다.
  재계약 초안 복제는 P1이다. 저장된 최신 선택은 계약 상세의 nullable
  `renewal_decision`으로 다시 조회한다.

- 프런트나 Adapter가 상태 enum을 직접 대입하지 않는다.
- 상태 전이와 권한 검사는 service/domain 계층에서 수행한다.
- 허용되지 않은 전이는 `INVALID_STATUS_TRANSITION`으로 거부한다.
- 로컬 상태 변경과 `AuditEvent` 추가는 하나의 DB 트랜잭션으로 처리한다.
- 감사 이벤트에는 계약 전문, 연락처, 토큰, 서명 링크를 넣지 않는다.

## 12. B·C 구현 경계와 D 검증 역할

| 담당 | API·데이터 생산 | 주요 소비 |
| --- | --- | --- |
| B — 문서·AI·공통 기반·이행 | 공통 repository·`AuditEvent`, `Document`, `UnderstoodTerm`, `AnalysisTask`, `ExtractedTerm`, `ReviewItem`, 공개 증빙, `Obligation` | C의 `Contract`·상태 전이 규칙 |
| C — 계약·모두싸인·대시보드 | `Contract`, `AdjustmentRequest`, `Agreement`, `Signature`, `Dashboard` | B의 확정 `ReviewItem`·repository·검증된 추출값 |
| D — 배포·QA 검증 | 백엔드 API·영속 데이터 생산 없음; 배포본 E2E 결과와 재현 절차 제공 | B·C가 구현한 전체 P0 흐름 |

교차 규칙:

- B가 Supabase DB·Storage Adapter, 객체 권한, 공통 repository와 감사 트랜잭션을
  구현한다.
- C가 조정 상세 endpoint를 담당하지만 역제안 쉬운 설명이 AI를 사용하면 B의 내부
  비교 서비스를 호출한다.
- 대행사 응답은 먼저 영속화한다. B의 `CounterproposalComparator`는 저장된 실제
  요청 문구, `counter_text`, `reason`만 비교하며 수락·거절은 결정적 코드로,
  역제안은 Solar 구조화 출력으로 설명한다. 비교 실패는 저장된 응답을 삭제하거나
  덮어쓰지 않고 `502 ANALYSIS_SCHEMA_INVALID`로 노출한다.
- B는 repository와 감사 이벤트를 제공하지만 C의 계약·조정·서명 전이 규칙을
  우회하지 않는다. C도 B의 AI 스키마와 근거 검증을 우회하지 않는다.
- D는 endpoint, service, repository, Adapter 또는 migration을 직접 구현하지 않고
  배포·환경변수 확인, 전체 E2E 실행, 데모 데이터와 테스트 증빙 정리를 담당한다.
- `apps/api/app/core/config.py`, `apps/api/app/schemas/common.py`, `packages/contracts`,
  `packages/contracts/openapi/openapi.yaml`, 공통 마이그레이션은 변경 전에 B·C가
  합의하고 D에 검증 영향을 공유한다.
- B와 C는 별도 백엔드를 만들지 않고 `apps/api` 하나를 함께 사용한다. D는 그 배포본을
  검증하며 백엔드 구현 브랜치를 소유하지 않는다.

## 13. 계약 변경 체크리스트

공개 API, 영속 상태 또는 AI 출력이 바뀌면 다음을 한 변경 단위에서 확인한다.

- [ ] `packages/contracts/openapi/openapi.yaml`
- [ ] Pydantic 요청·응답 스키마
- [ ] service/domain 상태 전이
- [ ] repository와 새 마이그레이션
- [ ] 공개 토큰 scope·만료·`no-store`
- [ ] API envelope와 오류 코드
- [ ] 단위·통합·API 테스트
- [ ] README와 `.env.example`
- [ ] AI 변경이면 fixture, 프롬프트 버전, `AI_USAGE.md`

## 14. 6.14 광고효과 P2-0 확정 데이터 계약

이 절은 `docs/api-명세서.md` 16~17절의 확정값을 영속성·보안·상태 관점에서
고정한다. 광고효과 기능은 P2이며 현재 백엔드 runtime과 migration에는 구현되지 않았다.
기존 P0 API, 전역 `/dashboard` 응답과 계약 상태 머신을 이 설계만으로 변경하지 않는다.

### 14.1 소유권·업무 범위

- 광고효과 API 4개는 모두 소상공인 Bearer 인증을 사용하며 공개 토큰 API를 만들지
  않는다. `contract_id`, `report_id`, `source_document_id`와 모든 revision·flag의
  계약 소유권을 서버 인증 컨텍스트로 검증한다.
- 쓰기는 Contract가 `SIGNED`, `IN_PROGRESS`, `RENEWAL_DUE`, `COMPLETED`일 때만
  허용한다. 리포트 업로드·추출·확정·정정은 Contract 상태를 변경하지 않는다.
- P2 광고효과 대시보드는 계약별 `GET /contracts/{contract_id}/performance`다. 기존
  전역 `/dashboard` 응답에는 성과 지표를 추가하지 않는다.
- AI `extracted_payload`는 소유자 확인 전 초안이다. 각 월의 최신 확정 revision만
  집계·계약 대조·재계약 근거로 사용한다.
- 서버는 성과·위법성·계약 위반·지급 여부를 판정하지 않고 문의 문안을 발송하지 않는다.
  전환율·CPA·ROAS, 매출 기여도, 플랫폼 API 수집, 리포트 위·변조 결과는 저장하지 않는다.

### 14.2 원본 Document·월별 고유성·업로드 원자성

`PerformanceReport.source_document_id`는 같은 계약의 기존 `Document.id`를 참조하며
해당 문서의 type은 `PERFORMANCE_REPORT`다. 이 type은 성과 리포트 전용 업로드 API에서만
생성하고 기존 `/documents` 요청 enum에는 노출하지 않는다. 원본 열람은 기존 소유자 전용
문서 접근 API와 `Cache-Control: no-store` 규칙을 재사용한다.

`PerformanceReport`는 최소한 다음 값을 보존한다.

- `id`, `contract_id`, `period`
- `source_document_id`, `status`, `extracted_payload`
- `current_revision_id`, `revision_count`
- `extraction_attempt_id`, `extraction_started_at`
- `created_at`, `updated_at`

DB는 `(contract_id, period)`와 `source_document_id`를 각각 고유하게 한다. `period`는
`Asia/Seoul` 달력월의 `YYYY-MM`이며 계약·월별 논리 리포트는 한 건이다. 채널별 여러
리포트와 `channel_key`는 P2 범위에 포함하지 않는다. 다른 요청으로 같은 월을 다시
생성하면 `409 REPORT_PERIOD_ALREADY_EXISTS`다. 정정은 두 번째 report가 아니라 같은
report의 새 revision으로 남긴다.

multipart 멱등 fingerprint는 정규화한 `period`, 파일 바이트 SHA-256, 검증한 MIME과
파일 크기로 만든다. 같은 키와 같은 fingerprint는 최초 응답을 재생하고 같은 키에 다른
fingerprint를 사용하면 `409 IDEMPOTENCY_CONFLICT`다.

공통 `IdempotencyOperation`은 다음 세 값으로 고정한다.

| 쓰기 | operation |
| --- | --- |
| 리포트 업로드 | `PERFORMANCE_REPORT_UPLOAD` |
| 리포트 추출·stale 복구 | `PERFORMANCE_REPORT_EXTRACT` |
| 최초 확정·append-only 정정 PATCH | `PERFORMANCE_REPORT_CONFIRM` |

최초 확정과 정정은 같은 HTTP operation과 공통 enum을 사용하되 request fingerprint의
`expected_revision`, 확정 payload, 사용자 이상 사유와 정정 사유가 다르면 같은 멱등
키로 재생하지 않는다.

Storage 업로드는 긴 DB 트랜잭션 밖에서 수행한다. DB RPC는 `Document` 메타데이터,
`PerformanceReport=UPLOADED`, `PERFORMANCE_REPORT_UPLOADED` 감사 이벤트를 원자적으로
저장한다. DB 저장 실패 시 업로드 객체를 삭제한다. 응답 유실 뒤 재시도는 서버가 미리
만든 Document·report UUID와 멱등 예약으로 커밋 여부를 복구하며 중복 파일·행·이벤트를
만들지 않는다. Storage 경로와 원본 파일명은 일반 응답이나 로그에 노출하지 않는다.

### 14.3 추출 claim·실패·stale 복구

추출은 `UPLOADED` report에서만 시작한다. 서비스는 완료된 같은 멱등 요청을 먼저 재생한
뒤 report와 Document를 lock하고 `extraction_attempt_id`, `extraction_started_at`과
Document의 기술 상태를 원자적으로 claim한다. 15분 미만의 활성 `PROCESSING`에는 다른
키로 외부 AI를 다시 호출하지 않고 `409 REPORT_EXTRACTION_IN_PROGRESS`를 반환한다.

15분 이상 지난 stale attempt만 소상공인의 새 `Idempotency-Key`를 사용한 명시적
재시도로 원자 재점유한다. 이전 멱등 예약을 abandon하고
`PERFORMANCE_REPORT_EXTRACTION_RECOVERED`를 기록한다. 현재 attempt ID와 일치하는 완료만
상태와 payload를 저장할 수 있으며 이전 작업의 늦은 응답은 버린다. 서버는 stale 작업을
자동 재개하거나 외부 AI를 자동 재호출하지 않는다.

`Document.parse_status`는 파일 파싱 기술 상태이고 `PerformanceReport.status`는 사용자
업무 상태다. 성공 시 Document를 `COMPLETED`, report를 `EXTRACTED`로 만들고 근거가 있는
완전한 `extracted_payload`와 `PERFORMANCE_REPORT_EXTRACTED`를 원자 저장한다. Parse 실패는
Document를 `FAILED`, report를 `UPLOADED`로 유지한다. Solar 매핑만 실패하면 Document의
`COMPLETED`를 보존하고 report를 `UPLOADED`로 유지한다. P2는 Parse 결과를 별도 저장하지
않으므로 명시적 재시도는 Document Parse부터 다시 실행한다.

timeout·HTTP·Parse·AI 스키마 실패를 고정 샘플로 대체하지 않고
`502 REPORT_EXTRACT_FAILED`를 반환한다. 추출 후보 각 필드는 `value`, `source_page`,
`source_text`, `confidence`, `verification_status`를 가진다. 원문에서 찾지 못한
`published_content_count`나 다른 지표를 행·URL 수로 추정하지 않고 `NOT_FOUND`로 둔다.

### 14.4 확정 지표·반응률 결정 규칙

확정 payload는 `additionalProperties=false`이며 다음 범위만 허용한다.

| 구분 | 필드 | 규칙 |
| --- | --- | --- |
| 필수 | `impressions`, `likes`, `comments` | 0 이상 정수 |
| 리포트 선택 | `reach`, `saves`, `shares` | nullable 0 이상 정수 |
| 리포트 선택 | `follower_net_change` | nullable 정수, 음수 허용 |
| 계약 대조 | `published_content_count` | nullable 0 이상 정수, `0`과 `null` 구분 |
| 소유자 선택 | `inquiries`, `reservations`, `purchases` | nullable 0 이상 정수 |
| 서버 파생 | `engagement_rate` | 클라이언트 입력 금지 |

`published_content_count`는 리포트에 명시되었거나 소유자가 확인·입력한 값만 저장한다.
AI 후보가 있더라도 소유자가 확정한 값만 비교한다. `null`이면 수량 신호를 만들지 않는다.

반응률은 확정 원본 정수에서
`(likes + comments + saves + shares) / impressions`로 계산한다. nullable `saves`와
`shares`는 계산에서 0으로 보되 null과 명시적 0의 존재 정보는 보존한다.
`impressions=0`이면 반응률은 `null`이다. 판정은 반올림 전 충분한 정밀도의 `Decimal`로
수행하고 API 저장·반환용 소수 6자리 반올림값을 판정에 다시 사용하지 않는다.

`ENGAGEMENT_RATE_DROP`은 다음 조건을 모두 만족할 때만 만든다.

- 달력상 바로 전월과 현재 월에 각각 최신 확정 revision이 있다.
- 두 달 모두 `impressions >= 1000`이고 이전 반응률이 0보다 크다.
- 두 달의 `saves`·`shares` 포함 구성이 같다.
- 절대 하락폭이 반올림 전 `1.0%p` 이상이고 상대 하락률이 `25%` 이상이다.

첫 달, 전월 누락, 0 노출, 표본 미달, 이전 반응률 0, 선택 지표 구성 차이가 있으면 이
신호를 만들지 않는다.

### 14.5 append-only 확정·정정 revision

`PerformanceReportRevision`은 최소한 `id`, `report_id`, `version`, `confirmed_payload`,
`engagement_rate`, `status`, nullable `corrected_from_revision_id`, nullable
`correction_reason`, `confirmed_at`을 보존한다. `(report_id, version)`은 고유하고 version은
1부터 시작한다.

- `EXTRACTED`에서 `expected_revision=0`, `correction_reason=null`이면 version 1을 만든다.
- `CONFIRMED`·`FLAGGED`에서는 `expected_revision`이 현재 version과 같고 1~500자의
  비어 있지 않은 정정 사유가 있을 때 version N+1을 만든다.
- version 2 이상은 같은 report의 바로 전 revision을 `corrected_from_revision_id`로
  참조한다. 기존 revision·flag·문의 문안을 UPDATE·DELETE하지 않는다.
- 가장 최근에 확정된 월만 정정한다. 더 뒤의 확정 report가 있으면
  `409 REPORT_CORRECTION_DEPENDENCY_EXISTS`이며 연쇄 재계산하지 않는다.
- `expected_revision`이 다르면 `409 REPORT_REVISION_CONFLICT`이고 새 revision을 만들지
  않는다.

PATCH 서비스는 같은 멱등 요청 재생을 상태·revision 검사보다 먼저 수행한다. 새 요청은
report 행을 `FOR UPDATE`로 lock한 뒤 상태, 현재 version과 후속 확정 월을 다시 검사한다.
`PerformanceReportRevision`, revision별 flag·문의 snapshot, report의
`current_revision_id`·`revision_count`·현재 표시 상태와 감사 이벤트를 한 트랜잭션에
저장한다.

`CONFIRMED`·`FLAGGED`는 과거 revision이 immutable이라는 의미에서 terminal이다. 정정은
terminal 값을 전이하거나 덮어쓰지 않고 새 revision을 추가한다. report의 현재 projection은
최신 revision에 따라 `CONFIRMED`와 `FLAGGED` 사이에서 바뀔 수 있다. 조회·집계·대조에는
각 월의 최신 non-superseded revision만 한 번 포함하고 과거 revision은 감사 이력으로
보존한다.

공통 코드에는 `PerformanceReportStatus`와 별도 계획값
`PerformanceStateEntityType.PERFORMANCE_REPORT`를 선언하지만 P2 runtime·migration
전에는 기존 `StateEntityType`과 `packages/contracts/state-machines.json`에 report 전이를
병합하지 않는다. 현재 state transition RPC가 지원하지 않는 값을 실행 가능 enum처럼
노출하지 않기 위함이며, 후속 migration에서 revision의 terminal 상태와 report 현재
projection 갱신을 분리한 저장 규칙을 구현할 때 함께 추가한다.

### 14.6 revision별 flag·계약 근거·문의 snapshot

`PerformanceFlag`는 report가 아니라 `report_revision_id`에 속하며 flag type은 다음 세
값만 허용한다.

- `DELIVERABLE_COUNT_SHORTFALL`
- `ENGAGEMENT_RATE_DROP`
- `OWNER_REPORTED_ISSUE`

수량 신호는 계약 원문의 `CONTENT_QUANTITY`와 월 단위 `POSTING_FREQUENCY`가 모두
`source_type=CONTRACT_DOCUMENT`, `verification_status=VERIFIED`이고 페이지·문장 근거가
있으며, `published_content_count < expected_count`일 때만 만든다. 실제 게시 수가 같거나
많으면 신호를 만들지 않는다.

별도의 가상 Clause를 만들지 않는다. DB의
`PerformanceFlagBasisTerm(flag_id, extracted_term_id)`이 같은 계약의 검증된
`ExtractedTerm.id`를 연결하고 공개 응답은 중복 없는 `basis_extracted_term_ids`를
반환한다. flag에는 문서 ID·페이지·문장·confidence·기대 수량·단위의 immutable basis
snapshot도 보존한다. 사용자 이상 기록과 반응률 하락은 적절한 계약 원문 근거가 없으면
빈 근거 목록을 허용한다. 반응률 하락은 바로 전월의
`comparison_report_revision_id`를 보존한다.

문의 문안은 Solar가 아니라 `performance-inquiry-copy-v1` 결정적 템플릿으로 확정·정정
시 생성한다. `PerformanceInquiryDraft`는 고유한 `flag_id`, `text`, `template_version`,
`created_at`을 revision별 snapshot으로 보존한다. 조회 시 다시 생성하거나 AI를 호출하지
않고 저장된 문안만 반환한다. 외부 발송은 하지 않는다.

### 14.7 감사·보안·무부작용 조회

계획한 P2 감사 이벤트는 다음과 같다.

```text
PERFORMANCE_REPORT_UPLOADED, PERFORMANCE_REPORT_EXTRACTED,
PERFORMANCE_REPORT_CONFIRMED, PERFORMANCE_REPORT_FLAGGED,
PERFORMANCE_REPORT_CORRECTED, PERFORMANCE_REPORT_EXTRACTION_RECOVERED
```

현재 DB `audit_events.event_type` CHECK는 P0 값만 허용하므로 위 6개는 공통 코드와
OpenAPI의 별도 `PerformanceAuditEventType`에 계획값으로 둔다. 후속 P2 migration에서
DB CHECK를 확장할 때 기존 `AuditEventType`에 병합하며, 그 전에는 runtime이 이 값을
저장하지 않는다.

업로드는 Document·report·감사 이벤트, 추출은 현재 attempt의 payload·상태·감사 이벤트,
확정·정정은 revision·flag·문의 snapshot·현재 projection·감사 이벤트를 각각 원자적으로
저장한다. 멱등 재생은 revision·flag·문안·감사 이벤트를 중복 생성하지 않는다.

원본 리포트, 전체 OCR 텍스트, AI 입출력, 확정 지표, 정정 사유, 사용자 이상 사유와 문의
문안을 로그에 남기지 않는다. Storage 경로·서명 URL·개인 연락처에 적용하던 기존 마스킹과
private 접근 규칙을 그대로 적용한다. Upstage·Solar는 추출에서만 Adapter의 `mock`·`live`
모드를 사용하며 일반 테스트는 외부 네트워크를 호출하지 않는다.

GET은 상태·revision·flag·감사 이벤트를 변경하지 않고 AI나 문의 문안 생성기를 실행하지
않는다. 확정되지 않은 `UPLOADED`·`EXTRACTED` payload는 확인 화면에서만 보일 수 있고
집계·계약 대조·재계약 근거에는 사용하지 않는다.

### 14.8 구현 상태

이 절은 P2-0 공개·영속 계약을 확정한 문서 변경이다. 현재 FastAPI endpoint, service,
repository와 Supabase migration은 구현되지 않았다. 구현 전 OpenAPI·Pydantic·공통 enum과
오류를 같은 값으로 맞추고, 구현 뒤 다음을 검증하기 전 P2 완료로 표시하지 않는다.

- 계약·월·source Document 고유성, 소유권과 private 접근
- 업로드 응답 유실·롤백과 추출 claim·15분 stale 복구
- 0/null·첫 달·전월 누락·999/1000 노출·1.0%p·25% 경계
- 수량 부족만 flag하고 같거나 초과한 게시 수에는 flag하지 않음
- 최신 월 append-only 정정, revision conflict와 후속 월 dependency 거부
- 과거 revision·flag·문의 snapshot 불변성과 최신 revision 단일 집계
- GET 무부작용·문안 미발송·일반 테스트 무네트워크
