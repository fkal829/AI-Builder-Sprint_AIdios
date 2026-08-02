# 기존 live 연동 증빙 안내

이 디렉터리의 pytest, Ruff, 프론트 테스트·lint·build와 오프라인 평가는
`AUTOMATED_OFFLINE` 결과다. 이번 실행에서는 Upstage·Solar·Supabase·모두싸인을 다시
호출하지 않았다.

| 검증 | 기록된 결과 | 원본 증빙 |
| --- | --- | --- |
| Solar 계약 검토 문구 | 가상 계약 3건, 1건 단위 요청 3/3 성공 | [SOLAR_LIVE_RESULTS.md](../../../../fixtures/evaluation/SOLAR_LIVE_RESULTS.md) |
| Solar 역제안 비교 | 가상 역제안 1건, strict schema·근거 검사 통과 | [COUNTERPROPOSAL_LIVE_RESULTS.md](../../../../fixtures/evaluation/COUNTERPROPOSAL_LIVE_RESULTS.md) |
| 계약 Parse·Extract | 합성 PDF 1건, 28필드·근거 연결·Supabase 수직 흐름 | [AI_USAGE.md](../../../../AI_USAGE.md#2026-07-30-live-확인) |
| 광고효과 Adapter·수직 E2E | 합성 PDF, 로컬 FastAPI TCP·live Supabase·Upstage·Solar | [AI_USAGE.md](../../../../AI_USAGE.md#2026-08-01-광고효과-162165-live-수직-e2e) |

현재 기본 계약 검토 chunk 크기는 4건이다. 성공한 계약 검토 live 증빙은 1건씩 보낸
3회 호출이고, 4건 chunk에서는 안전 검증 실패가 결정 규칙 기반 fallback으로 격리되는
동작을 확인했다. 4건 전체 생성 성공을 입증한 결과로 해석하지 않는다.

Solar 문구 다듬기 `adjustment-copy-polish-v1`은 자동 테스트로 API·스키마·숫자 보존·
사용자 적용 경계를 확인했지만, 별도 live 외부 호출 성공 산출물은 아직 없다.

현재 성과 매핑은 `performance-report-metrics-v2` 10개 후보다. 위 live 결과는 확장 전
v1의 8개 후보에 대한 것이며, 새 `ad_spend`와 `clicks`를 포함한 strict 출력은 별도
live 재검증 전이다. 2026-08-02 추출 후보 격리와 환불 부재 처리 수정도 고정 응답 회귀
테스트까지 확인했고 수정 후 외부 Upstage 재호출은 하지 않았다.
