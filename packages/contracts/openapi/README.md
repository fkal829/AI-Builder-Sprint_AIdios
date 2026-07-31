# API contract

`openapi.yaml`은 팀이 먼저 합의하는 HTTP 계약입니다. persisted state나 공개 응답을
변경하기 전에 이 파일을 수정합니다. P0 operation은 현재 FastAPI runtime과 동기화하고,
6.14 광고효과 operation은 runtime이 생길 때까지 `x-implementation-status: planned`로
구분합니다. `planned`를 제거할 때는 runtime·DB migration·회귀 테스트를 같은 변경에서
완료해야 합니다.

FastAPI 구현에서 추출한 OpenAPI와 TypeScript 생성물은 추후 별도 파일로 두며, 생성물은
직접 수정하지 않습니다.

## Revised-contract verification (2026-07-31)

새 정상 경로는 대행사가 다시 보낸 `REVISED_CONTRACT` PDF와 확정 조정 문구를 대조하고,
소유자가 모든 항목을 확인한 뒤 그 문서 ID와 SHA-256을 서명 시도에 고정합니다. 기존
`/agreement` API와 저장 레코드는 이전 데이터 호환을 위해 deprecated 상태로 남습니다.

## C-7 API change — embedded Modusign drafts (2026-07-31)

`POST /contracts/{contract_id}/signature-requests`의 템플릿 기반 즉시 발송 흐름을
`POST /contracts/{contract_id}/signature-embedded-drafts`로 대체했습니다. 새 엔드포인트는
최신 확정 수정 계약서 PDF를 SHA-256 검증 후 읽어 서명자 기본값과 함께
모두싸인 편집 초안만 만들고 `editor_url`을 반환합니다. C-7은 PDF를 다시 렌더링하지 않습니다.
사용자가 해당 편집기에서 서명란을 배치하고 직접 발송하며, API 호출 자체는 서명 요청을
발송하지 않습니다. `editor_url`은 약 2시간 동안 유효한 민감한 URL이라 `no-store` 응답으로만
전달하며 DB, 로그, 멱등성 재생값에 저장하지 않습니다. `Signature`에는 새 `EDITING` 상태와
`modusign_draft_id`가 추가됐고, 계약은 이 단계에서 `READY_TO_SIGN`을 유지합니다.

수정 계약서 대조는 정확 문구를 찾은 경우만 `MATCHED`로 표시합니다. 표현이 달라 의미 판단이
필요한 경우 `NEEDS_CONFIRMATION`으로 남기며 사용자가 명시적으로 확인하기 전에는 계약을
`READY_TO_SIGN`으로 바꾸지 않습니다.
