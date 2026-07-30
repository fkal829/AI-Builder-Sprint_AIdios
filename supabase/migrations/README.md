# Supabase migrations

마이그레이션은 날짜 순서의 append-only SQL로 관리합니다.

`202607300001_p0_document_upload.sql`은 4.1 업로드 수직 흐름에 필요한 `Contract`,
`Document`, `AuditEvent`, private `contracts` bucket과 원자적
`create_document_with_audit` RPC를 먼저 만든다. 이후 모델은 기존 마이그레이션을
수정하지 않고 후속 append-only SQL로 추가한다.

`20260730180001_add_understood_terms.sql`은 4.3의 계약당 한 `UnderstoodTerm`,
소유자 조회 RLS와 동일 PUT의 감사 이벤트 중복을 막는 원자적
`save_understood_term_with_audit` RPC를 추가한다.

`20260730190000_add_public_token_and_idempotency_foundation.sql`은 공개 토큰 hash와
6개 멱등 작업의 최초 응답 재생 기반을 추가한다.

`20260730200000_add_analysis_pipeline.sql`은 4.4의 `AnalysisTask`, `ExtractedTerm`,
`ReviewItem`, 대표 `Obligation` 저장소와 소유자 RLS를 추가한다. 분석 접수는 계약 상태·작업·감사 이벤트,
완료는 추출·검토 결과·검증된 canonical 승격·상태·감사 이벤트를 각각 하나의
트랜잭션으로 처리한다. 실패한 작업은 계약을 `ANALYZING`으로 유지해 사용자가 새
멱등 키로 재시작할 수 있다.

`20260730240000_add_review_item_selection.sql`은 4.6의 검토 선택과
`REVIEW_ITEM_SELECTION_UPDATED` 감사 이벤트를 원자적으로 저장한다. 같은 선택의
반복 저장은 기존 결과를 반환하고, 분석 작업의 `result.review_items` 미러도 함께
갱신한다.

원격 프로젝트 적용에는 service-role key가 아니라 Supabase CLI 로그인·프로젝트 연결과
DB 자격 정보가 필요하다.

```bash
supabase login
supabase link --project-ref <project-ref>
supabase db push
```

규칙:

- 원본 계약 파일 bucket은 private으로 유지합니다.
- 소유자용 테이블에는 RLS를 활성화합니다.
- 공개 토큰 접근은 브라우저에서 Supabase를 직접 호출하지 않고 FastAPI를 통합니다.
- 웹훅 이벤트 ID에는 unique 제약을 두어 중복 수신을 안전하게 처리합니다.
- enum과 상태 전환을 바꿀 때 `packages/contracts/state-machines.json`도 함께 수정합니다.
