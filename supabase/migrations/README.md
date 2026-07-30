# Supabase migrations

마이그레이션은 날짜 순서의 append-only SQL로 관리합니다.

첫 스키마에는 기획안의 `Contract`, `Document`, `UnderstoodTerm`, `ExtractedTerm`, `ReviewItem`, `AdjustmentRequest`, `AdjustmentResponse`, `Signature`, `Obligation`, `AuditEvent`를 포함합니다.

`202607300001_p0_document_upload.sql`은 4.1 업로드 수직 흐름에 필요한 `Contract`,
`Document`, `AuditEvent`, private `contracts` bucket과 원자적
`create_document_with_audit` RPC를 먼저 만든다. 이후 모델은 기존 마이그레이션을
수정하지 않고 후속 append-only SQL로 추가한다.

규칙:

- 원본 계약 파일 bucket은 private으로 유지합니다.
- 소유자용 테이블에는 RLS를 활성화합니다.
- 공개 토큰 접근은 브라우저에서 Supabase를 직접 호출하지 않고 FastAPI를 통합니다.
- 웹훅 이벤트 ID에는 unique 제약을 두어 중복 수신을 안전하게 처리합니다.
- enum과 상태 전환을 바꿀 때 `packages/contracts/state-machines.json`도 함께 수정합니다.
