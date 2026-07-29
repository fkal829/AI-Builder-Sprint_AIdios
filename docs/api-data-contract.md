# P0 API·데이터 계약

이 문서는 프런트엔드, 문서·AI, 조정·전자서명, 통합·이행 작업이 공유하는
경계를 설명한다. 상세 HTTP 스키마는
`packages/contracts/openapi/openapi.yaml`을 기준으로 한다.

## 명명과 변환

| 경계 | 규칙 | 예시 |
| --- | --- | --- |
| HTTP JSON | `snake_case` | `counterparty_name`, `request_id` |
| FastAPI/Pydantic | `snake_case` | `source_page`, `source_text` |
| PostgreSQL | `snake_case` | `termination_notice_date` |
| 프런트 도메인 모델 | `camelCase` 허용 | `counterpartyName` |

프런트의 `camelCase` 변환은 `apps/frontend/src/lib/adapter.ts` 한 곳에서 수행한다.
페이지와 컴포넌트가 HTTP DTO를 직접 변환하지 않는다.

## 공통 응답

성공:

```json
{
  "data": {},
  "error": null,
  "request_id": "req_123abc"
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
  "request_id": "req_123abc"
}
```

오류 메시지나 `details`에는 계약 전문, 연락처, 공개 토큰, 서명 링크를 넣지 않는다.

## 원문 근거

추출 결과와 검토 항목은 다음 네 필드를 항상 포함한다.

- `source_page`
- `source_text`
- `confidence`
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

## 상태 변경 책임

- 프런트는 원하는 다음 상태를 임의 저장하지 않는다.
- FastAPI service가 `packages/contracts/state-machines.json`에 정의된 전이를 검증한다.
- 외부 모두싸인 상태는 `SignatureStatus`로 저장한 뒤 계약 상태에 매핑한다.
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
