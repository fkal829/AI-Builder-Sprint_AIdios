# Solar 역제안 비교 live 연동 결과

2026-07-31에 실제 사업자 정보가 아닌 고정 가상 역제안 한 건으로 Upstage Solar Chat
API를 호출했다. 아래 내용은 원시 HTTP 응답이 아니라 Adapter의 보안 검사와 Pydantic
스키마를 통과한 필드만 기록한 결과다.

| 항목 | 결과 |
| --- | --- |
| 완료 시각 | 2026-07-31 09:17:58 UTC (18:17:58 KST) |
| endpoint | `POST /v1/chat/completions` |
| 요청 모델 | `solar-pro3` |
| 프롬프트 버전 | `counterproposal-comparison-v1` |
| 실제 요청 수 | 1회, 가상 역제안 1건 |
| 응답 스키마 | 1/1 통과 |
| 달라진 점 | 1/1 생성 |
| 남은 확인사항 | 1/1 생성 |
| 최종 확인 | 1/1 생성 |

검증된 결과는 원 요청의 위약금 20% 삭제와 역제안의 10% 유지가 어떻게 다른지
구분했다. 남은 확인사항으로 적용 시점·계산 기준·대상 조항·추가 비용 여부를 제시했고,
10% 채택과 조항 삭제 중 사용자가 최종 확인하도록 안내했다. 입력 ID 일치, 추가 필드,
빈 확인사항, 금지 단정 표현, 입력에 없는 숫자 검사를 모두 통과했다. 이 호출은
조정 상태를 변경하거나 역제안을 자동 수락하지 않았다.

## 재현 방법

```bash
cd apps/api
.venv/bin/python -m evaluation.counterproposal_live --confirm-live
.venv/bin/python -m pytest \
  tests/test_counterproposal.py \
  tests/test_counterproposal_live_evaluation.py \
  tests/test_solar_adapter.py -q
```

일반 `pytest`는 외부 Solar를 호출하지 않는다.
