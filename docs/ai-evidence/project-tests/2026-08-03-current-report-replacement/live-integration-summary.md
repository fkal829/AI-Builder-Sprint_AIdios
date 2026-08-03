# 현재 광고성과 PDF 실제 Upstage 연동 결과

2026-08-03 KST에 저장소의 exact SHA fixture를 프로덕션 Adapter로 실행했다. 공개 증빙에는
API key, Authorization, 리포트 원문, `source_text`, 외부 원시 응답을 넣지 않았다.

| 항목 | 결과 |
| --- | --- |
| 모드 | `LIVE_CURRENT_PERFORMANCE_REPORT` |
| 파일 SHA-256 | `4ba0dbc5d1c2283b21feb81e668a098e1f0a0c5fff65c8c7943a9362ea255f3f` |
| Document Parse | `document-parse-260630`, 3/3페이지 |
| Solar | `solar-pro3`, `performance-report-metrics-v3` |
| 직접 근거 확인 | 4/4 `VERIFIED`: 광고비·노출·클릭·게시물 수, 모두 1페이지 근거 |
| 안전 미확정 | 6/6 `NOT_FOUND`: 좋아요·댓글·도달·저장·공유·전체 팔로워 순증 |
| 전체 기대 안전 조건 | 10/10 통과 |

표 헤더와 합계 값이 분리된 지표 및 Instagram 한정 도달을 전체 합계로 추정하지 않았다.
직접 근거가 없는 값은 사용자 확인 입력으로 남기고, CTR·CPC·반응률은 확인된 정수에서
서버 코드가 계산한다. 성공 JSON은 [live-result.json](live-result.json), 실패부터 개선까지의
과정은 [live-attempts.md](live-attempts.md)에 보관한다.

이 검증은 exact PDF의 Document Parse·Solar Adapter 통합을 입증한다. 별도로 보존된
2026-08-01 로컬 FastAPI·live Supabase 수직 E2E는 저장·멱등·정리를 입증한다. 이번 실행은
Supabase에 데이터를 생성하지 않았고 배포 FastAPI 전체 E2E를 다시 실행한 것은 아니다.
