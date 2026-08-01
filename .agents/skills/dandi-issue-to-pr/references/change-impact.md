# 변경 영향 및 검증표

요청된 변경과 관련된 행만 사용한다. 아래 저장소 파일을 진실 소스로 사용하고, 스키마나
상태 값을 이 Skill에 복제하지 않는다.

| 변경 유형 | 먼저 읽을 문서 | 필요한 검증 |
| --- | --- | --- |
| 제품 또는 P0 범위 | `docs/기획안.md`, `docs/product-scope.md`, `docs/architecture.md` | 관련 테스트 및 `apps/api/tests/test_e2e_contract_lifecycle.py` |
| 공개 API 요청·응답·경로·enum | `packages/contracts/openapi/openapi.yaml`, `docs/api-명세서.md` | 공유 계약, HTTP 계약, 관련 endpoint 테스트 |
| 영속 상태 또는 상태 전이 | `docs/api-data-contract.md`, `packages/contracts/state-machines.json`, `docs/DECISIONS.md` | 새 migration, repository, 상태 머신, 멱등성 테스트 |
| 추출·검토 또는 AI 출력 | `packages/contracts/schemas/`, `fixtures/evaluation/` | 스키마, 근거 필드, 고정 평가, Adapter·service 테스트 |
| FastAPI 동작 | `apps/api/AGENTS.md`, `apps/api/pyproject.toml` | 대상 pytest와 Ruff, 필요한 경우 전체 백엔드 테스트 |
| Next.js 동작 | `apps/frontend/AGENTS.md`, 관련 `apps/frontend/node_modules/next/dist/docs/` 가이드 | 프론트엔드 테스트, lint, build, 화면 변경 스크린샷 |
| 외부 Adapter 또는 Webhook | `apps/api/.env.example`, Adapter·service 코드, 보안·멱등성 규칙 | mock 모드, 오류·마스킹, Webhook, 멱등성 테스트. 승인된 경우에만 live 검사 |
| 공개 토큰 또는 비인증 경로 | `docs/api-data-contract.md`, 공개 경로 header, 토큰 service | 만료·범위, 재실행·멱등성, 마스킹, 공개 경로 header 테스트 |

## 검증 명령

영향 범위에 비례해 검사를 선택한다. 승인 없이 의존성을 설치하거나 환경을 다시 만들지 않는다.

```bash
cd apps/api
pytest tests/<target_test>.py
ruff check app tests
pytest
```

```bash
cd apps/frontend
npm test
npm run lint
npm run build
```

여러 P0 단계를 가로지르거나 생애주기 전이를 바꾸면 다음 E2E 테스트를 실행한다.

```bash
cd apps/api
pytest tests/test_e2e_contract_lifecycle.py
```
