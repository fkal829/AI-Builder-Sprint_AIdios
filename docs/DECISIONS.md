# 확정된 기술·제품 결정

## ADR-001 API 필드 명명

- 상태: 확정
- 결정: 공개 API 도메인 필드는 `snake_case`를 사용한다. 기존 공통 envelope와의
  호환성을 위해 요청 추적 필드만 `requestId`를 유지한다.
- 구현: Pydantic 내부 필드는 `request_id`, 외부 alias는 `requestId`로 둔다.

## ADR-002 원문 페이지와 AI 확신도

- 상태: 확정
- 결정: `source_page`는 사용자에게 표시하는 1-based 페이지 번호다.
- 추출 결과는 `confidence`를 저장한다.
- 검토 결과의 `source_confidence`는 기본 원문 근거로 연결한
  `ExtractedTerm.confidence`를 저장한다. 이는 검토 판단 자체의 확신도가 아니다.
- 검토 결과는 `detection_method`가 `MODEL` 또는 `HYBRID`일 때만
  `model_confidence`를 저장한다. 결정적 규칙 결과에는 가짜 모델 확신도를 넣지 않는다.

## ADR-003 원화와 날짜

- 상태: 확정
- 결정: 원화는 소수점 없는 0 이상의 정수 KRW로 저장하고 API에서도 `int64`로 전달한다.
- 계약상 날짜는 ISO 8601 `date`, 이벤트 시각은 timezone-aware UTC `date-time`을 쓴다.
- 총액, 비율, D-day는 AI가 아닌 결정적 코드로 계산한다.

## ADR-004 인증 경계

- 상태: 경계 확정, 공급자 미정
- 결정: 소유자 API는 Bearer 인증이 필요하다. 특정 인증 공급자는 아직 도입하지 않는다.
- 조정 응답 토큰과 산출물 증빙 토큰은 각각 `ADJUSTMENT_RESPONSE`,
  `OBLIGATION_EVIDENCE` scope로 분리한다.
- 공개 토큰 원문은 생성 응답에서 한 번만 반환하고 저장소에는 hash와 scope, 만료,
  폐기 정보만 저장한다.

## ADR-005 외부 실행과 멱등성

- 상태: 확정
- 결정: 조정 링크 활성화와 모두싸인 서명 요청은 사용자 명시적 확인과
  `Idempotency-Key`가 필요하다.
- 같은 키와 같은 요청은 최초 결과를 반환한다. 같은 키와 다른 요청은
  `IDEMPOTENCY_CONFLICT`로 거부한다.

## ADR-006 모두싸인 인증과 웹훅 중복 처리

- 상태: 공식 문서 확인 후 확정
- 결정: 외부 모두싸인 API는 서버 Adapter에서 HTTP Basic 인증을 사용한다.
- 웹훅 등록 시 `X-Modusign-Webhook-Secret` 사용자 지정 헤더를 설정하고 수신 전에
  검증한다.
- 공식 웹훅 payload에 별도 이벤트 ID가 없으므로 `event.type`, `document.id`, payload
  hash를 수신 식별자로 사용한다. 이벤트 수신 후 필요하면 문서 조회 API로 원본 상태를
  재확인한다.
- 참고:
  - https://developers.modusign.co.kr/docs/quick-start
  - https://developers.modusign.co.kr/docs/webhook-event

## ADR-007 서명자 연락처 최소 보존

- 상태: P0 확정
- 결정: 서명자 연락처는 사용자가 서명 요청 직전에 입력하고 모두싸인 Adapter 호출에만
  사용한다.
- 원문 연락처는 애플리케이션 DB, 감사 이벤트, 로그, API 응답에 저장하지 않는다.
- 서비스에는 역할, 이름, 서명 수단 종류, 마스킹된 연락처와 멱등성 확인용 단방향
  fingerprint만 저장한다.
- 외부 요청 전에 실패하면 사용자가 연락처를 다시 확인해 재요청한다.

## ADR-008 P0 문서 업로드 제한과 mock 인증

- 상태: P0 확정
- 결정: 계약서·제안서·견적서 PDF와 메시지 선택 자료는 파일당 최대 20 MiB로 제한한다.
  PDF는 최대 100페이지이며 암호화되었거나 손상된 파일은 저장하지 않는다.
- 선언 MIME과 실제 magic bytes가 일치해야 한다. `CONTRACT`, `PROPOSAL`, `ESTIMATE`는
  PDF만 허용하고 `MESSAGE`는 PDF·PNG·JPEG·UTF-8 text를 허용한다.
- 원본 파일명은 Storage 경로에 사용하지 않는다. 서버가 생성한 owner·contract·document
  UUID 기반 경로에 저장하고 일반 `Document` 응답에는 경로를 포함하지 않는다.
- 인증 공급자가 확정되기 전 로컬 `SUPABASE_MODE=mock`에서는 고정된 데모 Bearer 토큰과
  데모 owner·contract UUID만 사용한다. production에서는 mock 모드로 기동할 수 없다.
- 제한값은 `DOCUMENT_MAX_SIZE_MIB`, `DOCUMENT_MAX_PDF_PAGES`로 더 낮게 조정할 수 있다.
  운영에서 상향할 때는 API 문서, Storage bucket 제한과 배포 설정을 함께 변경한다.

## ADR-009 비공개 원문 임시 접근

- 상태: P0 확정
- 결정: 원문 접근은 소유자·계약·문서 조합을 함께 확인한 뒤 발급하며, 대상이 없거나
  소유하지 않은 경우를 모두 `404 NOT_FOUND`로 은닉한다.
- 접근 URL의 TTL은 서버에서 300초로 고정하고 응답에 `Cache-Control: no-store`를
  적용한다. URL과 영속 Storage 경로를 로그에 남기지 않는다.
- `source_page`는 1-based이고 저장된 `Document.page_count` 이하여야 한다. 범위를
  벗어나면 signed URL 발급 전에 `422 VALIDATION_ERROR`로 거부한다.
- `SUPABASE_MODE=mock`은 같은 프로세스의 메모리 객체를 고엔트로피 임시 토큰으로
  조회하며, `live`는 Supabase private Storage signed URL을 발급한다. mock 결과를
  실제 Supabase 연동 성공으로 간주하지 않는다.

## ADR-010 사용자 이해조건 저장

- 상태: P0 확정
- 결정: 기획안 6.1의 다섯 문항은 계약기간, 월 납부액, 총 계약금액, 환불조건,
  중도해지 가능 여부다. `source_type`은 입력 출처 메타데이터로 `USER_MEMORY`에
  고정한다.
- `UnderstoodTerm`은 `contract_id`를 PK로 하는 계약당 한 행이며 PUT으로 전체 교체한다.
  `contract_id`는 body가 아니라 경로와 인증된 소유자 컨텍스트에서 정한다.
- 월 납부액과 총 계약금액은 필수 nullable 정수 KRW다. 사용자가 기억하지 못하면
  `null`을 저장하며 두 값을 서버가 서로 계산하거나 보정하지 않는다.
- 계약 소유권 확인, 이해조건 upsert, `UNDERSTOOD_TERMS_SAVED` 감사 이벤트는 한
  트랜잭션에서 수행한다. 기존 값과 완전히 같은 PUT은 상태 변화가 없으므로 새 감사
  이벤트를 만들지 않는다.

## ADR-011 Upstage 분석·근거 검증

- 상태: P0 확정
- 결정: Upstage Adapter는 `mock`과 `live` 모드를 분리한다. live 문서 구조 분석은
  `/v1/document-digitization`, 구조화 추출은
  `/v1/information-extraction/chat/completions`의 `information-extract` 모델을 쓴다.
- Universal Extraction에는 PDF를 base64 문서 항목 하나로 보내고 first-level scalar
  JSON Schema, `location=true`, `confidence=true`, `split=false`를 사용한다.
- location 좌표가 같은 페이지의 Document Parse 요소와 겹친 경우에만 해당 요소
  원문을 `source_text`로 인정한다. 좌표를 연결하지 못한 값은
  `MISSING_EVIDENCE`이며 canonical 값으로 승격하지 않는다.
- Upstage의 confidence 범주 `high`, `low`는 저장 계약의 0~1 number에 맞춰 각각
  `0.9`, `0.4`로 정규화한다. `low`는 근거를 유지한 `NEEDS_CHECK`로 처리하며 이
  매핑은 보정된 확률이 아니다.
- 1차 결과에서 해결되지 않은 필드만 한 번 재추출하고 Evaluator Loop는 작업당 최대
  2회에서 종료한다. 모델 응답은 저장 전에 Pydantic과 원문 근거 규칙으로 검증한다.

## ADR-012 Solar 검토 설명과 3종 문구

- 상태: P0 확정
- 결정: 서버의 결정 규칙이 누락·불일치·명시적인 모호 표현과 책임 확인 후보를 먼저
  만든다. Solar는 후보별 쉬운 설명과 원안 수용·절충·요청 문구만 생성하고 신호,
  심각도, 원문 근거, 계산 결과, 사용자 선택과 상태를 변경하지 않는다. 이 결과는
  `detection_method=HYBRID`로 저장한다.
- 명시적 모호 표현 `공란`, `미기재`, `수기 입력 예정`, `별도 협의`, `추후 결정`,
  `상황에 따라 변경`은 `UNCLEAR` 후보로 만든다. 산출물 수량·기한·보고, 촬영 안전,
  시설 파손·손해 및 허위·과장 광고 책임 누락은 `MISSING` 후보로 만들고, 책임 필드의
  `모든 책임`, `일체의 책임`, `전적인 책임`, `전적으로 부담`, 책임 부인 표현은
  `NEEDS_CHECK` 후보로 만든다. 명시적 원문 표현을 찾은 후보만 원문 근거를 연결한다.
- live 호출은 설정 가능한 `UPSTAGE_SOLAR_MODEL`과
  `POST /v1/chat/completions`를 사용한다. 기본 alias는 `solar-pro3`, 프롬프트 버전은
  `contract-review-copy-v1`이다. live 검증된 기본값은 요청당 검토 항목 1건이며,
  Adapter가 허용하는 chunk 상한은 4건이다. 모든 chunk가 성공하고 전체 입력
  UUID의 개수·중복·순서가 일치한 뒤에만 결과를 반환한다. 모든 객체는 추가 필드를
  거부하는 strict JSON Schema와 Pydantic으로 검증한다.
- 입력과 출력 UUID 집합 불일치, 중복, 빈 문구, 같은 3종 문구, 금지된 단정 표현,
  입력 근거에 없는 숫자는 거부한다. 계약 원문 안의 명령은 데이터로 취급하며 전체
  계약서 대신 후보에 필요한 최소 원문만 전달한다.
- Solar Chat 응답에는 공식적인 보정 confidence가 없다. 공개 계약을 유지하기 위해
  Solar의 비보정 자기평가값을 `model_confidence`에 저장하되
  `model_limitations`에 법적 판단 정확도와 `source_confidence`가 아니라는 점을
  항상 덧붙인다.
- timeout, HTTP 오류, 잘못된 JSON, 스키마 오류는 고정 문구로 대체하지 않고
  `FAILED/ANALYSIS_SCHEMA_INVALID`로 종료한다. 멱등한 문구 생성 호출 중 `429`,
  전송 오류, `5xx`만 한 번 재시도하며 추출 `attempt_count`에는 포함하지 않는다.
- 프롬프트·원문·원시 응답은 로그에 남기지 않는다. 프롬프트 버전, 모델 ID, 시작 시각,
  성공·실패, 항목 수, 지연시간, 스키마 검증 결과만 구조화 로그로 추적한다. 별도의
  영속 AI 실행 이력 테이블은 현재 P0 범위에 추가하지 않는다.
- 참고:
  - https://console.upstage.ai/api/docs/for-agents/raw
  - https://console.upstage.ai/docs/capabilities/generate/structured-outputs

## ADR-013 Solar 역제안 비교

- 상태: P0 확정
- 결정: C가 대행사 응답 원본을 먼저 저장하고, 소유자용 조정 상세 조회에서 B의
  `CounterproposalComparator`를 호출한다. 수락·거절은 결정적 코드로 설명하고
  `COUNTER` 응답만 실제 요청 문구, 역제안 문구와 사유를 Solar에 전달한다.
- live 호출은 ADR-012와 같은 Solar Chat 모델·timeout을 사용하며 프롬프트 버전은
  `counterproposal-comparison-v1`이다. 출력은 달라진 점, 남은 확인사항, 최종 확인
  세 필드로 제한하고 strict JSON Schema와 Pydantic으로 검증한다.
- 입력·출력 UUID 불일치, 중복, 빈 확인사항, 추가 필드, 금지된 단정 표현과 입력에
  없는 숫자는 거부한다. 모델은 역제안을 자동 수락하거나 새 협상 문구를 만들지 않는다.
- timeout, HTTP 오류 또는 출력 검증 실패는 고정 성공 문구로 대체하지 않고
  `502 ANALYSIS_SCHEMA_INVALID`로 반환한다. 비교 실패는 먼저 저장된 대행사 응답,
  조정 상태와 감사 이벤트를 변경하지 않는다.
- mock 비교는 실제 입력을 직접 반영하는 규칙 기반 예시이며 live Solar 성공으로
  간주하지 않는다.

## ADR-014 배포 전 migration 버전 충돌 정정

- 상태: 2026-07-31 배포 전 정정 완료
- 문제: 모두싸인 웹훅과 증빙 링크 migration이 병합 시 같은
  `20260730300000` 버전을 사용해 Supabase 적용 순서를 고유하게 식별할 수 없었다.
- 확인: 서버 전용 자격으로 원격 PostgREST OpenAPI를 읽어 두 migration의 RPC가 모두
  노출되지 않았음을 확인했다. 신규 dashboard RPC도 아직 배포되지 않은 상태였다.
  원격 데이터나 migration 이력은 변경하지 않았다.
- 결정: 모두싸인 파일은 기존 버전을 유지하고, 증빙 링크 SQL은 아직 사용되지 않은
  `20260730300001`로 이동하면서 확정된 `SIGNED`·`IN_PROGRESS` 계약 상태 잠금·검사를
  함께 반영한다. 이후 보완 migration은
  `20260730330000`, `20260730330002`, `20260730330003`처럼 고유 버전만 추가한다.
- 운영 규칙: 이미 두 RPC 중 하나가 존재하거나 동일 버전이 원격 migration 이력에
  기록된 다른 환경에는 이 정정을 그대로 적용하지 않는다. 먼저 원격 이력과 함수
  정의를 확인하고 별도 append-only reconciliation migration을 만든 뒤 `db push`한다.

## ADR-015 서비스 생성 합의서를 수정 계약서 검증 흐름으로 교체

- 상태: 2026-07-31 확정
- 결정: 단디계약은 변경 합의서나 새 계약서를 대신 생성하지 않는다. 대행사는 조정 응답을
  자기 계약서 양식에 반영해 기존 이메일·메신저 채널로 수정본을 전달하고, 소상공인이
  `REVISED_CONTRACT` PDF를 업로드한다.
- 검증: 서버는 확정 조항 1~4개를 최신 수정본과 대조한다. 정확 문구를 찾은 경우에만
  `MATCHED`와 원문 페이지·문구를 붙이고, 표현이 다르거나 찾지 못하면
  `NEEDS_CONFIRMATION`으로 남겨 AI가 자동 확정하지 않게 한다.
- 승인 경계: 조정 결과 확정만으로 Contract를 `READY_TO_SIGN`으로 만들지 않는다. 최신
  수정본의 모든 항목을 소유자가 명시적으로 확인한 뒤에만 서명 준비 상태로 전이한다.
- 서명 무결성: 모두싸인 초안은 최신 `CONFIRMED` 대조의 문서 ID와 SHA-256에 고정된
  PDF만 사용한다. 확인 뒤 새 파일이 올라오면 다시 대조·확인해야 한다.
- 호환성: 이미 추가된 `agreements`, `agreement_files`와 관련 migration은 append-only
  원칙에 따라 삭제·수정하지 않는다. 기존 API는 deprecated 이력 호환 경로로 남기고 새
  정상 흐름에서 호출하지 않는다.
