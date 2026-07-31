# API contract

`openapi.yaml`은 팀이 먼저 합의하는 P0 HTTP 계약입니다. persisted state나 공개 응답을
변경하기 전에 이 파일을 수정합니다.

FastAPI 구현에서 추출한 OpenAPI와 TypeScript 생성물은 추후 별도 파일로 두며, 생성물은
직접 수정하지 않습니다.

## C-7 API change — embedded Modusign drafts (2026-07-31)

`POST /contracts/{contract_id}/signature-requests`의 템플릿 기반 즉시 발송 흐름을
`POST /contracts/{contract_id}/signature-embedded-drafts`로 대체했습니다. 새 엔드포인트는
합의서 PDF와 서명자 기본값으로 모두싸인 편집 초안만 만들고 `editor_url`을 반환합니다.
사용자가 해당 편집기에서 서명란을 배치하고 직접 발송하며, API 호출 자체는 서명 요청을
발송하지 않습니다. `editor_url`은 약 2시간 동안 유효한 민감한 URL이라 `no-store` 응답으로만
전달하며 DB, 로그, 멱등성 재생값에 저장하지 않습니다. `Signature`에는 새 `EDITING` 상태와
`modusign_draft_id`가 추가됐고, 계약은 이 단계에서 `READY_TO_SIGN`을 유지합니다.
