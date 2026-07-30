# AI 사용 명세

## P0 계약 분석

4.4 분석 작업은 `apps/api/app/adapters/upstage.py`의 Upstage Adapter와
`apps/api/app/services/analysis.py`의 결정적 검증 코드로 구성한다.

| 단계 | 모드·API | 역할 |
| --- | --- | --- |
| 문서 구조 분석 | mock 또는 Upstage `POST /v1/document-digitization` | 페이지, 원문 요소, 정규화 좌표 보존 |
| 핵심 필드 추출 | mock 또는 Upstage Universal Extraction `POST /v1/information-extraction/chat/completions` | JSON Schema에 맞는 계약 필드 추출 |
| 검증·검토 | 서버 코드 | 타입, 날짜, 금액, 원문 페이지·문장, 이해조건 불일치 검증 |

live 추출 모델 alias는 `UPSTAGE_EXTRACT_MODEL=information-extract`이며 PDF 한 건을
base64 문서 항목 하나로 전송한다. 추출 요청에는 first-level scalar JSON Schema와
`location=true`, `location_granularity=element`, `confidence=true`, `split=false`를
사용한다. 별도의 자유 형식 시스템 프롬프트 대신 각 필드의 한국어 설명과 타입을
스키마에 명시한다.

Universal Extraction의 `additional_values` 좌표를 같은 페이지의 Document Parse 요소와
겹침 검증한 경우에만 해당 요소 원문을 `source_text`로 저장한다. 좌표가 맞지 않으면
값을 확정하지 않고 `MISSING_EVIDENCE`로 처리한다. Upstage의 범주형 confidence는 저장
스키마에 맞춰 `high=0.9`, `low=0.4`로 정규화한다. `low`는 원문 근거를 보존하되
`NEEDS_CHECK`로 처리한다. 이 수치는 별도 확률 보정 결과가 아니며 모델 판단의 범주를
0~1 필드에 표현하기 위한 내부 매핑이다.

## Evaluator Loop

1. Document Parse 결과와 1차 추출 결과를 Pydantic 스키마로 검증한다.
2. 누락, `NOT_FOUND`, 근거 불일치, 확인 필요 필드만 두 번째 추출 대상으로 좁힌다.
3. 작업당 Evaluator Loop는 최대 2회에서 종료한다.
4. 두 번째에도 찾지 못한 필드는 `NOT_FOUND`, 근거가 맞지 않는 값은
   `MISSING_EVIDENCE`로 저장한다.
5. 날짜·금액·비율·canonical 승격과 계약 상태 전이는 모델이 아니라 서버 코드와 DB
   트랜잭션이 처리한다.

mock 모드는 고정된 가상 계약 결과를 사용하며, 발견한 값에는 `source_page`,
`source_text`, `confidence`가 모두 포함된다. 찾지 못한 필드도 같은 공개 스키마를
사용하되 근거 필드는 `null`, confidence는 `0`이다. mock 결과를 live 연동 성과로
간주하지 않는다.

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

## 보안

- API 키는 `apps/api/.env` 또는 배포 환경의 서버 변수로만 주입한다.
- 키, Authorization 헤더, 계약 전문, 원시 모델 응답은 로그나 저장소에 남기지 않는다.
- 외부 발송, 계약 확정, 서명 요청, 증빙 승인, 재계약은 AI가 자동 실행하지 않는다.
