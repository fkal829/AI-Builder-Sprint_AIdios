# 2026-08-03 프로젝트 자동 검증 결과

## 결론

제품 코드 커밋 `e4cb13ec6fe397f44eb346a81ccfe514e1fb7de7` 기준 백엔드·프론트엔드
자동 검증은 모두 통과했다. `docs/#126/ai-usage-통합` 브랜치의 작업 트리에는 문서와
검증 산출물 변경만 있었다. 이 실행은 외부 Adapter를 호출하지 않은
`AUTOMATED_OFFLINE` 증빙이며,
실제 Upstage·Solar 연동 결과는 [live-integration-summary.md](live-integration-summary.md)와
분리한다.

## 결과

| 검증 | 결과 | 산출물 |
| --- | --- | --- |
| 백엔드 pytest | 820 passed, 실패·오류·skip 0 | [pytest-full.txt](pytest-full.txt), [pytest-junit.xml](pytest-junit.xml) |
| Ruff | 진단 0건 | [ruff-check.json](ruff-check.json) |
| 오프라인 고정 계약 평가 | 10건, 선언 목표 전부 통과 | [offline-evaluation.json](offline-evaluation.json) |
| 프론트 소스 회귀 테스트 | 35 passed, 실패 0 | [frontend-tests.txt](frontend-tests.txt) |
| 프론트 ESLint | 종료 코드 0 | [frontend-lint.txt](frontend-lint.txt) |
| Next.js 프로덕션 빌드 | 컴파일·TypeScript·정적 페이지 생성 성공 | [frontend-build.txt](frontend-build.txt) |

## 오프라인 평가

| 지표 | 결과 |
| --- | ---: |
| 핵심 필드 추출 정확도 | 96.67% (58/60) |
| 근거 페이지 연결 정확도 | 96.36% (53/55) |
| 필수 JSON 스키마 성공률 | 100% (10/10) |
| 기간·총액 불일치 탐지율 | 100% (3/3) |
| 기대 확인 신호 재현율 | 100% (16/16) |
| 근거 없는 확정 경고 | 0건 |

이 수치는 사람이 작성한 가상 계약과 고정 snapshot으로 스키마·근거·결정 규칙을
회귀 검증한 결과다. Upstage·Solar 모델의 실제 정확도 또는 운영 성능이 아니다.

## 환경과 재현 범위

- Python 3.12.13, pytest 8.4.2, Ruff 0.16.1
- Node.js 24.18.0, npm 11.16.0, Next.js 16.2.12
- `SUPABASE_MODE=mock`, `UPSTAGE_MODE=mock`, `MODUSIGN_MODE=mock`
- 백엔드는 로컬 `.env`를 읽지 않도록 격리했다.
- 프론트 빌드는 Next.js가 `.env.local` 존재를 감지했지만 파일 내용·환경 변수·비밀값은
  산출물에 기록하지 않았다.
- 프론트 빌드의 첫 샌드박스 실행은 Google Fonts 연결 차단으로 실패했고, 같은 명령을
  네트워크 허용 환경에서 다시 실행해 통과했다. 성공 로그를 산출물로 보관한다.
- fixture는 모두 가상 데이터다.
- 산출물 공개 안전을 위해 pytest 출력의 절대 작업 경로는 상대 경로로 정규화하고 JUnit의
  로컬 hostname은 `[redacted]`로 치환했다. 테스트명·건수·시간·결과는 유지했다.

세부 실행 환경은 [environment.txt](environment.txt), 산출물 무결성은
`SHA256SUMS.txt`에서 확인한다.
