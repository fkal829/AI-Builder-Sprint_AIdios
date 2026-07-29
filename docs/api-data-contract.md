# P0 API·데이터 계약

이 문서는 프런트엔드, 문서·AI, 조정·전자서명, 통합·이행 작업이 공유하는
경계를 설명한다. 상세 HTTP 스키마는
`packages/contracts/openapi/openapi.yaml`을 기준으로 한다.

## 명명과 변환

| 경계 | 규칙 | 예시 |
| --- | --- | --- |
| HTTP JSON | 기본 `snake_case`, envelope 식별자는 `requestId` | `counterparty_name`, `requestId` |
| FastAPI/Pydantic | `snake_case` | `source_page`, `source_text` |
| PostgreSQL | `snake_case` | `termination_notice_date` |
| 프런트 도메인 모델 | `camelCase` 허용 | `counterpartyName` |

프런트의 `camelCase` 변환은 `apps/frontend/src/lib/adapter.ts` 한 곳에서 수행한다.
페이지와 컴포넌트가 HTTP DTO를 직접 변환하지 않는다.

원화 금액은 소수점이 없는 정수 원 단위로 주고받는다.

```yaml
type: integer
format: int64
minimum: 0
```

## 공통 응답

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
    "message": "현재 상태에서는 요청을 처리할 수 없습니다.",
    "details": null
  },
  "requestId": "req_123abc"
}
```

오류 메시지나 `details`에는 계약 전문, 연락처, 공개 토큰, 서명 링크를 넣지 않는다.

## 원문 근거

추출 결과는 원문 근거와 `confidence`를 포함한다. 검토 항목은
`detection_method`가 `MODEL` 또는 `HYBRID`일 때만 `model_confidence`를 갖는다.

- `source_page`
- `source_text`
- `confidence` (추출 결과)
- `verification_status`

`verification_status`의 의미:

| 값 | 의미 | 원문 표시 |
| --- | --- | --- |
| `VERIFIED` | 페이지와 문장을 검증함 | 확정 근거로 표시 가능 |
| `NOT_FOUND` | 계약서에서 근거를 찾지 못함 | “근거를 찾지 못함”으로 표시 |
| `MISSING_EVIDENCE` | 결과는 있으나 근거 연결에 실패함 | 확정값 표시 금지 |
| `NEEDS_CHECK` | 모순·낮은 확신도 등으로 확인 필요 | 사용자 확인 필요 |

`VERIFIED`에는 페이지와 문장이 반드시 있어야 한다. `NOT_FOUND`에는 페이지와 문장을
임의로 채우지 않는다.

추출 필드는 enum으로 제한하고 `value_type`으로 값 타입을 구분한다.

- `MONEY_KRW`: 0 이상의 원화 정수
- `DATE`: ISO 8601 date
- `BOOLEAN`: `YES`, `NO`, `UNKNOWN`
- `PERCENT`: 0~100 정수
- `INTEGER`: 0 이상의 정수
- `TEXT`: 문자열

## 인증과 공개 토큰

- `/contracts`, `/dashboard` 등 소유자 API에는 Bearer 인증이 필요하다.
- `/public/adjustment-requests/*`는 `ADJUSTMENT_RESPONSE` scope 토큰만 허용한다.
- `/public/obligations/*`는 `OBLIGATION_EVIDENCE` scope 토큰만 허용한다.
- 두 공개 토큰은 서로 교환해서 사용할 수 없으며 원문을 로그에 남기지 않는다.
- 소유자가 존재하지 않거나 다른 소유자의 리소스에 접근하면 리소스 존재 여부를
  노출하지 않도록 `404`를 반환할 수 있다.

## 외부 실행과 멱등성

조정 링크 활성화와 모두싸인 서명 요청에는 `Idempotency-Key` 헤더가 필요하다.
동일 키와 동일 요청은 최초 결과를 반환하고, 동일 키에 다른 요청 body가 오면
`IDEMPOTENCY_CONFLICT`로 거부한다.

모두싸인 외부 API 호출은 서버 Adapter가 HTTP Basic 인증으로 수행한다. 웹훅 수신은
웹훅 등록 시 설정한 `X-Modusign-Webhook-Secret` 사용자 지정 헤더를 검증한다.
공식 웹훅 payload에는 별도 이벤트 ID가 없으므로 `event.type`, `document.id`, payload
해시를 이용해 중복 안전하게 처리한다.

서명자 연락처 원문은 서명 요청 시 Adapter 전달에만 사용하고 DB·로그·응답에는 남기지
않는다. 역할, 이름, 서명 수단, 마스킹 값과 단방향 fingerprint만 저장한다.

- [모두싸인 API QuickStart](https://developers.modusign.co.kr/docs/quick-start)
- [모두싸인 Webhook event](https://developers.modusign.co.kr/docs/webhook-event)

## 상태 변경 책임

- 프런트는 원하는 다음 상태를 임의 저장하지 않는다.
- FastAPI service가 `packages/contracts/state-machines.json`에 정의된 전이를 검증한다.
- 모두싸인 원본 상태는 `modusign_status`, 서비스 내부 서명 상태는 `status`로 분리해
  저장한 뒤 계약 상태에 매핑한다.
- 발송, 최종 합의, 서명 시작, 증빙 승인은 사용자의 명시적 요청으로만 수행한다.
- 상태 변경마다 `AuditEvent`를 추가하되 민감한 payload는 남기지 않는다.

## 팀별 생산·소비 경계

| 담당 | 생산 | 소비 |
| --- | --- | --- |
| A 프런트엔드 | 사용자 입력, 명시적 확인 | 모든 P0 API 응답 |
| B 문서·AI | `ExtractedTerm`, `ReviewItem` | 문서와 `UnderstoodTerm` |
| C 조정·서명 | `AdjustmentRequest`, `Signature`, `Agreement` | 선택된 `ReviewItem` |
| D 통합·이행 | API envelope, `Obligation`, `AuditEvent`, 대시보드 | A·B·C의 공통 계약 |

공유 구조를 변경할 때는 OpenAPI/JSON Schema, Pydantic, 프런트 adapter 타입, 테스트를
같은 변경 단위에서 정렬한다.
