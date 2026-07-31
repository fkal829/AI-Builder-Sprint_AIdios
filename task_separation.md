# C 역할 작업 분리

## 범위

C는 계약 생명주기 중 계약·조정·전자서명·재계약·대시보드를 담당한다.

- 담당: 계약 생성·목록·상세·감사 타임라인, 계약/조정/서명 상태 전이, 조정 요청과 대행사 공개 응답, 수정 계약서 대조, 모두싸인, 만료·재계약, 대시보드
- B 담당: 문서 업로드·Storage, 사용자 이해조건, AI 분석·추출, ReviewItem 생성·선택, 이행 항목·증빙, 공통 repository/AuditEvent 기반
- 공통 원칙: 상태 변경과 감사 이벤트는 하나의 트랜잭션으로 저장하고, OpenAPI·Pydantic·migration·테스트를 함께 변경한다.

## GitHub 이슈 순서

### C-1. 계약·조정·서명 상태 머신 서비스 구현

**목적:** 모든 C API가 상태를 직접 변경하지 않도록 도메인 전이 함수를 만든다.

```text
Contract
DRAFT → ANALYZING → REVIEW_REQUIRED → NEGOTIATING
→ READY_TO_SIGN → SIGNING → SIGNED
→ IN_PROGRESS → COMPLETED / RENEWAL_DUE

Adjustment
DRAFT → SENT → OPENED → RESPONDED → CONFIRMED / EXPIRED

Signature
REQUEST_READY → REQUESTING → EDITING → SIGNING → COMPLETED / ABORTED / FAILED
```

완료 조건:

- 허용되지 않은 전이는 `409 INVALID_STATUS_TRANSITION`으로 거부한다.
- 상태 변경과 `AuditEvent` 기록을 한 DB 트랜잭션으로 처리한다.
- B가 분석 성공·실패를 반영할 때 사용할 상태 전이 인터페이스를 제공한다.
- Router, repository, Modusign Adapter는 상태 enum을 직접 변경하지 않는다.

### C-2. 계약 기본 API: 생성·목록·상세·타임라인

대상 API:

```text
POST /contracts
GET  /contracts
GET  /contracts/{contract_id}
GET  /contracts/{contract_id}/timeline
```

구현 기능:

- 소상공인 소유 계약 생성: 제목, 상대 대행사명
- 계약 목록: 만료일 오름차순, 만료일 없음은 마지막
- 계약 상세: B가 나중에 넣는 canonical 기간·총액·갱신 정보도 `null` 포함 형태로 반환
- 감사 타임라인: 시간순 정렬, 내부 민감 payload는 노출하지 않음
- 소유자 권한 검증

완료 조건:

- 생성 시 `DRAFT`, `CONTRACT_CREATED` 이벤트를 생성한다.
- 다른 사용자의 계약은 접근할 수 없다.
- 목록과 타임라인 정렬 테스트를 통과한다.

### C-3. 공개 토큰·멱등성 처리 기반

조정 링크와 임베디드 서명 초안의 재시도 시 중복 생성이 일어나지 않게 한다.

구현 기능:

- 공개 토큰은 원문 대신 hash, scope, resource ID, 만료 시각을 저장한다.
- 조정 응답 링크 scope는 `ADJUSTMENT_RESPONSE`로 고정한다.
- `Idempotency-Key` 저장 및 같은 요청의 최초 응답 재생
- 같은 키에 다른 요청이면 `409 IDEMPOTENCY_CONFLICT`
- 공개 토큰 형식·scope·대상 불일치는 `404`, 유효하지만 만료되었으면 `410`
- 공개 URL과 토큰 응답에는 `Cache-Control: no-store`

### C-4. 소상공인 조정 요청 초안·상세·발송

대상 API:

```text
POST /contracts/{contract_id}/adjustment-requests
GET  /contracts/{contract_id}/adjustment-requests/{adjustment_request_id}
POST /contracts/{contract_id}/adjustment-requests/{adjustment_request_id}/send
```

구현 기능:

- B가 만든 `ReviewItem` 중 `SELECTED` 상태의 절충안/요청안만 1~4개 선택한다.
- 발송 전 조정 요청 초안과 실제 요청 문구를 미리보기로 제공한다.
- 소상공인이 `confirmed=true`로 확인한 뒤 공개 링크를 활성화한다.
- 발송 시 선택된 ReviewItem을 `SENT`로 동결한다.
- 계약당 실제 조정 발송·응답 라운드는 한 번만 허용한다.
- 소유자용 상세에서 대행사 응답과 역제안 비교 결과를 함께 조회한다.

완료 조건:

- 초안에는 공개 URL이 없다.
- 발송 응답에서만 `public_url`을 반환한다.
- 이미 발송 이력이 있으면 새 발송은 `409`로 거부한다.
- `REVIEW_REQUIRED → NEGOTIATING` 전이와 감사 이벤트를 기록한다.

### C-5. 대행사용 공개 조정 응답

대상 API:

```text
GET  /public/adjustment-requests/{token}
POST /public/adjustment-requests/{token}/open
POST /public/adjustment-requests/{token}/responses
```

구현 기능:

- 가입 없이 유효한 공개 토큰으로 조정 요청을 조회한다.
- 공개 GET은 상태를 바꾸지 않는다.
- 실제 공개 화면이 렌더링된 뒤 `/open`을 호출해 최초 열람만 기록한다.
- 대행사가 모든 조항을 정확히 한 번씩 응답한다.
  - `ACCEPT`: 추가 문구·사유 없음
  - `REJECT`: 사유 필수
  - `COUNTER`: 역제안 문구와 사유 필수
- 전체 응답은 한 번만 원자적으로 제출한다.

완료 조건:

- `/open` 반복 호출은 최초 열람 시각과 이벤트를 바꾸지 않는다.
- 열람 없이 응답하면 열람·응답 시각을 함께 기록한다.
- 만료·중복 응답·누락 항목을 정확히 거부한다.
- `SENT/OPENED → RESPONDED` 전이와 감사 이벤트를 기록한다.

### C-6. 최종 조정 확정 및 수정 계약서 대조

대상 API:

```text
POST /contracts/{contract_id}/adjustment-confirmation
POST /contracts/{contract_id}/revised-contract-reviews
GET  /contracts/{contract_id}/revised-contract-reviews/latest
POST /contracts/{contract_id}/revised-contract-reviews/{review_id}/confirmation
```

구현 기능:

- 소상공인이 각 조항별로 `ACCEPT_REQUEST`, `ACCEPT_COUNTERPROPOSAL`, `KEEP_ORIGINAL` 중 하나를 선택한다.
- 클라이언트가 임의의 최종 합의 문구를 보내지 못하게 하고, 서버가 저장된 요청·응답 기록에서 최종 문구를 결정한다.
- 대행사가 기존 채널로 보낸 최신 `REVISED_CONTRACT` PDF와 확정 문구를 대조한다.
- 정확 문구만 `MATCHED`로 표시하고 나머지는 사용자의 직접 확인을 요구한다.
- 최신 검토의 모든 항목을 확인하면 문서 ID·SHA-256을 고정하고 `READY_TO_SIGN`으로 전이한다.

완료 조건:

- 조정 확정 때는 `NEGOTIATING`을 유지하고 수정 계약서 최종 확인 때 `READY_TO_SIGN`으로 전이한다.
- 수용 조항은 `RESOLVED`, 원안 유지 조항은 `KEPT_ORIGINAL`으로 처리한다.
- 최신 수정본이 아니거나 확정 항목이 빠지면 최종 확인을 거부한다.

### C-7. 모두싸인 Adapter 및 임베디드 서명 초안

> **변경(2026-07-31):** 템플릿 기반 즉시 발송 방식에서, 확인한 수정 계약서 PDF를
> 업로드하고 사용자가 모두싸인 편집기에서 서명란을 배치한 뒤 직접 발송하는 임베디드
> 방식으로 전환했다.

대상 API:

```text
POST /contracts/{contract_id}/signature-embedded-drafts
GET  /contracts/{contract_id}/signature
```

구현 기능:

- Modusign `mock/live` Adapter를 분리한다.
- 최신 확정 수정 계약서 대조 ID와 `confirmed=true`를 검증한다.
- OWNER와 AGENCY 각각 1명, 총 2명의 서명자를 검증한다.
- 이메일/카카오 서명 방식 형식을 검증한다.
- C-6에서 확인한 수정 계약서 PDF를 읽어 SHA-256 무결성을 검증한 뒤,
  Modusign `POST /embedded-drafts`에 Base64 PDF로 전달한다. C-7에서 PDF를 다시
  렌더링하지 않는다.
- 연락처는 외부 Adapter 전달에만 사용하고 API 응답·DB·로그에 저장하지 않는다.
- `editor_url`과 `expires_at`은 `Cache-Control: no-store` 생성 응답으로만 반환하며
  DB·로그·멱등 재생값에 저장하지 않는다.
- 외부 초안 ID·외부 문서 ID·내부 `Signature` 상태를 분리해 저장한다.
- API는 초안만 만들고 서명 요청은 자동 발송하지 않는다. 사용자가 임베디드 편집기에서
  서명란을 배치하고 직접 발송한다.

완료 조건:

- 초안 생성 성공 시 계약은 `READY_TO_SIGN`을 유지하고 Signature를
  `REQUESTING → EDITING`, 원본 상태를 `DRAFT`로 저장한다.
- `modusign_draft_id`와 `SIGNATURE_DRAFT_CREATED` 감사 이벤트를 저장한다.
- 같은 멱등 키 재호출은 민감 편집 URL을 재생·재발급하지 않고 `409`로 막는다.
- 저장된 PDF 읽기·무결성 검증 또는 외부 초안 생성 실패는 `FAILED`로 남기되 계약은
  `READY_TO_SIGN`을 유지한다.
- 실패·중단 뒤 자동 재요청하지 않는다.
- mock·HTTP MockTransport 테스트와 실제 모두싸인 PDF 초안 생성 테스트를 통과한다.

### C-8. 모두싸인 웹훅 인증·중복·순서 역전 처리

대상 API:

```text
POST /webhooks/modusign
```

구현 기능:

- `X-Modusign-Webhook-Secret`을 검증한다.
- vendor event ID 또는 payload fingerprint로 중복을 제거한다.
- 웹훅은 빠르게 `204 No Content`를 반환한다.
- 이후 비동기로 최신 모두싸인 문서 상태를 조회하고 내부 상태에 반영한다.
- 사용자가 임베디드 편집기에서 발송한 문서를 `modusign_draft_id`의 내부 Signature와
  연결하고 외부 문서 ID를 저장한다. 초안 생성 시 서명 시도 ID와 HMAC 증명 메타데이터를
  넣어, 상태 조회 결과가 해당 시도에 속하는지 확인한다.
- 과거 이벤트가 완료 상태를 되돌리지 않게 한다.

완료 조건:

- `ON_GOING`이면 Signature `EDITING → SIGNING`, Contract
  `READY_TO_SIGN → SIGNING`을 반영하고, `COMPLETED → SIGNED`를 처리한다.
- `COMPLETED`가 시작 이벤트보다 먼저 처리되면 최신 문서 상태를 기준으로
  `EDITING/READY_TO_SIGN → COMPLETED/SIGNED`를 원자적으로 보정한다.
- `ABORTED`/`PROCESSING_FAILED`면 `SIGNING → READY_TO_SIGN`으로 되돌린다.
- 중복 웹훅은 새 이벤트나 중복 상태 변경을 만들지 않는다.
- 웹훅 중복·순서 역전·실패 시나리오 테스트를 통과한다.

### C-9. 만료 D-day와 재계약 의사결정

대상 API:

```text
PUT /contracts/{contract_id}/renewal-decision
```

구현 기능:

- `Asia/Seoul` 기준으로 계약 만료 D-30, 해지 통보기한 D-14, 자동갱신 D-7을 계산한다.
- 검토 기간에만 `RENEW_SAME_TERMS`, `RENEW_WITH_CHANGES`, `TERMINATE` 중 하나를 저장한다.
- 조건 변경을 선택하면 이전에 거절되었거나 원안 유지된 ReviewItem ID를 반환한다.

완료 조건:

- 선택 저장만 수행하며 새 계약·조정·서명 요청을 자동 생성하지 않는다.
- 같은 선택 반복 저장은 기존 시각과 응답을 재사용한다.
- 다른 선택으로 바꿀 때만 `RENEWAL_DECISION_SAVED` 이벤트를 추가한다.
- D-30/D-14/D-7 경계 날짜 테스트를 통과한다.

### C-10. 계약 대시보드 집계

대상 API:

```text
GET /dashboard
```

구현 기능:

- 전체/서명 중/이행 중/완료 계약 수
- 만료 임박 계약 수
- 미해결 검토 신호 수
- 조정 요청·합의·거절 조항 수
- 이행 대기·제출·승인 수
- 총 약정액과 지급 조건 충족 금액
- 최빈 미해결 신호 유형

완료 조건:

- 같은 조정 조항이나 계약이 중복 집계되지 않는다.
- `RENEWAL_DUE`는 이행 중 계약으로 집계한다.
- B가 검증·승격한 canonical `total_amount`만 금액 집계에 사용한다.
- 실제 지급액·광고 성과·법적 이행 여부를 지표로 표현하지 않는다.

### C-11. C 담당 P0 통합 테스트 및 E2E

대표 E2E 흐름:

```text
계약 생성
→ B의 분석 완료·ReviewItem 준비
→ 조정 요청 발송
→ 대행사 공개 응답
→ 최종 확정
→ 수정 계약서 업로드·대조·확인
→ 모두싸인 임베디드 초안·사용자 발송·웹훅 완료
→ 재계약 신호 및 대시보드 반영
```

필수 테스트:

- 소유권·공개 토큰 scope·만료
- 멱등 키 재시도
- 조정 응답 중복 제출
- 상태 전이 거부
- 모두싸인 웹훅 중복/순서 역전
- D-day 경계
- 대시보드 distinct 집계

## B와의 의존성

B와의 의존성은 세 가지로 정리됩니다. B가 제공하는 `ReviewItem`, 검증된 계약 canonical 값, 공통 repository/AuditEvent 기반을 C가 소비합니다. 반대로 B는 계약 상태를 직접 바꾸지 않고 C의 상태 전이 서비스를 사용해야 합니다. 그래서 C-1을 가장 먼저 만들고, B 결과가 없는 구간은 fixture로 개발해두는 방식이 가장 효율적입니다.

### B가 C에 제공해야 하는 것

| 제공 항목 | C에서 사용하는 기능 |
| --- | --- |
| `ReviewItem` 및 선택 상태 | 조정 초안 생성, 발송 항목 동결, 최종 조정 확정 |
| 검증된 canonical 계약 값 | 계약 상세, 수정 계약서 대조 기준, D-day, 대시보드 금액 집계 |
| 공통 repository와 `AuditEvent` 트랜잭션 | 계약·조정·서명·재계약 상태 변경 기록 |
| 역제안 비교 서비스 | 소유자용 조정 상세의 비교 설명 |

### C가 B에 제공해야 하는 것

| 제공 항목 | B에서 사용하는 기능 |
| --- | --- |
| 계약 상태 전이 서비스 | 분석 시작·완료·실패 시 `DRAFT/ANALYZING/REVIEW_REQUIRED` 상태 반영 |
| 계약·조정·서명 상태 | 대표 이행 항목 노출 조건, 분석/조정 결과 연결 |
| 대행사 응답 원본 | B의 역제안 비교 서비스 입력 |

## 병렬 개발 방법

- C-1~C-3은 B의 실제 AI 결과 없이 먼저 구현한다.
- C-4~C-6은 고정 `ReviewItem` fixture와 가짜 역제안 비교 서비스로 개발한다.
- C-7~C-8은 Modusign mock Adapter로 임베디드 초안·상태 전이·웹훅 테스트를 먼저
  완료하고, live 모드에서는 발송 없는 초안 생성부터 검증한다.
- B의 실제 분석·추출 결과가 준비되면 fixture를 실제 repository 조회로 교체하고 통합 테스트를 수행한다.
