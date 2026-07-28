# Shared contracts

프런트엔드와 API가 함께 지켜야 하는 안정적인 경계만 둡니다.

- `schemas/`: AI 구조화 결과와 외부 공개 payload의 JSON Schema
- `state-machines.json`: 내부 enum과 허용 상태 전환
- `openapi/`: FastAPI에서 생성한 OpenAPI 또는 TypeScript 타입의 출력 위치

Python이나 TypeScript 런타임 비즈니스 로직은 두지 않습니다. 스키마를 변경하면 API 테스트와 프런트 타입을 같은 변경에서 갱신합니다.
