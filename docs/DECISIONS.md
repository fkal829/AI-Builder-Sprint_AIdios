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
