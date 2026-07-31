# Shared contracts

프런트엔드와 API가 함께 지켜야 하는 안정적인 경계만 둡니다.

- `schemas/`: AI 구조화 결과와 외부 공개 payload의 JSON Schema
- `state-machines.json`: 내부 enum과 허용 상태 전환
- `openapi/`: 구현된 P0와 `planned` P2를 구분한 OpenAPI 명세 및 생성 TypeScript 타입 출력 위치

Python이나 TypeScript 런타임 비즈니스 로직은 두지 않습니다. 스키마를 변경하면 API 테스트와 프런트 타입을 같은 변경에서 갱신합니다.

## 명명 규칙

- HTTP JSON과 JSON Schema의 필드명은 `snake_case`를 사용합니다.
- 프런트엔드는 `apps/frontend/src/lib/adapter.ts` 경계에서 `camelCase`로 변환합니다.
- 저장되는 추출 결과에는 `source_page`, `source_text`, `confidence`를 함께 둡니다.
- 검토 결과는 `detection_method`가 모델을 사용할 때만 `model_confidence`를 둡니다.
- 근거를 찾지 못한 결과는 근거 필드를 `null`로 두고 `verification_status`를
  `NOT_FOUND`로 표시합니다. 근거 누락 상태인 `MISSING_EVIDENCE`는 확정값으로
  표시할 수 없습니다.
