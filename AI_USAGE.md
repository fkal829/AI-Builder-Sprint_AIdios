# AI 사용 명세

## P0 계약 분석

4.4 분석 작업은 `apps/api/app/adapters/upstage.py`의 Parse·Extract Adapter,
`apps/api/app/adapters/solar.py`의 Solar 검토 문구 Adapter,
`apps/api/app/services/analysis.py`의 결정적 검증 코드로 구성한다.

| 단계 | 모드·API | 역할 |
| --- | --- | --- |
| 문서 구조 분석 | mock 또는 Upstage `POST /v1/document-digitization` | 페이지, 원문 요소, 정규화 좌표 보존 |
| 핵심 필드 추출 | mock 또는 Upstage Universal Extraction `POST /v1/information-extraction/chat/completions` | JSON Schema에 맞는 계약 필드 추출 |
| 신호 판정 | 서버 코드 | 타입, 날짜, 금액, 원문 페이지·문장, 누락·불명확 표현·이해조건 불일치 검증 |
| 검토 문구 생성 | mock 또는 Solar Chat `POST /v1/chat/completions` | 항목별 쉬운 설명과 원안 수용·절충·요청 문구 생성 |

live 추출 모델 alias는 `UPSTAGE_EXTRACT_MODEL=information-extract`이며 PDF 한 건을
base64 문서 항목 하나로 전송한다. 추출 요청에는 first-level scalar JSON Schema와
`location=true`, `location_granularity=element`, `confidence=true`, `split=false`를
사용한다. 별도의 자유 형식 시스템 프롬프트 대신 각 필드의 한국어 설명과 타입을
스키마에 명시한다.

live Parse·Extract는 모델, 시작 시각, 성공·실패 상태, HTTP status, 지연 시간,
스키마 검증 성공 여부만 구조화 로그에 남긴다. API key, 계약 원문·파일, data URL,
전체 요청·응답 payload는 로그에 남기지 않는다.

Universal Extraction의 `additional_values` 좌표를 같은 페이지의 Document Parse 요소와
겹침 검증한 경우에만 해당 요소 원문을 `source_text`로 저장한다. 좌표가 맞지 않으면
값을 확정하지 않고 `MISSING_EVIDENCE`로 처리한다. Upstage의 범주형 confidence는 저장
스키마에 맞춰 `high=0.9`, `low=0.4`로 정규화한다. `low`는 원문 근거를 보존하되
`NEEDS_CHECK`로 처리한다. 이 수치는 별도 확률 보정 결과가 아니며 모델 판단의 범주를
0~1 필드에 표현하기 위한 내부 매핑이다.

## Solar 검토 문구

live 모드는 `UPSTAGE_SOLAR_MODEL=solar-pro3`,
`UPSTAGE_SOLAR_TIMEOUT_SECONDS=120`을 기본값으로 사용한다. 서버가 먼저 누락,
불일치, 명시적인 모호 표현과 책임 확인 후보를 만든 뒤 필요한 최소 원문과 사용자
이해조건만 Solar에 전달한다. Solar는 신호 종류, 원문 근거, 날짜·금액 계산, 상태,
사용자 선택을 변경할 수 없고 다음 필드만 생성한다.

- `plain_explanation`
- `suggestion_accept`
- `suggestion_compromise`
- `suggestion_request`
- 비보정 자기평가값과 모델 한계

응답은 `contract-review-copy-v1` 프롬프트와 strict JSON Schema로 요청하고 별도의
Pydantic 스키마로 다시 검증한다. 검토 항목은 실제 live 검증에서 성공한 기본 1건
chunk로 순차 호출한다. 일부 chunk가 성공했더라도 전체 입력 UUID의 개수·중복·순서가
일치해야만 결과를 반환하며, 뒤 chunk가 실패하면 앞 결과도 저장하지 않고 분석 전체를
실패 처리한다. 세 문구가 같거나, 금지된 단정 표현 또는 입력 근거에 없는 숫자가 있어도
저장하지 않는다. 결정 규칙과 Solar 문구가 함께 사용된 항목은
`detection_method=HYBRID`다.

Solar Chat API는 보정된 confidence를 제공하지 않는다. 공개 계약의
`model_confidence`에는 Solar가 반환한 비보정 자기평가값을 넣고,
`model_limitations`에 이것이 법적 판단 정확도나 `source_confidence`가 아님을
명시한다. `source_confidence`는 기존 원문 추출 근거 값으로 유지한다.

Solar timeout, HTTP 오류, 잘못된 JSON, 스키마 오류, 출력 ID 불일치는 고정 문구로
조용히 대체하지 않고 해당 분석을 `FAILED/ANALYSIS_SCHEMA_INVALID`로 종료한다.
`429`와 일시적인 전송·서버 오류만 한 번 재시도한다. 이 호출은 추출 Evaluator Loop의
`attempt_count`에 포함하지 않는다.

## Solar 역제안 비교

5.2 소유자용 조정 상세 조회는 `apps/api/app/services/counterproposal.py`의
`CounterproposalComparator`를 사용한다. 수락·거절 설명은 서버 코드가 결정적으로
만들고, 역제안만 저장된 실제 요청 문구, 대행사의 역제안 문구와 사유를 Solar Chat에
전달한다.

live 요청은 `counterproposal-comparison-v1` 프롬프트와 strict JSON Schema를 사용해
다음 필드만 생성한다.

- `changed_summary`
- `remaining_checks`
- `final_confirmation`

출력 UUID는 입력 UUID와 정확히 일치해야 하며 빈 확인사항, 추가 필드, 금지된 법적·
신뢰성 단정과 입력에 없는 숫자는 거부한다. 비교 결과는 조정 상태를 변경하거나
역제안을 자동 수락·재요청하지 않는다. Solar 요청 또는 검증 실패는
`502 ANALYSIS_SCHEMA_INVALID`로 반환하며 먼저 저장된 대행사 응답은 유지한다.
mock 결과는 실제 요청·역제안·사유를 반영한 규칙 기반 예시이고 실제 Solar 응답이
아니다.

2026-07-31 09:17:58 UTC에 가상 역제안 한 건을 실제 `solar-pro3`로 호출해
`counterproposal-comparison-v1` strict JSON Schema 검증, 달라진 점·남은
확인사항·최종 확인 생성과 입력 근거 검사를 모두 통과했다. 결과와 재현 명령은
`fixtures/evaluation/COUNTERPROPOSAL_LIVE_RESULTS.md`에 기록한다.

## Evaluator Loop

1. 선택한 주 계약 문서와 지원 문서를 각각 한 번 Parse한다.
2. 1라운드에서 모든 선택 문서의 추출 결과를 Pydantic 스키마로 검증한다.
3. 문서별 누락, `NOT_FOUND`, 근거 불일치, 확인 필요 필드만 2라운드 재추출 대상으로
   좁힌다.
4. 지원 문서 수와 관계없이 작업의 Evaluator `attempt_count`는 최대 2라운드다. 한
   라운드에는 선택 문서별 추출 호출이 하나씩 포함될 수 있다.
5. 두 번째에도 찾지 못한 필드는 `NOT_FOUND`, 근거가 맞지 않는 값은
   `MISSING_EVIDENCE`로 저장한다.
6. 날짜·금액·비율·canonical 승격과 계약 상태 전이는 모델이 아니라 서버 코드와 DB
   트랜잭션이 처리한다.

mock 모드는 고정된 가상 계약 결과를 사용하며, 발견한 값에는 `source_page`,
`source_text`, `confidence`가 모두 포함된다. 찾지 못한 필드도 같은 공개 스키마를
사용하되 근거 필드는 `null`, confidence는 `0`이다. mock 결과를 live 연동 성과로
간주하지 않는다.

mock Solar 문구는 항목별 필드와 신호를 반영하지만 실제 모델 응답이 아니며
`model_limitations`에도 이 사실을 표시한다.

## 비동기 작업 복구 경계

HTTP 진입점의 FastAPI `BackgroundTasks`는 빠른 mock/demo 처리를 위한 보조 경로이며,
내구성 복구는 별도 worker가 맡는다. 4.5 최근 분석 조회는 상태 변경이나 AI 호출을
일으키지 않는 순수 조회다.

`python -m app.workers.analysis_recovery --once`는 설정한 cutoff보다 오래된 `QUEUED`
작업을 `created_at ASC, id ASC` 순서로 최대 batch만 읽고, 저장된 `owner_id`와 `task_id`로
기존 `AnalysisService.process`를 호출한다. 실제 claim은 기존의 조건부
`QUEUED → PROCESSING` 전이인 `mark_analysis_processing`이 수행하므로, 여러 worker가
같은 작업을 읽어도 한 worker만 처리한다. worker 로그에는 작업 UUID, 개수와 오류 유형만
남기며 계약 원문, 공개 토큰, 키, URL을 남기지 않는다.

별도 `ANALYSIS_RECOVERY_PROCESSING_TIMEOUT_SECONDS`(기본 14,400초)는 Upstage Parse·Extract,
Solar 실행 시간보다 충분히 긴 처리 제한이다. worker는 `updated_at`이 이 제한보다
오래된 `PROCESSING` 행만 `FOR UPDATE SKIP LOCKED`로 잠그고 cutoff과 상태를 다시
확인한다. 확인된 행은 `FAILED/DOCUMENT_PARSE_FAILED`, 주 계약 문서와 선택 자료
`parse_status=FAILED`, `ANALYSIS_FAILED` 감사 이벤트로 한 DB 트랜잭션에 전이한다.
계약 상태는 `ANALYZING`을 유지하고 새 멱등 키로 사용자가 명시적으로 재시작해야
하며, worker가 자동으로 무한 재시도하지 않는다.

운영에서는 API 프로세스와 별도의 worker를 실행한다.

```bash
# 한 번 실행
python -m app.workers.analysis_recovery --once

# 장기 실행 (기본 30초 간격)
python -m app.workers.analysis_recovery --loop
```

`ANALYSIS_RECOVERY_STALE_AFTER_SECONDS`(기본 60),
`ANALYSIS_RECOVERY_PROCESSING_TIMEOUT_SECONDS`(기본 14,400),
`ANALYSIS_RECOVERY_BATCH_SIZE`(기본 10),
`ANALYSIS_RECOVERY_INTERVAL_SECONDS`(기본 30)로 범위를 조절한다. mock/live repository의
cutoff·정렬·limit·소유자 전달과 동시 claim·timeout 전이 안전성은 자동 테스트로
검증했고, 실제 Supabase
환경에서는 마이그레이션 적용 뒤 worker 배포가 필요하다.

## 고정 계약 10건 오프라인 평가

`fixtures/evaluation/cases`의 가상 계약 10건은 계약 원문, 사용자가 이해한 조건
5문항, 오프라인 추출 스냅샷, 사람이 검증한 정답과 기대 확인 신호를 함께 보관한다.
`apps/api/evaluation` 실행기는 외부 네트워크 없이 현재 Pydantic 스키마, 원문 근거
검증과 결정적 확인 신호 생성 코드를 평가한다.

2026-07-31 오프라인 기준선 결과는 핵심 필드 추출 96.67%, 근거 페이지 연결
96.36%, 필수 JSON 스키마 100%, 기간·총액 불일치 탐지 100%, 근거 없는 확정 경고
0건이다. 전체 기대 확인 신호 16건도 모두 재현했다. 상세 분모와 실행 방법은
`fixtures/evaluation/RESULTS.md`에 기록한다.

이 수치는 `OFFLINE_SNAPSHOT` 회귀 결과이며 실제 Upstage·Solar 모델 정확도가 아니다.
live 결과는 같은 계약 원문을 실제 Adapter로 실행한 뒤 모델·프롬프트 버전·실행일과
함께 별도로 공개한다.

## 2026-07-31 Solar 검토 문구 live 확인

고정 평가의 가상 계약 중 총액 불일치, 모호한 산출물 수량, 촬영 안전 책임 3건으로
Solar `POST /v1/chat/completions`를 실제 호출했다. 요청 모델은 `solar-pro3`,
프롬프트 버전은 `contract-review-copy-v1`이다.

- 입력을 한 건씩 분리한 실제 요청 3회 성공
- 응답 3건 모두 strict JSON Schema와 Pydantic 스키마 검증 통과
- 쉬운 설명 3/3 생성
- 원안 수용·절충·요청 문구 3종 3/3 생성 및 항목별 상호 구분 확인
- 입력 ID 일치, 입력에 없는 숫자, 금지 단정 표현 검사 통과
- 기본 1건 chunk 전략을 production과 평가 실행기에 함께 적용한 뒤
  2026-07-31 09:05:34 UTC에 외부 요청 3회를 다시 실행해 모두 성공

최초 3건 배치 요청은 120초 timeout 뒤 한 번 재시도했지만 `ReadTimeout`으로
실패했다. 한 건씩 나눈 호출은 모두 성공했으므로 실제 endpoint와 응답 계약 연동은
확인했지만, 3건 비스트리밍 배치가 현재 timeout 안에서 안정적이라는 증거는 아니다.
검증된 생성 문구와 실패·재시도 내역은
`fixtures/evaluation/SOLAR_LIVE_RESULTS.md`에 기록한다.

## 2026-07-30 live 확인

가상 샘플 `apps/frontend/public/sample-contract.pdf`로 명시적 live 확인을 수행했다.

- Document Parse: 성공, 모델 `document-parse-260128`, 2페이지, 원문 요소 31개
- 소수 필드 사전 확인: 기간 시작일·총액·환불조건 3개 모두
  `source_page`, `source_text`, `confidence`를 가진 `VERIFIED`
- 전체 live 분석: 대상 필드 28개, Evaluator 2회, 최종 `VERIFIED` 27개,
  원문 근거를 보존한 `NEEDS_CHECK` 1개
- 근거 필드가 연결된 추출값: 28개, 생성된 검토 항목: 5개
- Supabase service-level 수직 흐름: Auth 테스트 사용자 → 계약 생성 → PDF private
  Storage 업로드 → 5문항 저장 → 분석 접수·완료 → signed URL 발급 성공
- 실제 Supabase access token을 사용한 FastAPI HTTP 수직 흐름:
  계약 생성 `201` → 업로드 `201` → 5문항 저장 `200` → 분석 접수 `202 QUEUED` →
  최종 `COMPLETED` → 원문 접근 `200`
- 최종 계약 상태: `REVIEW_REQUIRED`; 분석 접수·완료 감사 이벤트 저장 확인
- 이 샘플은 산출물 제목 필드와 기한이 동일한 원문 요소에 있지 않아 대표
  `Obligation`을 임의 생성하지 않음

위 확인은 한 샘플의 Adapter·HTTP API·원격 영속성 연동 결과이며 정확도 평가 지표가
아니다. 기획안의 목표 지표는 `fixtures/evaluation/`의 고정 10건 평가를 실행한 뒤
별도로 기록한다.

이 2026-07-30 확인 자체는 Solar 검토 문구 단계가 추가되기 전 수행한 기록이다.
Solar `/v1/chat/completions`의 새 live 성공 근거는 위 2026-07-31 기록을 따른다.

## 보안

- API 키는 `apps/api/.env` 또는 배포 환경의 서버 변수로만 주입한다.
- 키, Authorization 헤더, 계약 전문, 원시 모델 응답은 로그나 저장소에 남기지 않는다.
- Solar 실행 로그에는 프롬프트 버전, 모델 ID, 시작 시각, 성공·실패, 항목 수,
  지연시간, 스키마 검증 여부만 남긴다.
- 외부 발송, 계약 확정, 서명 요청, 증빙 승인, 재계약은 AI가 자동 실행하지 않는다.
