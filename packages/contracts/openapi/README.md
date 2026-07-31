# API contract

`openapi.yaml`은 팀이 먼저 합의하는 P0 HTTP 계약입니다. persisted state나 공개 응답을
변경하기 전에 이 파일을 수정합니다.

FastAPI 구현에서 추출한 OpenAPI와 TypeScript 생성물은 추후 별도 파일로 두며, 생성물은
직접 수정하지 않습니다.

## C-6 extension — rendered agreement PDF (2026-07-31)

`POST /contracts/{contract_id}/agreement`는 원본 계약 PDF를 수정하지 않습니다. 확정된
구조화 합의서를 별도 PDF로 한 번 렌더링해 private Storage에 저장하고, 저장 경로·SHA-256·
페이지 수·합의서 버전·`AGREEMENT_CREATED` 감사 이벤트를 원자적으로 기록합니다. 이 저장
메타데이터는 내부용이며 `AgreementResponse`에는 노출하지 않습니다. PDF 저장 또는 메타데이터
기록에 실패하면 생성 전체를 실패 처리하고 저장된 파일을 정리합니다.

## C-7 API change — embedded Modusign drafts (2026-07-31)

`POST /contracts/{contract_id}/signature-requests`의 템플릿 기반 즉시 발송 흐름을
`POST /contracts/{contract_id}/signature-embedded-drafts`로 대체했습니다. 새 엔드포인트는
C-6이 private Storage에 저장한 합의서 PDF를 SHA-256 검증 후 읽어 서명자 기본값과 함께
모두싸인 편집 초안만 만들고 `editor_url`을 반환합니다. C-7은 PDF를 다시 렌더링하지 않습니다.
사용자가 해당 편집기에서 서명란을 배치하고 직접 발송하며, API 호출 자체는 서명 요청을
발송하지 않습니다. `editor_url`은 약 2시간 동안 유효한 민감한 URL이라 `no-store` 응답으로만
전달하며 DB, 로그, 멱등성 재생값에 저장하지 않습니다. `Signature`에는 새 `EDITING` 상태와
`modusign_draft_id`가 추가됐고, 계약은 이 단계에서 `READY_TO_SIGN`을 유지합니다.

## C-6 extension — rendered agreement artifact (2026-07-31)

`POST /contracts/{contract_id}/agreement`는 원계약 파일을 수정하지 않습니다. 확정된 합의서
데이터로 PDF를 한 번 생성해 private Storage에 보관하고, 해당 파일의 위치·SHA-256과 합의서
레코드를 원자적으로 연결합니다. 이 내부 메타데이터와 Storage 경로는 공개 API 응답에 포함하지
않으며, C-7은 이 저장본만 모두싸인 임베디드 초안에 전달합니다.
