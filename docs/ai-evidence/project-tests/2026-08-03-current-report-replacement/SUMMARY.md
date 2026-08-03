# 2026-08-03 광고성과 리포트 fixture 교체 검증

## 결론

제품 기준 커밋 `d3af764db180fc85ed5ecc5c4e3d0abc40497c8f` 위의 현재 작업 트리에서
구 8개 지표 광고 리포트를 3페이지·10개 후보의
`브릿지웨이브_2026-07_광고성과리포트.pdf`로 교체했다. 새 PDF의 SHA-256·페이지 수·
기대 근거·현재 `performance-report-metrics-v3` 스키마를 자동 테스트로 고정했다.
그 뒤 exact SHA PDF를 실제 Upstage Document Parse·Solar에 보내 기대 안전 조건 10/10을
확인했고, 백엔드·프론트 전체 자동 검증도 통과했다.

## 교체 범위

- 구 `브릿지웨이브_7월_광고리포트.pdf`, 전용 생성기와 이미지 자산을 활성 fixture에서 제거
- 새 PDF와 `expected-extraction.json`의 10개 후보·3페이지·SHA-256 연결
- 전 매체 합계가 없는 팔로워 순증은 추정하지 않고 `NOT_FOUND`
- 표 합계 지표와 Instagram 한정 도달은 원문만 보존한 값 `null`의 `NEEDS_CHECK`
- 프론트 mock 파일명·hash·추출 후보·7월 집계값 갱신
- 명시적 live runner의 다음 실행 범위를 8개에서 10개 후보로 확장
- 현재 fixture 전용 live runner와 민감정보 없는 실패 코드 추가
- 원문 근거 실패 시 1회 교정하고, 그래도 원문에 없는 개별 후보만 `NOT_FOUND`로 강등
- OpenAPI·API 문서·AI_USAGE의 현재 프롬프트 버전을 v3로 정렬

## 결과

| 검증 | 결과 | 산출물 |
| --- | --- | --- |
| 백엔드 pytest | 850 passed, 실패·오류·skip 0 | [pytest-full.txt](pytest-full.txt), [pytest-junit.xml](pytest-junit.xml) |
| Ruff | 진단 0건 | [ruff-check.json](ruff-check.json) |
| 오프라인 고정 계약 평가 | 10건, 선언 목표 전부 통과 | [offline-evaluation.json](offline-evaluation.json) |
| 프론트 소스 회귀 테스트 | 36 passed, 실패·skip 0 | [frontend-tests.txt](frontend-tests.txt) |
| 프론트 ESLint | 종료 코드 0 | [frontend-lint.txt](frontend-lint.txt) |
| Next.js production build | 컴파일·TypeScript·정적 페이지 생성 성공 | [frontend-build.txt](frontend-build.txt) |
| 새 PDF fixture 계약 | SHA·3페이지·근거·파생값 테스트 2건 통과 | `test_performance_demo_fixture.py` |
| 새 PDF Upstage live | exact SHA·Parse 3페이지·10개 기대 안전 조건 통과 | [live-integration-summary.md](live-integration-summary.md), [live-result.json](live-result.json) |

## 재현 범위

- `SUPABASE_MODE=mock`, `UPSTAGE_MODE=mock`, `MODUSIGN_MODE=mock`
- 백엔드 전체 테스트는 `env -i`로 로컬 `.env`를 읽지 않게 격리했다.
- 프론트 build는 `.env.local` 존재를 감지했지만 파일 내용·환경변수·비밀값을 기록하지 않았다.
- 첫 build는 샌드박스의 Google Fonts 연결 차단으로 실패했다. 같은 명령을 네트워크 허용
  환경에서 다시 실행해 성공했고 최종 성공 출력만 보관했다.
- JUnit의 로컬 hostname과 pytest 출력의 절대 경로는 제출 전 제거했다.
- fixture는 문서 내부에 가상 데이터임을 명시한 시연 자료다.
- live 성공 전 5회 실패를 숨기지 않고 [live-attempts.md](live-attempts.md)에 원인 코드와
  개선 단계를 기록했다. 전체 실행 합계는 Document Parse 6회, Solar 9회다.

세부 버전은 [environment.txt](environment.txt), 검증 대상은
[source-state.txt](source-state.txt), 파일 무결성은 `SHA256SUMS.txt`에서 확인한다.
