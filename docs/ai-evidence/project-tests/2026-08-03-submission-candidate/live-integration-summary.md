# 기존 live 연동 증빙과 이번 실행 범위

이번 제출 후보 검증은 외부 호출 없는 `AUTOMATED_OFFLINE` 실행이다. Upstage·Solar·
Supabase·모두싸인을 다시 호출하지 않았으며, 자동 테스트 성공을 live 성공으로 합치지
않는다.

| 검증 | 기록된 live 결과 | 원본 증빙 |
| --- | --- | --- |
| 계약 Parse·Extract | 합성 PDF 1건, 2페이지·31요소, 28필드 중 `VERIFIED` 27·`NEEDS_CHECK` 1 | [AI_USAGE.md](../../../../AI_USAGE.md#2026-07-30-live-확인) |
| Solar 계약 검토 문구 | 가상 계약 3건, 1건 단위 요청 3/3와 strict schema 3/3 성공 | [SOLAR_LIVE_RESULTS.md](../../../../fixtures/evaluation/SOLAR_LIVE_RESULTS.md) |
| Solar 역제안 비교 | 가상 역제안 1건, schema·근거·안전 검사 통과 | [COUNTERPROPOSAL_LIVE_RESULTS.md](../../../../fixtures/evaluation/COUNTERPROPOSAL_LIVE_RESULTS.md) |
| 광고효과 Adapter·수직 E2E | 합성 PDF, 로컬 FastAPI TCP·live Supabase·Upstage·Solar | [AI_USAGE.md](../../../../AI_USAGE.md#2026-08-01-광고효과-162165-live-수직-e2e) |

## 아직 live로 증명하지 않은 범위

- 배포 FastAPI·배포 Supabase·배포 프론트를 묶은 운영 환경 전체 E2E
- 현재 기본 4건 Solar 검토 chunk의 전체 생성 성공
- `adjustment-copy-polish-v1` 별도 외부 호출 성공
- 성과 매핑 v3의 새 `ad_spend`, `clicks`를 포함한 10개 strict 출력
- 교체한 `브릿지웨이브_2026-07_광고성과리포트.pdf`의 실제 Parse·Solar 결과
- 2026-08-02 추출 후보 격리·환불 부재 처리 수정 뒤 외부 Upstage 재호출

API key·Authorization·계약 원문·`source_text`·Storage 경로·외부 원시 응답은 공개
증빙에 포함하지 않는다.
