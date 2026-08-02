# AI evaluation fixtures

`cases/`에는 기획안 7.4의 고정 가상 계약 10건을 둔다. 실제 사업자·계약·개인정보를
사용하지 않는다.

1. 기간·총액 불일치
2. 환불 설명 누락
3. 자동갱신
4. 모호한 산출물
5. 빈칸 다수
6. 위약금 조건
7. 촬영 안전·손해 책임
8. 콘텐츠 권리
9. 정상 계약
10. 낮은 OCR 품질

각 JSON은 다음을 하나의 변경 단위로 유지한다.

- `contract_pages`: 사람이 작성한 가상 계약 원문과 1-based 페이지
- `understood_terms`: 사용자가 이해한 기간·월 금액·총액·환불·중도해지 5문항
- `observed_terms`: 외부 네트워크 없이 재현할 오프라인 추출 스냅샷
- `expected_terms`: 사람이 원문을 보고 검증한 필드 값과 페이지 근거
- `expected_signals`: 현재 결정적 검토 코드가 만들어야 하는 확인 신호
- `mismatch_targets`: 기간·총액 불일치 탐지율의 분모가 되는 필드

각 케이스에서 해당 시나리오를 대표하는 핵심 필드 6개를 평가하며 전체 분모는
60개다. 계약 원문에 없는 값도 `NOT_FOUND` 정답으로 포함한다.

## 실행

```bash
cd apps/api
.venv/bin/python -m evaluation
.venv/bin/python -m evaluation --format markdown
.venv/bin/python -m pytest tests/test_evaluation_fixtures.py -q
```

`RESULTS.md`는 실행기가 생성하는 Markdown과 정확히 일치해야 하며 테스트가 이를
검증한다.

`performance-metrics/`는 P2 성과 리포트 매핑의 별도 가상 fixture다. 원문에
`게시물 수`가 없을 때의 `NOT_FOUND`/`null`과 명시적인 `0`을 서로 다른
경계로 고정한다. 이 fixture는 기존 계약 10건 평가 분모에 포함하지 않는다.

Solar 검토 문구 live 검증은 외부 호출과 비용이 발생하므로 일반 평가와 분리한다.
`apps/api/.env`에 `UPSTAGE_API_KEY`를 설정하고 명시적으로 실행한다.
실행기는 production과 같은 `SolarReviewAdapter` 경계를 사용한다. 현재 기본 chunk는
최대 4건이며, 전체 출력 ID와 순서가 일치한 경우에만 보고서를 생성한다. 2026-07-31에
기록한 성공 결과는 당시 기본이던 1건 chunk로 세 입력을 각각 호출한 결과다.

```bash
cd apps/api
.venv/bin/python -m evaluation.solar_live --confirm-live
.venv/bin/python -m evaluation.counterproposal_live --confirm-live
```

2026-07-31 실제 호출의 검증 문구와 실패·재시도 결과는
`SOLAR_LIVE_RESULTS.md`, 역제안 비교 결과는
`COUNTERPROPOSAL_LIVE_RESULTS.md`에 기록되어 있다.

## 지표 정의

- 핵심 필드 추출 정확도: 정답 필드 값과 오프라인 추출 값의 exact match 비율
- 근거 페이지 연결 정확도: 정답에 페이지가 있는 필드 중 추출 페이지가 일치한 비율
- 필수 JSON 스키마 성공률: 10개 JSON이 평가·분석 Pydantic 스키마를 통과한 비율
- 기간·총액 불일치 탐지율: `mismatch_targets` 중 `MISMATCH`가 생성된 비율
- 근거 없는 확정 경고: `VERIFIED`·`NEEDS_CHECK` 경고에 원문 근거가 빠진 개수

이 평가는 mock 결과를 live 성능으로 포장하지 않기 위한 `OFFLINE_SNAPSHOT` 회귀
기준선이다. 실제 Upstage·Solar 정확도는 같은 원문을 live Adapter로 실행한 별도
결과에 날짜, 모델, 프롬프트 버전과 함께 기록한다.
