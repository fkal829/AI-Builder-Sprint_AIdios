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

### 2026-08-02 `05-many-blanks` live 필드 격리 문제 발견

고정 평가 케이스 `05-many-blanks`를 Universal Extraction live로 호출하던 중,
모델이 요청된 날짜 필드 하나에 ISO date 형식이 아닌 값을 반환했다. 응답 JSON
객체와 나머지 필드는 유효했지만, 단일 후보의 Pydantic 검증 예외가 호출 전체로
전파돼 정상 후보를 포함한 6개 추출 결과가 모두 폐기되는 문제를 확인했다.

응답이 JSON이 아니거나 최상위 객체가 아닌 경우, 또는 요청하지 않은 필드가 포함된
구조 오류는 기존처럼 해당 추출 호출 전체를 실패 처리한다. 반면 요청한 필드 하나의
값만 서버의 타입·형식·enum·범위 검증을 통과하지 못하면 다른 정상 필드를
보존하고 그 필드만 격리한다. Document Parse location으로 원문 근거를 검증할 수
있으면 `value=null`과 원문 근거를 가진 `NEEDS_CHECK`, 근거도 검증할 수 없으면
`value`, `source_page`, `source_text`가 모두 `null`이고 `confidence=0`인 `NOT_FOUND`로
다룬다. 해당 필드는 Evaluator 2라운드 재추출 대상이며, 두 번째에도 해결되지
않으면 격리 상태로 분석을 완료한다.

이번 수정의 검증 범위는 고정 fake 응답을 사용한 offline regression까지다. 수정 후
외부 Upstage를 다시 호출하지 않았으므로, `05-many-blanks` live 재검증은 아직 완료하지
않았다.

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
Pydantic 스키마로 다시 검증한다. 검토 항목은 Adapter 상한인 4건씩 묶어 호출한다.
전체 입력 UUID의 개수·중복·순서가 일치하고 모든 문구 검증을 통과한 경우에만 Solar
문구를 사용한다. 세 문구가 같거나, 금지된 단정 표현 또는 입력 근거에 없는 숫자가
있으면 Solar 결과 전체를 저장하지 않는다. 결정 규칙과 검증된 Solar 문구가 함께
사용된 항목은 `detection_method=HYBRID`다.

Solar Chat API는 보정된 confidence를 제공하지 않는다. 공개 계약의
`model_confidence`에는 Solar가 반환한 비보정 자기평가값을 넣고,
`model_limitations`에 이것이 법적 판단 정확도나 `source_confidence`가 아님을
명시한다. `source_confidence`는 기존 원문 추출 근거 값으로 유지한다.

Solar timeout, HTTP 오류, 잘못된 JSON, 스키마 오류, 출력 ID 불일치가 발생하면 모델
문구를 버리고 서버가 이미 만든 결정 규칙 기반 검토 항목으로 분석을 완료한다. 이때
항목은 `detection_method=DETERMINISTIC`이고 모델 자기평가와 한계를 저장하지 않는다.
`429`와 일시적인 전송·서버 오류만 Adapter에서 한 번 재시도한다. Solar 문구 실패는
추출값·원문 근거·신호·상태 전이를 변경하지 않으며 추출 Evaluator Loop의
`attempt_count`에도 포함하지 않는다.

### 2026-08-01 저장 계약 live 실패 재현과 fallback 검증

사용자가 명시적으로 실제 Upstage 사용을 요청해, 저장된 계약 한 건을 DB 쓰기 없이
live Adapter 경로로 재현했다. API key·계약 원문·파일명·Storage 경로·원시 모델 응답은
출력하지 않았다.

- Document Parse 성공: 5페이지, 원문 요소 74개
- Universal Extraction 성공: 대상 필드 28개, Evaluator 2라운드
- 결정 규칙 검토 후보 14개 생성
- 기존 1건 chunk 경로에서 첫 항목은 성공했지만 다음 항목의 Solar 문구에 입력 근거에
  없는 숫자가 포함되어 안전 검증이 거부했음을 확인
- 기본 chunk를 4건으로 바꾸고 같은 계약을 다시 실행한 결과, Solar 문구 검증 실패를
  결정 규칙 항목 14개로 fallback해 최종 `Analysis` 스키마 검증 완료
- 최종 안전 메타데이터: 추출값 28개, 검토 항목 14개,
  `detection_method=DETERMINISTIC` 14개

이 검증은 실제 Upstage Parse·Extract·Solar 연결과 실패 격리를 확인한 것이며 계약
내용의 법률적 정확도 평가는 아니다. 저장된 실패 작업의 재시작은 사용자가 화면의
`같은 계약서 다시 분석하기`를 명시적으로 눌렀을 때만 새 작업으로 실행한다.

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

## 수정 계약서 대조

대행사 응답을 소상공인이 확정해도 계약을 곧바로 서명 준비 상태로 바꾸거나 서비스가
별도 합의서를 생성하지 않는다. 대행사가 외부 채널로 보낸 수정 계약서 PDF를 소상공인이
다시 업로드하면 기존 Upstage Parse Adapter로 페이지별 원문만 추출한다.

확정된 각 최종 문구와 수정본의 대조는 생성형 모델 판단이 아니라 서버 코드가 NFKC
정규화, 소문자화, 공백 정규화 뒤 완전 포함 여부로 처리한다. 완전히 일치한 항목에만
`source_page`, `source_text`, `confidence=1`을 붙이고, 표현이 다르거나 찾지 못한 항목은
`NEEDS_CONFIRMATION`으로 남긴다. 사용자가 모든 항목을 명시적으로 체크한 뒤에만 계약을
`READY_TO_SIGN`으로 전이한다. 서명 초안은 확정한 수정 PDF의 문서 ID와 SHA-256을 검증해
같은 파일을 모두싸인에 전달하며, 서비스가 서명 요청을 자동 발송하지 않는다.

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

## P2 성과 리포트 지표 매핑 기반

17.5/P2-B-5 기반은 `apps/api/app/adapters/performance_metrics.py`의
`SolarPerformanceMetricMapper`로 분리한다. Upstage Document Parse가 만든
페이지별 원문을 입력받아 Solar가 strict JSON Schema로 지표 후보를 매핑한다.
공유 추출 계약은 기존 8개 required 후보를 유지하고 `ad_spend`와 `clicks`를 optional로
추가해 이전 payload도 계속 허용한다. 현재 구현의 prompt/schema version은
`performance-report-metrics-v2`다. v2 Solar strict output에서는 아래 10개를 모두
required로 요청하며, 원문에 없으면 새 두 후보도 생략하지 않고 `NOT_FOUND`로 반환한다.
즉 optional은 저장된 v1 payload를 읽는 공개 계약의 호환 규칙이고 Solar 출력 규칙이 아니다.

- `ad_spend`, `impressions`, `clicks`
- `likes`, `comments`, `reach`, `saves`, `shares`
- `follower_net_change`
- `published_content_count`

`mock`는 명시적인 `지표명: 정수`형 가상 원문만 결정적으로 읽고
HTTP client를 생성하지 않는다. `live`는 Solar Chat에 strict structured output을
요청한 뒤 Pydantic 스키마와 `source_page`/`source_text`의 실제 페이지
포함 여부를 다시 검증한다. 인용문의 해당 지표 라벨과 그 라벨 구간의
정수가 같은지도 검증해 페이지 전체에서 다른 지표 숫자를 고르는 결과를 거부한다.
광고비는 명시적인 `ad_spend` 금액 후보로, 클릭은 명시적인 `clicks` 건수 후보로만
취급한다. 비율·기간·비용 문맥과 `%`·기간·금액 단위를 다른 실적 건수로 인정하지 않는다.
스키마 밖에서 발견한 표현을 임의 사용자 정의 지표로 만들거나 확정하지 않는다.
원문에 없는 지표는 `NOT_FOUND`/`null`/
`confidence=0`이고, 원문의 명시적인 `0`은 누락으로 바꾸지 않는다.
`게시물 수`가 없으면 행이나 URL 수로 `published_content_count`를 추정하지
않는 두 경계는 `fixtures/evaluation/performance-metrics/`에 고정했다.

로그는 prompt version, model, 시작 시각, 성공/실패, HTTP status, 페이지·
지표 개수, 지연 시간, 스키마 검증 여부만 남긴다. 리포트 원문,
요청·응답 payload, API key는 로그에 남기지 않고 model도 외부 응답이 아닌
서버에 설정된 값만 기록한다. `apps/api/app/services/performance_ai.py`는 점유된
private 원본을 다운로드하고 Upstage Parse 후 이 mapper를 호출한다.
이 조합은 `get_performance_report_extraction_service`를 통해 16.3 공개 추출
endpoint에 연결됐다. 일반 자동 테스트는 mock parser·mapper나 고정 fake를
사용하며 외부 네트워크를 호출하지 않는다.

16.3 서버는 stale 작업이나 extraction attempt 전체를 자동으로 재실행하지 않는다.
사용자가 새 `Idempotency-Key`로 명시적으로 재시도해야 Document Parse부터 새 attempt가
시작된다. 다만 이미 claim한 동일 attempt 안에서 Solar 요청이 일시적인 transport 오류
또는 HTTP `429`/`500`/`502`/`503`/`504`로 실패하면 mapper가 최대 1회 전송
재시도한다. 이 재전송은 Document Parse를 다시 실행하거나 새 attempt를 claim하지 않으며,
두 전송이 모두 실패하면 `REPORT_EXTRACT_FAILED`로 종료한다.

2026-08-01 사용자의 명시적 요청으로 비식별 합성 PDF를 사용한 live Adapter
연결 검증을 1회 실행했다. Upstage Document Parse와 Solar Chat을 순서대로 실제
호출했고 exit code 0으로 완료됐다. Parse 결과는 1페이지였으며 Solar 설정 모델은
`solar-pro3`, prompt version은 `performance-report-metrics-v1`이었다. 8개 지표가
모두 원문 근거를 가진 `VERIFIED`로 strict Pydantic 검증을 통과했고 합성 PDF의
기대 정수값과 일치했다. API key·PDF 원문·`source_text`·외부 raw 응답은 결과에
기록하지 않았고 Supabase DB·Storage에는 쓰지 않았다. 이 결과는 Adapter live
연결 증거이며 아래 수직 E2E와 분리해 기록한다.

이 live 증거는 계약 확장 전 8개 required 후보에 대한 것이다. 새 `ad_spend`와
`clicks`까지 포함한 strict 출력은 별도 live 재검증 전이며, 사용자 정의 `metric_items`는
Solar가 생성하지 않고 소유자 확인 PATCH에서만 추가·수정·삭제한다.

### 2026-08-01 광고효과 16.2~16.5 live 수직 E2E

로컬 FastAPI를 실제 TCP로 기동한 뒤 live Supabase Auth·private Storage·
PostgreSQL, Upstage Document Parse, Solar Chat을 통과하는 합성 리포트 한 건을
명시적으로 실행했다. 배포된 FastAPI가 아닌 로컬 서버의 live 외부 연동
검증이며, 배포 환경은 별도로 확인해야 한다.

- 16.2 업로드 `201`, 16.3 추출·16.4 확정·16.5 조회 `200`
- Parse 1페이지, `solar-pro3`, `performance-report-metrics-v1`, 8개 지표 모두
  원문 근거가 있는 `VERIFIED`이며 기대 정수 8/8 일치
- 업로드·추출·확정 멱등 재생과 최초 `requestId` 일치 3/3, `no-store` 7/7
- private bucket, 익명 public object 읽기 거부, 감사 이벤트 3/3,
  멱등 레코드 3/3 확인
- 임시 Auth 사용자·계약·Storage·DB 대상 정리 6/6, 잔여 fixture 없음
- API key·원문·`source_text`·Storage 경로·외부 raw 응답을 요약에 노출하지 않음

재현 runner는 `apps/api/evaluation/performance_e2e_live.py`이다. localhost 목적지와
`--confirm-live --cleanup-created-data` 두 플래그를 모두 강제하며, 일반 자동 테스트에서는
외부 네트워크를 호출하지 않는다.

아래 명령은 이미 Parse된 고정 fixture로 Solar mapper만 다시 점검할 때 사용하는
최소 재현 절차다. 유료 호출 전 명시적 확인을 다시 받아야 한다.
`UPSTAGE_API_KEY`는 명령어나 shell history에 적지 말고 `apps/api/.env`
또는 배포 환경의 서버 비밀 변수로 미리 주입한다.

```bash
cd apps/api
CONFIRM_LIVE_PERFORMANCE_METRICS=1 UPSTAGE_MODE=live \
.venv/bin/python - <<'PY'
import asyncio
import json
import os
from pathlib import Path

from app.adapters.base import ParsedDocument, ParsedPage
from app.adapters.performance_metrics import (
    PERFORMANCE_METRIC_PROMPT_VERSION,
    SolarPerformanceMetricMapper,
)
from app.core.config import get_settings

if os.environ.get("CONFIRM_LIVE_PERFORMANCE_METRICS") != "1":
    raise SystemExit("set CONFIRM_LIVE_PERFORMANCE_METRICS=1 to allow the paid live call")

fixture_path = (
    Path.cwd().parents[1]
    / "fixtures/evaluation/performance-metrics/02-explicit-zero.json"
)
fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
parsed = ParsedDocument(
    pages=tuple(ParsedPage(number=p["page"], text=p["text"]) for p in fixture["pages"]),
    model="fixture-document-parse-v1",
)
settings = get_settings()
mapper = SolarPerformanceMetricMapper(
    mode="live",
    api_key=settings.upstage_api_key,
    base_url=settings.upstage_base_url,
    timeout_seconds=settings.upstage_solar_timeout_seconds,
    model=settings.upstage_solar_model,
)
try:
    result = asyncio.run(mapper.map_metrics(parsed_document=parsed))
except Exception as error:
    cause = error.__cause__
    response = getattr(cause, "response", None)
    status_code = getattr(response, "status_code", None)
    print(json.dumps({
        "status": "failed",
        "error_type": type(error).__name__,
        "cause_type": type(cause).__name__ if cause is not None else None,
        "http_status": status_code if isinstance(status_code, int) else None,
    }, ensure_ascii=False, indent=2))
    raise SystemExit(1) from None
print(json.dumps({
    "status": "completed",
    "prompt_version": PERFORMANCE_METRIC_PROMPT_VERSION,
    "model": settings.upstage_solar_model,
    "schema_valid": True,
    "verification_statuses": {
        name: getattr(result, name).verification_status.value
        for name in type(result).model_fields
    },
}, ensure_ascii=False, indent=2))
PY
```

재검증 명령의 exit code와 안전한 메타데이터 요약을 확인하고, 모델·prompt version·
실행일을 결과 문서에 추가한다. 실패하면
성공으로 대체하지 않고 오류 유형·HTTP status만 민감한 본문 없이 남긴다.

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

## 2026-08-01 백엔드 자동 테스트 검증 산출물

제출용 AI 활용 증빙을 위해 외부 Adapter를 명시적으로 mock으로 고정한 백엔드 전체
자동 검증을 실행했다. Python 3.12.3 환경에서 Ruff 진단 0건, 전체 `pytest` 719건 통과,
고정 계약 10건 오프라인 평가의 선언 목표 전체 통과를 확인했다.

JUnit XML, Ruff JSON, 오프라인 평가 JSON, 실행 환경·명령·제약을 포함한 검증 묶음은
[`docs/ai-evidence/backend-tests/2026-08-01`](docs/ai-evidence/backend-tests/2026-08-01/SUMMARY.md)에
보관한다. 이 결과는 `AUTOMATED_OFFLINE`이며 실제 외부 API 재호출 결과가 아니다. 기존
Upstage·Solar·Supabase live 결과는 같은 폴더의 live 증빙 안내에서 별도로 연결한다.

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
