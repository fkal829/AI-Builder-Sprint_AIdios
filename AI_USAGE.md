# AI_USAGE — 단디계약

단디계약은 부산 관광상권 소상공인이 광고대행 계약의 조건을 확인하고, 원문 근거가
연결된 조정 요청을 만든 뒤 수정본 검증·서명·이행·광고효과·만료까지 관리하도록 돕는
계약 생애주기 관리 서비스다.

이 파일은 제품 AI와 개발 과정 AI의 **단일 증빙·기술 기준 문서**다. API·데이터 계약은
[api-data-contract.md](docs/api-data-contract.md), 실행 산출물은
[docs/ai-evidence/](docs/ai-evidence/)에서 확인한다.

## 1. 기준과 표기

| 항목 | 값 |
| --- | --- |
| 사실 검증일 | 2026-08-03 KST |
| 제품 코드 기준 | `origin/main` / `d3af764db180fc85ed5ecc5c4e3d0abc40497c8f` + 현재 리포트 fixture 교체 작업 트리 |
| 최신 자동 검증 | [2026-08-03 현재 리포트 교체 검증](docs/ai-evidence/project-tests/2026-08-03-current-report-replacement/SUMMARY.md) |
| 테스트 데이터 | 실제 개인정보가 없는 가상 계약·합성 PDF |

- `LIVE_EXTERNAL`: 실제 외부 API를 호출한 기록이다. 실행일·모델·프롬프트 버전과
  검증 범위를 함께 표시한다.
- `AUTOMATED_OFFLINE`: 외부 Adapter를 mock으로 고정한 자동 테스트다.
- `OFFLINE_SNAPSHOT`: 사람이 만든 정답·고정 추출 snapshot의 회귀 평가다. 실제 모델
  정확도가 아니다.
- `IMPLEMENTED_NOT_LIVE_VERIFIED`: 코드·자동 테스트는 있지만 별도 live 성공 산출물은 없다.

## 제출용 채점 기준별 증빙 색인

심사위원이 문서와 코드를 역추적하지 않아도 되도록 OT의 AI 활용도와 Upstage 가점 기준을
아래 증빙에 바로 연결한다.

| 채점 관점 | 단디계약의 선택 | 직접 확인할 증빙 | 현재 한계 |
| --- | --- | --- | --- |
| 개발 프로세스 전반의 AI 통합 | Codex·Claude Code를 구현·테스트에 사용하고 저장소 지침과 팀 Skill로 변경 절차를 통제 | [개발 과정 AI 활용](#8-개발-과정의-ai-활용과-증빙-범위), [dandi-issue-to-pr Skill](.agents/skills/dandi-issue-to-pr/SKILL.md) | 세션별 소요 시간과 토큰은 저장하지 않아 시간 절감률은 주장하지 않음 |
| 에이전트 설정·지침 체계성 | 공통·백엔드·프론트 지침, Issue→PR 반복 절차, 제출 증빙 Stop Hook을 저장소에 버전 관리 | [AGENTS.md](AGENTS.md), [apps/api/AGENTS.md](apps/api/AGENTS.md), [apps/frontend/CLAUDE.md](apps/frontend/CLAUDE.md), [Hook 설정](.claude/settings.json) | Hook은 제출 직전 도입되어 장기간 효율 효과는 아직 측정하지 않음 |
| 결과물 품질 기여도 | 고정 계약 평가, strict schema, 근거 좌표 검증, 안전 검사, 전체 자동 테스트로 AI 출력 품질을 검증 | [테스트·평가 산출물](#7-테스트평가검증-산출물), [RESULTS.md](fixtures/evaluation/RESULTS.md) | 오프라인 snapshot 수치를 실제 모델 정확도로 해석하지 않음 |
| Upstage 실질 통합 | 핵심 계약 흐름의 PDF 읽기·28개 조건 구조화·검토 문구와 성과 리포트 매핑에 사용 | [사용자 흐름 기준 AI 호출](#3-사용자-흐름-기준-ai-호출-위치), [실제 외부 API 검증](#73-실제-외부-api-검증--live_external) | 배포 FastAPI 전체 경로의 최신 live 재검증은 별도 필요 |

## Workflow와 Agent를 구분한 설계

단디계약 제품 런타임은 자율 에이전트가 아니라 **검증 가능한 고정 Workflow**다. 계약처럼
금액·상태·당사자 행동의 오류 비용이 큰 영역에서는 모델이 다음 행동이나 도구를 스스로
선택하게 하지 않고, 생성형 AI가 필요한 좁은 단계에만 Upstage를 배치했다.

| 구간 | 분류 | 선택 근거 |
| --- | --- | --- |
| 업로드 → Parse → Extract → 근거 검증 → 저장 | 결정적 Workflow | 실행 순서, 입력·출력 schema, 실패 상태가 서버 코드로 고정됨 |
| 미해결 필드 최대 1회 재추출 | 제한된 Evaluator Workflow | 대상 필드와 최대 2라운드가 코드로 고정되고 모델이 루프 지속 여부를 결정하지 않음 |
| 성과 지표 근거 검증 → 1회 교정 → 개별 안전 강등 | 제한된 Evaluator Workflow | 재시도 상한과 `NOT_FOUND` 강등 조건이 코드로 고정되고 라벨-값 불일치는 계속 거부됨 |
| Solar 설명·조정 문구 생성 | Workflow 안의 LLM 단계 | 서버가 만든 검토 신호만 표현하며 도구 선택·상태 전이 권한이 없음 |
| 발송·역제안 수락·서명·증빙 승인·갱신 | 사람 승인 Gate | 사용자 명시 행동 없이는 실행되지 않음 |
| Codex·Claude Code | 개발용 Coding Agent | 저장소를 읽고 구현·검증하지만 AGENTS·CLAUDE·Skill의 권한과 절차를 따름 |

따라서 제품에 자율 에이전트를 억지로 추가하지 않은 것은 기능 부족이 아니라 안전성과
재현성을 위한 의도적인 범위 결정이다. 날짜·금액·비율·상태 전이는 일반 코드가 맡고,
Upstage는 문서 이해와 원문 근거 범위 안의 사용자 설명에 집중한다.

## 2. 어떤 AI를 어디에 사용했는가

| 제품 기능 | 사용 AI·API | 역할 | 증빙 상태 |
| --- | --- | --- | --- |
| 계약서·수정계약서·성과 리포트 읽기 | Upstage Document Parse `POST /v1/document-digitization` | PDF 페이지·원문 요소·좌표 추출 | `LIVE_EXTERNAL` |
| 계약 조건 구조화 | Upstage Universal Information Extraction `POST /v1/information-extraction/chat/completions` | 정해진 JSON Schema의 계약 필드 28종 추출 | `LIVE_EXTERNAL` |
| 계약 검토 문구 | Upstage Solar Chat `solar-pro3` | 서버가 찾은 누락·불일치·모호 신호의 쉬운 설명과 문구 3종 생성 | `LIVE_EXTERNAL` |
| 대행사 역제안 비교 | Upstage Solar Chat `solar-pro3` | 달라진 점·남은 확인사항·최종 확인 문구 생성 | `LIVE_EXTERNAL` |
| 조정 요청 문구 다듬기 | Upstage Solar Chat `solar-pro3` | 사용자가 쓴 문구를 조건과 숫자를 유지하며 정중하게 변환 | `IMPLEMENTED_NOT_LIVE_VERIFIED` |
| 성과 리포트 지표 매핑 | Upstage Document Parse + Solar Chat `solar-pro3` | 광고비·노출·클릭 등 10개 후보와 원문 근거 매핑 | `LIVE_EXTERNAL`(v3 10개) |

서비스는 OpenAI·Claude 등 다른 회사의 모델을 제품 런타임에서 호출하지 않는다.
Codex·Claude Code는 개발 과정에서 사용한 코딩 도구이며 제품 사용자 데이터 처리 경로와
분리된다.

## 3. 사용자 흐름 기준 AI 호출 위치

| 단계 | AI가 하는 일 | AI가 하지 않는 일 |
| --- | --- | --- |
| 계약서 업로드·분석 | Parse로 문서를 읽고 Universal Extraction으로 28개 조건 후보와 위치·confidence를 추출 | 날짜·금액 계산, canonical 값 확정, 상태 전이 |
| 계약 검토 | 서버가 먼저 만든 신호를 쉬운 말과 원안 수용·절충·요청 문구로 표현 | 불일치 여부나 위법성 판단, 조정 요청 자동 발송 |
| 조정 문구 작성 | 사용자가 누른 경우에만 입력 문구를 정중하게 다듬고 미리보기를 반환 | 자동 적용·저장·발송, 숫자·조건 변경 |
| 상대방 역제안 확인 | 실제 요청·역제안·사유의 차이와 확인사항을 요약 | 역제안 자동 수락·거절, 상태 변경 |
| 수정계약서 검증 | Parse로 최신 PDF의 페이지별 원문을 추출 | 합의 반영 여부를 생성형 모델 의미 판단으로 확정 |
| 광고효과 리포트 | Parse 후 v3의 10개 성과 후보와 페이지·인용문을 매핑 | 없는 지표 추정, 비율·금액을 다른 실적 건수로 오인 |

수정계약서는 Parse 단계에만 AI API가 사용된다. 확정 문구와 수정본의 일치 여부는 서버가
NFKC 정규화·소문자화·공백 제거 후 정확 포함 여부로 검사한다. 정확히 찾은 경우만
`MATCHED`, `source_page`, `source_text`, `confidence=1.0`을 기록한다. 찾지 못하거나 표현이
다르면 `NEEDS_CONFIRMATION`이며, 사용자가 모든 항목을 확인해야 `READY_TO_SIGN`으로
전이한다. 구현은 [revised_contracts.py](apps/api/app/services/revised_contracts.py)다.

## 4. 모델·API·프롬프트·설정

### 4.1 호출 위치

| 용도 | 모델·alias / 프롬프트 버전 | 구현 위치 |
| --- | --- | --- |
| Document Parse | 요청 alias `document-parse`; 2026-07-30 응답 모델 `document-parse-260128` | [upstage.py](apps/api/app/adapters/upstage.py) |
| 계약 조건 추출 | `information-extract`; 자유 형식 시스템 프롬프트 없음 | [upstage.py](apps/api/app/adapters/upstage.py) |
| 계약 검토 문구 | `solar-pro3` / `contract-review-copy-v1` | [solar.py](apps/api/app/adapters/solar.py), [analysis.py](apps/api/app/services/analysis.py) |
| 역제안 비교 | `solar-pro3` / `counterproposal-comparison-v1` | [solar.py](apps/api/app/adapters/solar.py), [counterproposal.py](apps/api/app/services/counterproposal.py) |
| 조정 문구 다듬기 | `solar-pro3` / `adjustment-copy-polish-v1` | [solar.py](apps/api/app/adapters/solar.py), [tone_polish.py](apps/api/app/services/tone_polish.py) |
| 성과 지표 매핑 | `solar-pro3` / `performance-report-metrics-v3` | [performance_metrics.py](apps/api/app/adapters/performance_metrics.py), [performance_ai.py](apps/api/app/services/performance_ai.py) |

### 4.2 요청 설정

| 호출 | 주요 설정 | 실패 처리 |
| --- | --- | --- |
| Document Parse | `ocr=auto`, `model=document-parse`, timeout 120초 | 문서 분석 실패로 종료; 고정 샘플로 대체하지 않음 |
| Universal Extraction | first-level scalar JSON Schema, `location=true`, `location_granularity=element`, `confidence=true`, `split=false`, timeout 180초 | 스키마·근거 검증 실패 상태 보존 |
| 계약 검토 문구 | `temperature=0.3`, `reasoning_effort=medium`, `stream=false`, strict JSON Schema, 현재 chunk 최대 4건, timeout 120초 | 일시 오류 1회 재전송; 모델 문구를 버리고 결정 규칙 항목으로 fallback |
| 역제안 비교 | `temperature=0.2`, `reasoning_effort=medium`, `stream=false`, strict JSON Schema, 서비스 batch 최대 4건, timeout 120초 | 안전한 `502`; 저장된 상대방 응답과 상태는 유지 |
| 조정 문구 다듬기 | `temperature=0.2`, `reasoning_effort=medium`, `stream=false`, strict JSON Schema, 1건, timeout 120초 | 안전한 `502`; 자동 저장·적용·발송하지 않음 |
| 성과 지표 매핑 | `temperature=0`, `reasoning_effort=medium`, `stream=false`, strict JSON Schema, timeout 120초 | 일시 오류 1회 재전송; 근거 실패는 교정 1회 뒤 원문에 없는 개별 후보만 `NOT_FOUND`, 라벨-값 불일치는 실패 보존 |

Solar의 일시 오류 재전송 대상은 transport 오류와 HTTP `429`, `500`, `502`, `503`,
`504`이며 최대 한 번이다. 설정 기본값은 [config.py](apps/api/app/core/config.py), 실제
system prompt와 JSON Schema는 각 Adapter 상수에 함께 버전 관리한다.

### 4.3 프롬프트에 고정한 핵심 지침

- 계약 검토: 서버가 판정한 신호를 바꾸지 않고, 새 사실·숫자·법적 결론을 만들지 않는다.
- 역제안 비교: 실제 요청·역제안·사유만 비교하고, 수락·거절이나 신뢰성 판단을 하지 않는다.
- 문구 다듬기: 입력을 신뢰할 수 없는 데이터로 취급하고, 의도·주체·조건·날짜·금액·기간·
  비율·숫자 개수를 유지한다. 결과는 사용자가 확인한 뒤 적용한다.
- 성과 지표: v3의 10개 후보만 반환하고 각 값에 짧은 실제 원문과 페이지를 붙인다.
  `ad_spend`는 원화 정수 금액, 나머지는 명시된 정수만 허용한다. 원문에 없으면
  `NOT_FOUND`, `null`, `confidence=0`으로 반환한다.

## 5. 모델 출력을 신뢰하지 않기 위한 장치

1. **Evaluator Loop 최대 2회**: 첫 추출 뒤 누락·`NOT_FOUND`·근거 불일치·확인 필요
   필드만 한 번 재추출한다.
2. **원문 좌표 검증**: Universal Extraction 좌표가 같은 페이지 Parse 요소와 실제로
   겹치는 경우에만 `source_text`를 인정한다.
3. **잘못된 추출 후보 격리**: 요청한 필드 하나가 타입·형식·enum·범위를 어겨도 정상
   후보는 보존한다. 원문 근거가 있으면 `NEEDS_CHECK`, 없으면 `NOT_FOUND`로 격리해
   2라운드 재추출 대상으로 삼는다.
4. **명시적 환불 부재 분리**: “환불 조건을 기재하지 않았다”는 문장은 실제 환불 조건으로
   확정하지 않는다. 실제 비환불 조건과 섞였는지는 서버가 원문을 다시 검사한다.
5. **엄격한 출력 계약**: Solar 응답을 strict JSON Schema와 Pydantic으로 이중 검증한다.
6. **입력·출력 ID 검증**: UUID 개수·중복·순서 또는 집합이 요청과 다르면 사용하지 않는다.
7. **근거 없는 숫자 차단**: 입력에 없는 숫자를 만든 계약 검토·역제안 결과를 거부한다.
   문구 다듬기는 숫자별 출현 횟수까지 동일해야 한다.
8. **금지 단정 검사**: 사기·위법·업체 안전성·승소 가능성·법률 자문 대체 같은 단정을
   거부한다.
9. **confidence 분리**: Upstage `high=0.9`, `low=0.4`는 내부 표현값이지 보정 확률이
   아니다. Solar 자기평가도 법적 정확도나 원문 추출 confidence로 사용하지 않는다.
10. **사람 승인 게이트**: 발송, 역제안 수락, 최종 합의, 서명 초안 시작, 증빙 승인,
   재계약·종료는 사용자 명시 행동 없이는 실행하지 않는다.
11. **성과 표 지표의 안전 강등**: Solar가 표 헤더와 합계 값을 합쳐 원문에 없는
   `source_text`를 만들면 1회 교정한다. 두 번째에도 원문과 일치하지 않는 해당 후보만
   `NOT_FOUND`로 넘기며, 다른 지표의 숫자를 붙인 라벨-값 불일치는 계속 전체 거부한다.

날짜·금액·비율·총액·D-day·계약 상태 전이는 결정적 Python·SQL 코드가 처리한다.

## 6. 프론트엔드와 비밀정보 경계

- 프론트엔드는 Upstage Document Parse·Universal Extraction·Solar Chat을 직접 호출하지
  않고 FastAPI 소유자 API를 사용한다.
- Supabase Auth는 `src/lib/supabase/*`에서 브라우저가 직접 사용한다. 브라우저에는 공개용
  `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`가 포함될 수 있다.
- Supabase service-role secret과 Upstage·Solar·모두싸인 비밀키는 서버 환경에만 둔다.
- API key, Authorization 헤더, 계약 전문, 공개 토큰, 서명 URL, 모델 원시 응답을 로그에
  남기지 않는다. 공개 토큰은 CSPRNG로 생성하고 DB에는 SHA-256 hash만 저장한다.
- AI 설명·원문·사용자 이해조건·공식 기준·조정 요청안을 UI에서 서로 다른 층위로 표시하고,
  원문 페이지·문장을 같은 카드에서 확인할 수 있게 한다.

현재 광고효과 화면은 목업이 아니다. 업로드·추출·확정·정정·집계 API가 연결되어 있고,
Supabase 이메일·비밀번호 가입·로그인·복구·세션 토큰 경로도 구현되어 있다. 회귀 테스트는
[performance-api-wiring.test.mjs](apps/frontend/tests/performance-api-wiring.test.mjs)와
[live-api-wiring.test.mjs](apps/frontend/tests/live-api-wiring.test.mjs)에 있다.

## 7. 테스트·평가·검증 산출물

### 7.1 2026-08-03 현재 리포트 교체 검증 — `AUTOMATED_OFFLINE`

| 검증 | 결과 |
| --- | ---: |
| 백엔드 pytest | 850 passed, 실패·오류·skip 0 |
| Ruff | 진단 0건 |
| 프론트 소스 회귀 테스트 | 36 passed, 실패·skip 0 |
| 프론트 ESLint | 통과 |
| Next.js 프로덕션 빌드 | 통과 |
| 고정 계약 10건 오프라인 평가 | 선언 목표 전체 통과 |

JUnit XML, Ruff JSON, 프론트 실행 출력, 빌드 출력, 환경, 재현 범위와 SHA-256은
[2026-08-03 현재 리포트 교체 검증 패키지](docs/ai-evidence/project-tests/2026-08-03-current-report-replacement/SUMMARY.md)에
보관한다. 기준은 `d3af764...` 위의 현재 작업 트리이며, 새 PDF·mock·v3 10개 후보
runner·문서 변경을 포함해 다시 실행했다. 아직 이 변경을 담은 커밋은 만들지 않았다.

### 7.2 고정 계약 10건 — `OFFLINE_SNAPSHOT`

| 지표 | 결과 |
| --- | ---: |
| 핵심 필드 추출 정확도 | 96.67% (58/60) |
| 근거 페이지 연결 정확도 | 96.36% (53/55) |
| 필수 JSON 스키마 성공률 | 100% (10/10) |
| 기간·총액 불일치 탐지율 | 100% (3/3) |
| 기대 확인 신호 재현율 | 100% (16/16) |
| 근거 없는 확정 경고 | 0건 |

상세 분모는 [RESULTS.md](fixtures/evaluation/RESULTS.md)다. 이 결과는 실제 모델 정확도가
아니며 고정 snapshot과 결정 규칙의 회귀 결과다.

### 7.3 실제 외부 API 검증 — `LIVE_EXTERNAL`

| 일자 | 범위 | 결과·원본 |
| --- | --- | --- |
| 2026-07-30 | 계약 Parse·Extract + Supabase 수직 흐름 | 2페이지·31요소, 28필드 중 `VERIFIED` 27 / `NEEDS_CHECK` 1; [기술 기록](#2026-07-30-live-확인) |
| 2026-07-31 | 계약 검토 문구 | 1건 단위 요청 3회 성공, strict schema 3/3; [SOLAR_LIVE_RESULTS.md](fixtures/evaluation/SOLAR_LIVE_RESULTS.md) |
| 2026-07-31 | 역제안 비교 | 가상 역제안 1건 성공; [COUNTERPROPOSAL_LIVE_RESULTS.md](fixtures/evaluation/COUNTERPROPOSAL_LIVE_RESULTS.md) |
| 2026-08-01 | 저장 계약 실패 격리 | Parse 5페이지·74요소, 28필드·2라운드 후 안전 검증 실패를 결정 규칙 14건으로 fallback; [기술 기록](#2026-08-01-저장-계약-live-실패-재현과-fallback-검증) |
| 2026-08-01 | 성과 지표 Adapter | 합성 PDF 기대 지표 8/8, 근거 있는 `VERIFIED`; [기술 기록](#p2-성과-리포트-지표-매핑-기반) |
| 2026-08-01 | 광고효과 16.2~16.5 수직 E2E | 로컬 FastAPI TCP·live Supabase·Upstage·Solar, 멱등 3/3, `no-store` 7/7, cleanup 6/6; [runner](apps/api/evaluation/performance_e2e_live.py) |
| 2026-08-03 | 현재 3페이지 광고성과 PDF | exact SHA PDF를 Document Parse `document-parse-260630` + Solar `solar-pro3`/v3로 실행; 10개 중 직접 근거 4개 `VERIFIED`, 표·플랫폼 합산 6개 `NOT_FOUND`, 기대 안전 조건 10/10; [실행 요약](docs/ai-evidence/project-tests/2026-08-03-current-report-replacement/live-integration-summary.md) |

live 호출 기록에는 API key·계약 원문·`source_text`·Storage 경로·원시 응답을 넣지 않는다.

### 7.4 실패와 미검증 범위

- 계약 검토 문구 3건을 한 요청으로 보낸 최초 live 배치는 120초 timeout과 한 번의 재시도
  뒤에도 `ReadTimeout`으로 실패했다. 1건씩 보낸 3회는 성공했다.
- 현재 기본 계약 검토 chunk는 최대 4건이다. 4건 chunk의 안전 fallback은 확인했지만,
  4건 전체 생성 성공을 입증한 live 결과는 없다.
- `adjustment-copy-polish-v1`은 자동 테스트가 있지만 별도 Solar live 성공 산출물은 없다.
- 2026-08-02 발견한 단일 추출 후보 형식 오류 격리와 환불 조건 명시적 부재 처리는
  고정 응답 회귀 테스트를 통과했지만 해당 두 live 케이스를 다시 호출하지 않았다.
- 현재 데모 fixture의 첫 live 시도들은 Solar가 표의 `likes` 헤더와 값을 합쳐 원문에 없는
  인용문을 만든 탓에 근거 검증에서 실패했다. 재시도 상한과 개별 `NOT_FOUND` 강등을
  구현한 뒤 exact SHA 파일이 v3 기대 안전 조건 10/10을 통과했다. 실패 순서와 외부 호출
  횟수는 [live-attempts.md](docs/ai-evidence/project-tests/2026-08-03-current-report-replacement/live-attempts.md)에 남겼다.
- 광고효과 수직 E2E는 배포 서버가 아니라 로컬 FastAPI를 실제 TCP로 기동한 검증이다.
- 2026-08-03 자동 검증은 외부 Adapter를 재호출하지 않았다.

## 8. 개발 과정의 AI 활용과 증빙 범위

팀 기록에 따르면 백엔드 구현·테스트에는 Codex, 프론트 구현·검증에는 Claude Code,
초기 화면 설계에는 Claude 기반 디자인 도구와 공개 디자인 Skill을 사용했다.

저장소에서 직접 확인 가능한 개발 AI 증빙은 다음과 같다.

| 증빙 | 확인 가능한 내용 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 저장소 경계, 근거 보존, 결정적 계산, 자동 발송 금지 |
| [apps/api/AGENTS.md](apps/api/AGENTS.md) | API·AI 파이프라인·스키마·상태 전이·테스트 규칙 |
| [apps/frontend/CLAUDE.md](apps/frontend/CLAUDE.md) | 추측 금지, 최소·외과적 변경, 검증 가능한 성공 기준 |
| [dandi-issue-to-pr Skill](.agents/skills/dandi-issue-to-pr/SKILL.md) | 이슈→브랜치→구현→검증→PR 절차 |
| [PR #107](https://github.com/fkal829/AI-Builder-Sprint_AIdios/pull/107) | 광고효과 프론트 API 연동 |
| [PR #109](https://github.com/fkal829/AI-Builder-Sprint_AIdios/pull/109) | 운영 소유자 Supabase Auth |
| [PR #115](https://github.com/fkal829/AI-Builder-Sprint_AIdios/pull/115) | Solar 조정 요청 문구 다듬기 |
| [PR #119](https://github.com/fkal829/AI-Builder-Sprint_AIdios/pull/119) | 계약 비교·공개 원문 근거 표시 |

지침 파일은 에이전트 설정과 작업 경계를 증명하지만 개별 AI 세션의 모델 ID·대화 전문까지
증명하지는 않는다. 공개 디자인 Skill의 설치본도 개인 에이전트 디렉터리로 관리되어 현재
저장소에는 포함하지 않는다. 따라서 개발 AI의 세션별 기여도를 제품 live 증빙이나 자동
테스트 수치와 혼합하지 않는다.

### 8.1 공용 Skill 도입 뒤 관찰 가능한 변화

`dandi-issue-to-pr` Skill과 Issue·PR 템플릿은 2026-08-01 17:58 KST 커밋
`7e43f9f`에서 추가되고 `5007bf1`에서 통합됐다. 이후 현재 `main`까지의 로컬 Git 이력에서
직접 재현 가능한 관찰값은 다음과 같다.

| 관찰 항목 | 결과 | 해석 제한 |
| --- | ---: | --- |
| Skill 통합 뒤 GitHub PR merge | 9건 | merge commit 제목에 `Merge pull request`가 있는 건만 계산 |
| `<type>/#issue/...` 브랜치 규칙 준수 | 7/9건 | 절차 일관성 지표이며 Skill이 PR을 만들었다는 증명은 아님 |
| 백엔드 전체 회귀 테스트 | 719건(08-01) → 850건(현재 작업 트리), +131건 | 품질 검증 범위의 증가이며 개발 시간 단축과 동일하지 않음 |
| 자동 검증 snapshot | 4회 | 실행 환경·JUnit·Ruff·평가·SHA-256을 덮어쓰지 않고 보관 |
| 제출 증빙 Stop Hook | 직접 실행 1회 통과 | 제출 직전 도입했으므로 과거 작업 시간 절감의 증거로 사용하지 않음 |

규칙을 따른 7건은 PR #115, #119, #121, #123, #127, #129, #131이다. 예외는 통합
브랜치 PR #125와 별도 프론트 브랜치 PR #132다. 이 수치는 저장소 이력에서 다시 셀 수
있는 **절차 준수와 검증 범위**만 보여준다. 작업별 시작·종료 시각, AI 세션 재시도 횟수,
사람의 수정 시간은 수집하지 않았으므로 “개발 시간이 N% 줄었다”는 주장은 하지 않는다.

### 8.2 Skill·Hook 사용 범위

- **Skill 사용:** 반복되는 Issue→브랜치→영향 범위 확인→테스트→PR 인계 절차를 한 문서로
  재사용한다. P0 우선순위, 원문 근거 보존, 문서 선행 변경, 외부 Adapter와 승인 경계를
  작업마다 다시 설명하는 비용을 줄인다.
- **지침 사용:** 디렉터리별 AGENTS·CLAUDE 파일이 에이전트의 읽기 범위, 코드 소유권,
  테스트와 안전 규칙을 세션 시작 시 제공한다.
- **공유 Hook:** Claude Code가 응답을 마칠 때 [validate-ai-evidence.sh](.agents/hooks/validate-ai-evidence.sh)를
  실행하도록 [.claude/settings.json](.claude/settings.json)에 `Stop` Hook을 등록했다. 제출
  증빙 파일이 변경된 경우에만 `git diff --check`, 현재 HEAD의 전체 SHA, 최신 검증 요약
  링크, ZIP 유효성과 핵심 파일 최신성을 결정적으로 검사한다. Hook이 한 번 작업을 계속시킨
  뒤 무한 반복하지 않도록 `stop_hook_active=true`에서는 종료한다.

이 Hook은 2026-08-03 제출 정리 시점에 새로 도입했고 직접 실행 검증만 마쳤다. 따라서
향후 낡은 증빙 제출을 막는 재사용 장치로는 제시하지만, 과거 개발 시간을 줄였다는
근거로 사용하지 않는다. 정적 검사와 전체 제품 검증은 여전히 명시적 명령으로 실행한다.

다음 작업부터 실제 시간 효율을 비교하려면 Issue마다 `started_at`, 최초 테스트 결과,
AI 수정 반복 수, `completed_at` 네 값만 남기면 된다. 이 측정이 쌓이기 전까지는 위의
재현 가능한 운영 지표만 제출 증빙으로 사용한다.

## 9. 현재 한계

- 배포 FastAPI·배포 Supabase·배포 프론트를 모두 묶은 운영 환경 live E2E는 별도 검증이
  필요하다.
- 계약 검토 4건 chunk와 문구 다듬기의 별도 live 성공 산출물이 필요하다.
- 추출 후보 격리·환불 부재 처리의 수정 후 별도 live 재검증이 필요하다.
- 모델 confidence는 확률 보정 결과가 아니다.
- 이 서비스는 법률 자문, 사기·위법성 판정, 업체 신뢰성 판정, 승소 가능성 예측을 제공하지
  않는다.

## 10. 재현 명령

외부 호출 없는 자동 검증:

```bash
env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 PYTHONPATH=apps/api \
  PYTHONDONTWRITEBYTECODE=1 APP_ENV=local SUPABASE_MODE=mock \
  UPSTAGE_MODE=mock MODUSIGN_MODE=mock \
  apps/api/.venv/bin/python -m pytest \
  -c apps/api/pyproject.toml apps/api/tests --strict-config \
  -p no:cacheprovider -q --tb=short --color=no

apps/api/.venv/bin/python -m ruff check \
  apps/api/app apps/api/tests apps/api/evaluation --no-cache

cd apps/frontend
npm test
npm run lint
npm run build
```

실제 외부 호출과 비용이 발생하는 live runner는 명시적 확인 옵션 없이는 실행되지 않는다.

```bash
cd apps/api
.venv/bin/python -m evaluation.solar_live --confirm-live
.venv/bin/python -m evaluation.counterproposal_live --confirm-live
.venv/bin/python -m evaluation.performance_e2e_live \
  --confirm-live --cleanup-created-data
.venv/bin/python -m evaluation.performance_fixture_live --confirm-live
```

## 11. 기술 상세 부록

### 11.1 계약 분석 Evaluator Loop

1. 선택한 주 계약 문서와 지원 문서를 각각 한 번 Parse한다.
2. 1라운드에서 모든 선택 문서의 추출 결과를 Pydantic 스키마로 검증한다.
3. 문서별 누락, `NOT_FOUND`, 근거 불일치, 확인 필요 필드만 2라운드 대상으로 좁힌다.
4. 지원 문서 수와 관계없이 작업의 `attempt_count`는 최대 2라운드다.
5. 두 번째에도 찾지 못한 필드는 `NOT_FOUND`, 근거가 맞지 않는 값은
   `MISSING_EVIDENCE`로 저장한다.
6. Solar 검토 문구 실행은 추출 `attempt_count`에 포함하지 않는다.

Universal Extraction의 `additional_values` 좌표가 같은 페이지 Document Parse 요소와
겹치는 경우에만 해당 요소 원문을 `source_text`로 저장한다. Upstage의 범주형 confidence는
저장 스키마에 맞춰 `high=0.9`, `low=0.4`로 표현하며, `low`는 근거를 보존하되
`NEEDS_CHECK`로 처리한다.

<a id="2026-07-30-live-확인"></a>

### 11.2 2026-07-30 계약 Parse·Extract

가상 샘플 `apps/frontend/public/sample-contract.pdf`로 명시적 live 확인을 수행했다.

- Document Parse 요청 alias `document-parse`, 응답 모델 `document-parse-260128`
- 2페이지, 원문 요소 31개
- 전체 대상 28필드, Evaluator 2회
- `VERIFIED` 27개, 원문 근거가 있는 `NEEDS_CHECK` 1개
- 실제 Supabase access token을 사용한 FastAPI 흐름:
  계약 생성 `201` → 업로드 `201` → 이해조건 저장 `200` → 분석 `202 QUEUED` →
  `COMPLETED` → 원문 접근 `200`

이 결과는 한 샘플의 Adapter·HTTP·원격 영속 연결 확인이며 모델 정확도 지표가 아니다.

<a id="2026-08-01-저장-계약-live-실패-재현과-fallback-검증"></a>

### 11.3 2026-08-01 저장 계약 실패 격리

저장된 계약 한 건을 DB 쓰기 없이 live Adapter 경로로 재현했다.

- Parse 5페이지·원문 요소 74개
- Universal Extraction 대상 28필드·Evaluator 2라운드
- 결정 규칙 검토 후보 14개
- Solar가 입력 근거에 없는 숫자를 생성해 안전 검증이 거부
- 결정 규칙 항목 14개로 fallback해 최종 `Analysis` 스키마 검증 완료

API key·계약 원문·파일명·Storage 경로·원시 모델 응답은 기록하지 않았다.

<a id="p2-성과-리포트-지표-매핑-기반"></a>
<a id="2026-08-01-광고효과-162165-live-수직-e2e"></a>

### 11.4 2026-08-01 성과 지표 Adapter와 수직 E2E

현재 `performance-report-metrics-v3`는 `ad_spend`, `impressions`, `clicks`, `likes`,
`comments`, `reach`, `saves`, `shares`, `follower_net_change`,
`published_content_count` 10개 후보를 strict 출력으로 요구한다. 공유 payload에서는
기존 v1 호환을 위해 새 두 후보만 optional이지만, Solar v2 출력에서는 누락 시에도
`NOT_FOUND`로 반드시 반환한다. `ad_spend`는 원화 정수 금액, `clicks`는 명시적 클릭
횟수만 허용하며 비율에서 역산하지 않는다. 각 값의 `source_page`·`source_text`가 실제
페이지에 존재하고 해당 라벨 구간에 같은 정수가 있는지 서버가 다시 검사한다.

비식별 합성 PDF live Adapter 검증은 확장 전 v1의 8개 지표가 모두 근거 있는
`VERIFIED`였고 기대값 8/8과 일치한 기록이다. 새 `ad_spend`·`clicks`를 포함한 v2 live
성공으로 해석하지 않는다. 로컬 FastAPI TCP·live Supabase Auth/Storage/PostgreSQL·Upstage·Solar를
통과한 수직 E2E는 업로드 `201`, 추출·확정·조회 `200`, 멱등 재생 3/3,
`no-store` 7/7, 감사 이벤트 3/3, 테스트 데이터 cleanup 6/6을 확인했다.

활성 데모 PDF는 `브릿지웨이브_2026-07_광고성과리포트.pdf`로 교체했다. 새 문서에 전
매체 팔로워 순증 합계는 없으므로 플랫폼별 수치를 더해 만들지 않는다. 표 합계 행의 반응
지표와 Instagram 한정 도달은 원문만 보존하고 값은 `null`인 `NEEDS_CHECK`, 전체 팔로워
순증은 `NOT_FOUND` 기대값으로 고정했다. 이 분류는 오프라인 fixture 기대값이며 새 PDF의
live 성공 결과가 아니다.

### 11.5 2026-08-02 live에서 발견한 추출 경계와 수정 범위

- `05-many-blanks`: 날짜 후보 하나가 ISO 형식이 아니어서 정상 후보까지 모두 버려지는
  문제를 live 응답에서 발견했다. 현재 서버는 전체 JSON 구조 오류와 개별 후보 오류를
  구분하고, 개별 오류만 근거 유무에 따라 `NEEDS_CHECK` 또는 `NOT_FOUND`로 격리한다.
- `02-refund-omission`: “환불 조건은 계약서에 기재하지 않았다”는 문장이 실제 환불
  조건처럼 `VERIFIED`되는 문제를 live 응답에서 발견했다. 현재 추출 설명과 서버 검증은
  명시적 부재를 `NOT_FOUND`로 정규화하되, “환불 불가”처럼 실제 비환불 조건은 유지한다.

두 수정은 고정 fake 응답을 사용한 회귀 테스트까지 통과했다. 수정 뒤 외부 Upstage를 다시
호출하지 않았으므로 live 재검증 성공으로 표기하지 않는다.

### 11.6 비동기 복구 경계

FastAPI `BackgroundTasks`는 빠른 mock/demo 처리를 위한 보조 경로이고, 내구성 복구는
`python -m app.workers.analysis_recovery` worker가 맡는다. worker는 오래된 `QUEUED`
작업만 읽고 기존 조건부 `QUEUED → PROCESSING` claim을 사용하므로 여러 worker 중 하나만
처리한다. 처리 제한을 넘긴 `PROCESSING`은 문서 실패·감사 이벤트와 함께 원자적으로
종료하며 자동 무한 재시도하지 않는다. 사용자가 새 멱등 키로 명시적으로 재시작해야 한다.

### 11.7 보안 로그

- Parse·Extract·Solar 로그에는 모델·프롬프트 버전·시작 시각·성공/실패·HTTP status·
  지연시간·스키마 검증 여부 같은 안전한 메타데이터만 기록한다.
- API key, Authorization 헤더, 계약 전문, data URL, Storage 경로, 공개 토큰,
  `source_text`, 외부 원시 요청·응답은 기록하지 않는다.
- mock 결과는 live 연동 성공이나 실제 모델 정확도로 발표하지 않는다.
