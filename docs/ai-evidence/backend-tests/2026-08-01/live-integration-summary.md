# 기존 live 연동 증빙 안내

이번 폴더의 `pytest`, Ruff, 오프라인 평가는 외부 호출 없는 `AUTOMATED_OFFLINE` 결과다.
실제 외부 API 결과를 자동 테스트 결과와 섞지 않기 위해, 기존 `LIVE_EXTERNAL` 증빙은
아래 원본 문서를 그대로 참조한다. 이번 작업에서는 live 호출을 다시 실행하지 않았다.

| 검증 | 기록된 결과 | 원본 증빙 |
| --- | --- | --- |
| Solar 검토 문구 | 가상 계약 3건, strict schema 3/3, 쉬운 설명·3종 문구 생성 | [SOLAR_LIVE_RESULTS.md](../../../../fixtures/evaluation/SOLAR_LIVE_RESULTS.md) |
| Solar 역제안 비교 | 가상 역제안 1건, strict schema와 근거·안전 검사 통과 | [COUNTERPROPOSAL_LIVE_RESULTS.md](../../../../fixtures/evaluation/COUNTERPROPOSAL_LIVE_RESULTS.md) |
| 광고효과 Adapter | 합성 PDF Parse → Solar, 8개 지표 근거·스키마 검증 | [AI_USAGE.md](../../../../AI_USAGE.md#2026-08-01-광고효과-162165-live-수직-e2e) |
| 광고효과 16.2~16.5 수직 E2E | 로컬 FastAPI TCP·live Supabase·Upstage·Solar, cleanup 6/6 | [AI_USAGE.md](../../../../AI_USAGE.md#2026-08-01-광고효과-162165-live-수직-e2e) |
| 공개 조정 응답 E2E | mock 기반 자동 테스트와 브라우저 체크리스트 | [e2e-public-adjustment-response.md](../../../e2e-public-adjustment-response.md) |

광고효과 live 재현 runner는
[`apps/api/evaluation/performance_e2e_live.py`](../../../../apps/api/evaluation/performance_e2e_live.py)다.
실제 실행에는 localhost 제한, 명시적 `--confirm-live`, 생성 데이터 전용 cleanup 승인이
필요하다. API key·Authorization·원문·`source_text`·Storage 경로·외부 raw 응답은 증빙에
포함하지 않는다.
