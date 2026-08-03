# 단디계약 AI 활용 증빙 색인

제출 검토는 루트 [AI_USAGE.md](../../AI_USAGE.md)에서 시작한다. 해당 문서가 채점 기준,
Workflow와 Agent 구분, 제품 AI 호출 위치, 프롬프트·안전장치, 개발 AI 설정과 효율 지표를
한 번에 연결한다.

## 최신 검증

- [2026-08-03 현재 광고성과 리포트 교체 검증](project-tests/2026-08-03-current-report-replacement/SUMMARY.md)
- [새 PDF와 기존 Upstage·Solar live 증빙의 구분](project-tests/2026-08-03-current-report-replacement/live-integration-summary.md)
- [교체 전 제출 후보 전체 자동 검증](project-tests/2026-08-03-submission-candidate/SUMMARY.md)
- [고정 가상 계약 평가 결과](../../fixtures/evaluation/RESULTS.md)
- [제출 증빙 Stop Hook](../../.agents/hooks/validate-ai-evidence.sh)과
  [공유 설정](../../.claude/settings.json)

## 증빙 구분

| 표기 | 의미 |
| --- | --- |
| `LIVE_EXTERNAL` | 실제 외부 API 호출이며 실행일·모델·프롬프트 버전·검증 범위를 함께 기록 |
| `AUTOMATED_OFFLINE` | 외부 Adapter를 mock으로 고정한 코드·스키마·상태 회귀 테스트 |
| `OFFLINE_SNAPSHOT` | 사람이 만든 정답과 고정 추출 snapshot 평가이며 실제 모델 정확도가 아님 |

`docs/ai-evidence.zip`은 이 디렉터리뿐 아니라 AI 지침·공용 Skill·Hook·평가 결과와 live
기록, README에 사용한 실제 화면을 함께 묶은 제출 편의본이다. 진실 소스는 항상 저장소의
개별 원본 파일이며 ZIP 내부 복사본은 제출 시점 탐색을 돕기 위한 것이다.
