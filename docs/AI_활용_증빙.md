# AI 활용 증빙

이 문서는 예선 제출 체크리스트 4번(AI 활용 증빙) 항목에 대한 요약 자료다. 기술적으로
더 상세한 내용은 [AI_USAGE.md](../AI_USAGE.md)와 [fixtures/evaluation/](../fixtures/evaluation/)를
참고한다.

## 1. 어떤 AI를 썼는가

단디계약은 두 층위에서 AI를 사용했다.

| 구분 | 사용한 AI | 역할 |
| --- | --- | --- |
| **제품 기능 (서비스가 실행 중 호출하는 AI)** | Upstage **Document Parse**, Upstage **Universal Extraction (Information Extraction)**, Upstage **Solar Chat (`solar-pro3`)** | 계약서를 읽고, 조건을 뽑고, 쉬운 말로 설명하는 실제 서비스 기능 |

Upstage 가점 대상 API(Solar LLM, Document Parse, Information Extract)를 모두 실제로
연동했다. Claude, GPT 등 타사 모델을 병행 사용하지는 않았고, Solar 계열 모델로만
서비스 로직을 구성했다.

코딩 에이전트 활용 근거는 저장소 루트의 [AGENTS.md](../AGENTS.md), `apps/api/AGENTS.md`,
`apps/frontend/CLAUDE.md`, `.claude/skills/`에 있다. 이 파일들은 Claude Code가 작업
경계(어떤 디렉터리를 건드릴 수 있는지), 제품 규칙(원문 근거 없는 AI 결과는 확정값으로
표시하지 않는다 등), 반복 작업 절차(로컬 서버 동시 실행, 이슈→PR 흐름)를 지키도록
저장소에 상시 포함된 지침이며, 매 커밋에 실제로 적용됐다.

## 2. 사용자 흐름 기준 — AI가 어디서, 무엇을 하는가

MVP 흐름은 다음과 같고, AI는 그중 4곳에서 호출된다. 계약 상태 전이·서명·발송처럼
"돌이키기 어려운" 단계는 전부 사람이 확정하며 AI가 자동으로 실행하지 않는다.

```
계약서 업로드 → 조건 추출 → 불일치·누락 검토 → 조정 요청 → 상대방 응답 →
수정 계약서 업로드·대조 → 모두싸인 서명 → 산출물 증빙 → 광고효과 기록·대조 → 만료·재계약 확인
        ①              ①            ②                        ③                                    ④
```

| # | 사용자가 보는 화면·행동 | 관련 화면 경로 | AI가 하는 일 | AI가 하지 않는 일 |
| --- | --- | --- | --- | --- |
| ① | 소상공인이 계약서 PDF를 올리면, 몇 초 뒤 기간·금액·환불조건 같은 핵심 조건이 화면에 정리되어 나타난다 | `contracts/new`, `contracts/[id]/analysis` | Document Parse가 PDF를 페이지·문장 단위로 읽고, Universal Extraction이 정해진 항목(JSON Schema)만 뽑아낸다 | 값이 맞는지 판정하지 않음 — 판정은 서버 결정 코드가 함 |
| ② | 사용자가 입력한 "내가 이해한 조건"과 실제 계약서 내용이 다르면, 항목별로 "쉬운 설명 + 원안 그대로 받기/절충안/재요청" 3가지 문구가 자동으로 제안된다 | `contracts/[id]/analysis`, `contracts/[id]/clauses` | Solar Chat이 서버가 이미 찾아낸 불일치·누락 신호를 받아 사람이 읽기 쉬운 설명과 3가지 협상 문구만 생성 | 불일치 여부 자체의 판정, 금액·날짜 계산, 계약 상태 변경은 하지 않음 |
| ③ | 광고대행사가 조정 요청에 "역제안"으로 응답하면, 원래 요청과 역제안이 뭐가 다른지, 무엇을 더 확인해야 하는지를 정리해 보여준다 | `contracts/[id]/responses`, `contracts/[id]/revision` | Solar Chat이 "달라진 점 / 남은 확인사항 / 최종 확인 문구"만 생성 | 역제안을 자동 수락·거절하지 않음 — 최종 선택은 항상 사용자 |
| ④ | 대행사가 올린 광고 성과 리포트(인스타그램 인사이트 캡처 등)를 업로드하면, 노출수·좋아요·저장수 같은 8개 지표를 자동으로 표로 정리해 계약과 대조한다 | `contracts/[id]/performance` | Document Parse로 리포트 원문을 읽고, Solar Chat이 8개 지표 후보를 표준 항목명으로 매핑 | 원문에 없는 지표를 추정해서 채우지 않음(값이 없으면 `NOT_FOUND`로 표시) |

수정 계약서가 원래 확정 문구와 실제로 같은 말인지 대조하는 단계(모두싸인 서명 직전
단계)는 Upstage Parse로 원문만 뽑고, 일치 여부 자체는 생성형 모델이 아니라 서버의
문자열 정규화·포함 검사 코드로 처리한다. "AI가 판단한 것처럼 보이지만 실제로는 AI가
관여하지 않는 지점"을 명확히 구분하기 위해 의도적으로 이렇게 설계했다.

## 3. 프롬프트 / 설정

모든 생성 호출은 **자유 형식 대화가 아니라 strict JSON Schema 구조화 출력**으로
고정했다. 모델이 스키마에 없는 필드를 만들거나 원문에 없는 숫자를 지어내면 그 결과는
저장하지 않고 실패로 처리한다.

| 프롬프트 버전 | 사용 위치 | 모델 | 주요 설정 | 생성 항목 |
| --- | --- | --- | --- | --- |
| `contract-review-copy-v1` | 조건 불일치·누락 검토 문구 | `solar-pro3` | `temperature=0.3`, `response_format=json_schema`, timeout 120초, 429/일시 오류 1회 재시도 | 쉬운 설명, 원안 수용/절충/요청 문구, 모델 한계 |
| `counterproposal-comparison-v1` | 대행사 역제안 비교 | `solar-pro3` | `temperature=0.2`, `response_format=json_schema`, timeout 120초 | 달라진 점, 남은 확인사항, 최종 확인 문구 |
| `performance-report-metrics-v1` | 광고효과 리포트 8개 지표 매핑 | `solar-pro3` | `temperature=0`, `response_format=json_schema`, timeout 120초, 전송 오류 1회 재시도 | 지표 8종 값과 원문 근거(`source_page`/`source_text`) |
| (프롬프트 없음, 스키마 추출) | 계약 조건 핵심 필드 추출 | Upstage `information-extract` | `location=true`, `location_granularity=element`, `confidence=true`, `split=false` | 계약 필드 값 + 원문 좌표 + confidence |

공통 설정:

- 모든 요청은 서버가 먼저 필요한 최소 정보(신호 종류, 원문 근거, 사용자 이해조건)만
  추려서 모델에 전달한다. 계약서 전문을 통째로 넘기지 않는다.
- 응답의 항목 ID가 요청한 입력 ID와 정확히 일치하지 않으면 결과 전체를 버린다.
- 로그에는 프롬프트 버전, 모델명, 시각, 성공/실패, HTTP 상태, 지연시간만 남기고
  API 키·계약 원문·모델 원시 응답은 남기지 않는다.

## 4. 테스트·검증 산출물

### 4-0. 날짜가 찍힌 재현 가능 증빙 패키지

`docs/ai-evidence/backend-tests/2026-08-01/`에 백엔드 전체 자동 검증 1회분을 실행
로그·원본 파일 그대로 보관했다. 심사자가 직접 열어 재현·대조할 수 있도록 사람이 다시
쓴 요약이 아니라 실행기 원본 출력을 커밋했다.

| 파일 | 내용 |
| --- | --- |
| [SUMMARY.md](ai-evidence/backend-tests/2026-08-01/SUMMARY.md) | 실행 결론·환경·재현 명령을 정리한 사람이 읽는 요약 |
| [environment.txt](ai-evidence/backend-tests/2026-08-01/environment.txt) | 실행 시각, git commit, Python·pytest·Ruff 버전, mock 모드 설정 |
| [pytest-full.txt](ai-evidence/backend-tests/2026-08-01/pytest-full.txt) | 실행 커맨드 전문과 `719 passed in 39.26s` 원본 출력 |
| [pytest-junit.xml](ai-evidence/backend-tests/2026-08-01/pytest-junit.xml) | 719개 테스트 케이스 이름·클래스·개별 실행 시간이 담긴 JUnit 리포트 |
| [ruff-check.json](ai-evidence/backend-tests/2026-08-01/ruff-check.json) | Ruff 정적 분석 결과 (`[]` = 진단 0건) |
| [offline-evaluation.json](ai-evidence/backend-tests/2026-08-01/offline-evaluation.json) | 고정 계약 10건 오프라인 평가의 원본 채점 결과 JSON |
| [live-integration-summary.md](ai-evidence/backend-tests/2026-08-01/live-integration-summary.md) | 이번 회차가 왜 live 호출을 다시 하지 않았는지, 기존 live 증빙 위치 안내 |
| [SHA256SUMS.txt](ai-evidence/backend-tests/2026-08-01/SHA256SUMS.txt) | 위 산출물의 SHA-256 체크섬 |

핵심 수치:

| 항목 | 결과 |
| --- | --- |
| 백엔드 전체 pytest | **719 passed, 0 failed, 0 errors, 0 skipped** (39.26초) |
| Ruff 정적 분석 | 진단 **0건** |
| 고정 계약 10건 오프라인 평가 | 5개 목표 지표 **전부 통과** |
| 검증 대상 commit | `5007bf1b80d5c1a529b8fd1965c2b34d471b30fa` (branch `backend`) |
| 외부 연동 모드 | `SUPABASE_MODE=mock`, `UPSTAGE_MODE=mock`, `MODUSIGN_MODE=mock` — 이 실행 자체는 유료 API를 호출하지 않음 |

이 719건에는 §2에서 설명한 AI 경계 — Upstage Parse/Extract 스키마 검증, 최대 2회
Evaluator Loop, Solar 검토 문구·역제안 비교의 안전 검사(금지 표현·근거 없는 숫자·ID
불일치 거부) — 를 검증하는 테스트가 모두 포함되어 있다. 이 회차는 `AUTOMATED_OFFLINE`
증빙이며, 실제 Upstage·Solar API를 호출하는 `LIVE_EXTERNAL` 증빙(§4-3)과는 명확히
구분해서 표기했다 — 자동 테스트 통과를 실제 모델 성능인 것처럼 포장하지 않기 위해서다.

재현 명령(외부 네트워크 호출 없음, 저장소 루트에서 실행):

```bash
env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 PYTHONPATH=apps/api \
  PYTHONDONTWRITEBYTECODE=1 APP_ENV=local SUPABASE_MODE=mock \
  UPSTAGE_MODE=mock MODUSIGN_MODE=mock \
  apps/api/.venv/bin/python -m pytest \
  -c apps/api/pyproject.toml apps/api/tests --strict-config \
  -p no:cacheprovider -q --tb=short --color=no
```

### 4-1. 자동 테스트 구성 (매 커밋 실행, 외부 네트워크 미사용)

`apps/api/tests/`에 Solar·Upstage 연동을 검증하는 단위/통합 테스트가 있으며, mock
어댑터와 고정 fixture로 스키마 검증·재시도·실패 처리 로직을 검증한다. 예: `test_solar_adapter.py`,
`test_counterproposal.py`, `test_performance_metric_mapper.py`, `test_performance_ai_pipeline.py`,
`test_evaluation_fixtures.py` 등 25개 이상 파일, 719개 테스트 케이스(§4-0 참고).

```bash
cd apps/api
.venv/bin/python -m pytest -q
```

### 4-2. 오프라인 고정 평가 — 가상 계약 10건

`fixtures/evaluation/cases/`에 만든 10가지 계약 시나리오(기간·총액 불일치, 환불 누락,
자동갱신, 위약금 등)를 외부 호출 없이 결정적 코드로 채점한다. 결과는
[fixtures/evaluation/RESULTS.md](../fixtures/evaluation/RESULTS.md)에 있다.

| 지표 | 결과 | 목표 |
| --- | ---: | ---: |
| 핵심 필드 추출 정확도 | 96.67% (58/60) | 90%↑ |
| 근거 페이지 연결 정확도 | 96.36% (53/55) | 90%↑ |
| 필수 JSON 스키마 성공률 | 100% (10/10) | 100% |
| 기간·총액 불일치 탐지율 | 100% (3/3) | 100% |
| 근거 없는 확정 경고 | 0건 | 0건 |

### 4-3. 실제 Upstage/Solar API를 호출한 live 검증

비용이 발생하는 실제 호출이므로 자동 테스트와 분리해 명시적으로 실행하고 결과를 기록했다.

- **Solar 검토 문구**: 가상 계약 3건으로 `solar-pro3` 실호출 3/3 성공, 스키마 검증
  3/3 통과 — [SOLAR_LIVE_RESULTS.md](../fixtures/evaluation/SOLAR_LIVE_RESULTS.md)
- **Solar 역제안 비교**: 가상 역제안 1건 실호출 성공, 스키마·근거 검증 통과 —
  [COUNTERPROPOSAL_LIVE_RESULTS.md](../fixtures/evaluation/COUNTERPROPOSAL_LIVE_RESULTS.md)
- **광고효과 지표 매핑**: Document Parse + Solar 순차 실호출, 8개 지표 모두 원문 근거를
  가진 `VERIFIED`로 검증 통과 (`AI_USAGE.md` 2026-08-01 기록)
- **로컬 서버 실제 TCP 기동 + Supabase(Auth/Storage/PostgreSQL) + Upstage + Solar를
  모두 통과하는 업로드→추출→확정→조회 수직 E2E**: 업로드 201, 추출·확정·조회 200,
  멱등 재생 3/3, private 버킷 익명 접근 거부 확인, 테스트 데이터 정리 6/6 완료
  (`AI_USAGE.md` "2026-08-01 광고효과 16.2~16.5 live 수직 E2E" 참고)
- **문서 구조 분석 + 조건 추출 단일 샘플 검증**: 가상 계약 PDF로 Document Parse 성공
  (2페이지, 원문 요소 31개), 전체 28개 대상 필드 중 27개 `VERIFIED` + 1개
  `NEEDS_CHECK`, Supabase 저장까지 포함한 HTTP 수직 흐름 성공 (`AI_USAGE.md`
  "2026-07-30 live 확인" 참고)

재현 커맨드(실제 과금 발생, 확인 플래그 필수):

```bash
cd apps/api
.venv/bin/python -m evaluation --format markdown          # 오프라인 10건 재채점
.venv/bin/python -m evaluation.solar_live --confirm-live   # Solar 검토 문구 실호출
.venv/bin/python -m evaluation.counterproposal_live --confirm-live  # 역제안 비교 실호출
```

### 4-4. "AI가 안전하게 실패하는지"에 대한 검증

세 문구가 서로 같거나, 금지된 단정 표현이 섞이거나, 입력에 없는 숫자가 나오거나,
응답 ID 순서가 요청과 다르면 결과를 저장하지 않고 분석 전체를 실패 처리하도록
테스트로 고정했다. "모델이 그럴듯하게 틀린 값을 만들어도 조용히 넘어가지 않는다"는
원칙을 코드와 테스트 양쪽에서 강제한다.
