# 2026-08-03 제출 후보 자동 검증 결과

## 결론

제품 코드 커밋 `d3af764db180fc85ed5ecc5c4e3d0abc40497c8f` 기준 백엔드·프론트엔드
자동 검증은 모두 통과했다. 제품 런타임 경로 `apps/`, `packages/`, `supabase/`는 검증
시점에 해당 커밋과 일치했고, 작업 트리의 별도 변경은 제출용 `AI_USAGE.md`, `README.md`,
`docs/ai-evidence/`와 개발 보조 설정 `.claude/`, `.agents/hooks/`에 한정됐다.

이 실행은 외부 Adapter를 호출하지 않은 `AUTOMATED_OFFLINE` 증빙이다. 실제
Upstage·Solar 연동은 [live-integration-summary.md](live-integration-summary.md)에
기존 live 원본과 미검증 범위를 분리해 연결한다.

## 결과

| 검증 | 결과 | 산출물 |
| --- | --- | --- |
| 백엔드 pytest | 835 passed, 실패·오류·skip 0 | [pytest-full.txt](pytest-full.txt), [pytest-junit.xml](pytest-junit.xml) |
| Ruff | 진단 0건 | [ruff-check.json](ruff-check.json) |
| 오프라인 고정 계약 평가 | 10건, 선언 목표 전부 통과 | [offline-evaluation.json](offline-evaluation.json) |
| 프론트 소스 회귀 테스트 | 36 passed, 실패·skip 0 | [frontend-tests.txt](frontend-tests.txt) |
| 프론트 ESLint | 종료 코드 0 | [frontend-lint.txt](frontend-lint.txt) |
| Next.js production build | 컴파일·TypeScript·정적 페이지 생성 성공 | [frontend-build.txt](frontend-build.txt) |
| 제출 증빙 Stop Hook | shell 문법·현재 증빙 검증 통과 | [hook-check.txt](hook-check.txt) |

## 오프라인 AI 평가

| 지표 | 결과 |
| --- | ---: |
| 핵심 필드 추출 정확도 | 96.67% (58/60) |
| 근거 페이지 연결 정확도 | 96.36% (53/55) |
| 필수 JSON 스키마 성공률 | 100% (10/10) |
| 기간·총액 불일치 탐지율 | 100% (3/3) |
| 기대 확인 신호 재현율 | 100% (16/16) |
| 근거 없는 확정 경고 | 0건 |

이 수치는 사람이 작성한 가상 계약과 고정 snapshot으로 스키마·근거·결정 규칙을 회귀
검증한 결과다. Upstage·Solar 모델의 실제 정확도 또는 운영 성능이 아니다.

## 재현 범위

- `SUPABASE_MODE=mock`, `UPSTAGE_MODE=mock`, `MODUSIGN_MODE=mock`
- 백엔드 명령은 `env -i`로 로컬 `.env`를 읽지 않게 격리했다.
- 프론트 build는 `.env.local` 존재를 감지했지만 파일 내용·환경변수·비밀값을 산출물에
  기록하지 않았다.
- 첫 build는 샌드박스의 Google Fonts 연결 차단으로 실패했다. 동일 명령을 네트워크 허용
  환경에서 다시 실행해 성공했고 최종 성공 출력을 보관했다.
- fixture는 모두 가상 데이터다.
- JUnit의 로컬 hostname은 제출 전 `[redacted]`로 치환하고 무결성 hash를 생성한다.

세부 버전은 [environment.txt](environment.txt), 검증 대상은
[source-state.txt](source-state.txt), 파일 무결성은 `SHA256SUMS.txt`에서 확인한다.
