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
