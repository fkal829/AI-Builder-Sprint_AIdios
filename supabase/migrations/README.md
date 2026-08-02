# Supabase migrations

마이그레이션은 날짜 순서의 append-only SQL로 관리합니다.

과거 병합에서 모두싸인 웹훅과 증빙 링크 파일이 같은 `20260730300000` 버전을 사용한
충돌은 실제 원격 RPC 배포 전에 확인됐다. ADR-014에 따라 모두싸인은 기존 버전을
유지하고 증빙 링크만 `20260730300001`로 고유화했다. 다른 환경에서 동일 버전이 이미
적용됐다면 바로 push하지 말고 원격 migration 이력과 함수 정의를 먼저 확인한다.

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

`20260730250000_expand_contract_audit_event_types.sql`은 3.5 감사 타임라인에서 사용하는
`CONTRACT_STARTED`, `CONTRACT_COMPLETED`, `CONTRACT_RENEWAL_DUE`를
`audit_events.event_type` 체크 제약에 추가해 API·Python enum·DB 허용값을 일치시킨다.

`20260730260000_add_renewal_decisions.sql`은 3.6의 계약당 최신 재계약 의사와 재검토
항목 ID를 저장한다. `save_renewal_decision_with_audit` RPC가 소유권과
D-30·D-14·D-7 검토 구간을 다시 확인하고, 실제 선택 변경과
`RENEWAL_DECISION_SAVED` 감사 이벤트를 한 트랜잭션으로 처리한다.

`20260730300001_add_obligation_evidence_links.sql`은 7.3의 증빙 제출 링크용
`OBLIGATION_EVIDENCE` 공개 토큰 hash와 `EVIDENCE_LINK_CREATED` 감사 이벤트를
소유권, 계약 `SIGNED`·`IN_PROGRESS`, 대표 의무 `PENDING` 상태 확인과 함께 하나의
트랜잭션으로 저장한다.

`20260730310000_submit_obligation_evidence.sql`은 7.4의 공개 토큰 hash·scope·대상·
만료를 다시 검증하고 증빙 URL, `PENDING → SUBMITTED` 상태와
`EVIDENCE_SUBMITTED` 감사 이벤트를 하나의 트랜잭션으로 저장한다.

`20260730320000_review_obligation_evidence.sql`은 7.5의 소유권과 `SUBMITTED`
상태를 잠금 검증하고 승인·이의 상태, 검토 시각, 지급 조건 표시와 대응 감사 이벤트를
하나의 트랜잭션으로 저장한다.

`20260803010000_add_owner_obligation_checklist.sql`은 기본 이행 흐름을 소유자 직접
체크리스트로 확장한다. `SIGNED`·`IN_PROGRESS` 계약의 `PENDING` 대표 산출물을 선택적
URL과 함께 `APPROVED` 또는 `DISPUTED`로 원자적으로 기록하고, 기존 공개 제출
`SUBMITTED` 흐름과 감사 이벤트 enum은 그대로 호환한다.

`20260730330000_make_idempotency_completion_recoverable.sql`은 비즈니스 처리가 끝난
멱등 요청의 완료 기록을 같은 응답으로 안전하게 재시도할 수 있게 한다. 응답 저장이
일시적으로 실패해도 처리 결과를 버리거나 동일 작업을 다시 실행하지 않는다.

`20260730330002_enforce_representative_obligation_evidence.sql`은 대표 의무 insert 전에
채널·콘텐츠 유형·수량·기한 네 필드가 같은 계약 원문에서 모두 `VERIFIED`인지 확인하고,
하나라도 없거나 근거가 다르면 분석 완료를 실패시키지 않고 해당 의무 생성을 건너뛴다.
2026-07-31 배포 전 원격 read-only 점검에서 기존 `obligations` 행이 0건임을 확인해
잘못 생성된 과거 대표 의무를 삭제하거나 보정하는 backfill은 추가하지 않았다.

`20260730330003_add_dashboard_aggregation.sql`은 소유자 계약 집합만 대상으로 계약 상태,
만료 구간, 미해결 신호, distinct 조정 항목, 대표 의무와 canonical 총액을 결정적으로
집계하는 `get_owner_dashboard` RPC를 추가한다. 최빈 신호 동률은
`MISMATCH`, `NO_BASIS`, `UNCLEAR`, `MISSING`, `NEEDS_CHECK` 순서로 해소한다.

`20260730330004_add_analysis_recovery_scan.sql`은 cutoff보다 오래된 `QUEUED`
분석 작업을 소유자 ID와 함께 생성 순서대로 제한 조회하는 service-role 전용 RPC를
추가한다. 별도 worker가 이 결과를 받아 기존 원자적 `QUEUED → PROCESSING` claim을
거치므로 여러 worker가 같은 작업을 처리하지 않는다.

`20260730330005_enforce_review_item_evidence_links.sql`은 검토 항목의 모든 관련 추출값이
같은 분석 작업·계약에 속하는지 확인하고, 기본 계약 원문 `source_*`가 연결된
`CONTRACT_DOCUMENT` 추출값과 정확히 일치하는지 insert·update 전에 강제한다. 기존 행도
마이그레이션 적용 중 같은 검증을 거쳐 잘못된 근거 링크를 조용히 유지하지 않는다.

`20260730330006_fail_stale_processing_analysis.sql`은 별도 worker가 처리 timeout보다
오래 `PROCESSING`에 머문 분석을 제한된 batch로 잠그고, cutoff을 다시 확인한 뒤
`FAILED/DOCUMENT_PARSE_FAILED`, 주 계약 문서와 선택 자료 `parse_status=FAILED`, `ANALYSIS_FAILED`
감사 이벤트를 한 트랜잭션으로 기록한다. `FOR UPDATE SKIP LOCKED`와 상태·cutoff
재검증으로 활성 처리 및 다른 worker와의 경쟁을 줄인다. 계약은 `ANALYZING`을
유지하므로 사용자가 기존의 명시적 재시작 경로를 사용할 수 있다. 기존 일반 분석 실패
RPC도 같은 작업의 주 계약 문서와 모든 선택 자료를 함께 `FAILED`로 정리하도록 보정한다.

`20260730330007_make_evidence_link_idempotent.sql`은 증빙 링크의 멱등 예약·검증,
공개 토큰과 감사 이벤트 생성, 안전한 replay payload 저장을 하나의 트랜잭션으로 묶는다.
DB 커밋 뒤 RPC 응답이 유실돼도 같은 키 재시도는 최초 token ID와 만료시각을 재생하며
두 번째 토큰이나 `EVIDENCE_LINK_CREATED` 이벤트를 만들지 않는다.

`20260801010000_add_performance_report_foundation.sql`은 16.1 광고효과 공통 기반으로
`Document.type=PERFORMANCE_REPORT`, 계약·월별 고유 `performance_reports`, 같은 계약의
전용 원본 연결, 허용 계약 상태 쓰기 guard와 owner 조회 RLS를 추가한다. 기존 일반
문서 RPC에서는 성과 원본 생성을 계속 차단하고, 계획된 성과 감사 이벤트 6종을 공통
`AuditEventType` DB CHECK에 병합한다. 업로드·추출·확정 원자 RPC와 revision·flag는
16.2~16.4 후속 migration에서 추가한다.

`20260801020000_add_performance_report_extraction_workflow.sql`은 17.2 추출 attempt
기반으로 `UPLOADED` 리포트와 원본 Document를 원자적으로 claim·완료·실패
처리한다. 15분 미만의 활성 작업은 중복 실행하지 않고, 15분 이상 지난
작업만 새 멱등 키로 재점유한다. 현재 attempt의 결과만 `EXTRACTED`와
Document 기술 상태에 반영하며, 이전 작업의 늦은 응답은 저장하지 않는다.

`20260801030000_add_performance_report_upload_audit.sql`은 16.2·17.5 업로드
저장 기반으로 private `Document`, `PerformanceReport=UPLOADED`, 빈 payload의
`PERFORMANCE_REPORT_UPLOADED` 감사 이벤트를 하나의 RPC 트랜잭션으로
저장한다. 서버가 미리 만든 Document·report ID와 동일한 불변 메타데이터로
재호출하면 기존 커밋을 재생하고 행과 감사 이벤트를 중복 생성하지 않는다.

`20260801040000_add_performance_report_confirmation.sql`은 16.4·16.5 확정 기반으로
append-only revision, 계약 근거 snapshot, 확인 신호, 미발송 문의 문안과
현재 projection·감사 이벤트를 한 트랜잭션에 저장하는 RPC를 추가한다.

`20260801050000_add_performance_report_atomic_snapshots.sql`은 계약 단위 lock으로
월별 확정을 직렬화하고, 비교 revision 충돌·과거 월 역순 확정을 거부한다.
확정 응답과 계약별 조회는 각각 하나의 DB snapshot에서 완전한 그래프를
반환하고, child table 직접 INSERT 권한을 회수한다.

`20260801060000_harden_performance_basis_and_period.sql`은 이미 적용된 050000을
수정하지 않고 후속 불변식을 추가한다. 근거 snapshot이 같은 계약·문서의
실제 `VERIFIED ExtractedTerm`과 원문·페이지·confidence까지 정확히 일치하는지
trigger로 강제하고 기존 행도 검증한다. 달력에 없는 `0000-MM`을 DB에서
거부하고, `0001-01`의 전월을 `null`로 처리하며 계약·리포트 상태 거부
결과를 분리한다.

`20260801070000_enforce_performance_basis_integrity.sql`은 수량 부족 신호가
수량·월 주기 근거를 정확히 한 건씩 갖도록 지연 constraint trigger로
강제한다. 근거 snapshot 검증 동안 원본 ExtractedTerm을 잠그고, 근거로
사용된 원본을 포함한 ExtractedTerm 전체를 append-only로 만들어 UPDATE를
차단한다. 참조된 원본 삭제는 기존 FK가 막고 service-role 직접 변경 권한도 회수한다.
기존 flag와 snapshot도 자동 수정 없이 다시 검증한다.

`20260801080000_fix_deferred_basis_trigger_execution.sql`은 070000의 지연
constraint trigger가 confirmation RPC 반환 뒤 service-role 트랜잭션의 commit
시점에도 비공개 검증 helper를 호출할 수 있도록, 완전히 한정된 trigger wrapper만
`SECURITY DEFINER`로 전환한다. helper의 직접 실행 권한은 계속 공개하지 않는다.

`20260802040000_remove_adjustment_item_count_limit.sql`은 조정 요청 초안과
수정 계약서 대조에서 항목 수 상한을 제거한다. 초안은 한 항목 이상,
선택·문구·원문 근거·순서·감사 이벤트 검증을 그대로 유지하고, 최신 수정본은
확정된 모든 조항을 빈 배열 없이 대조할 수 있다.

`20260802050000_sync_adjustment_original_text.sql`은 기존 검토 항목의 원문 기본 안내값을
보존된 `source_text`로 backfill하고, 새 검토 항목도 insert 시 같은 근거 문구를
`original_text`에 동기화한다. 공개 조정 링크와 최종 합의 비교는 이 문구와
`source_page`를 사용하며 원문 파일 URL이나 계약 전문은 공개하지 않는다.

`20260802060000_add_editable_performance_metric_items.sql`은 광고효과 확정 revision의
`confirmed_payload.metric_items`가 있으면 최대 50개의 `{key,label,value,unit}` 배열인지
검증한다. 소문자 slug key와 대소문자를 무시한 label의 고유성, canonical 지표 unit,
nullable 비음수 숫자의 소수점 6자리 및 `COUNT`·`KRW` 정수 규칙을 강제한다. 기존
append-only revision에 키가 없으면 legacy payload로 허용하며, 과거 행을 backfill하거나
기존 confirmation RPC·migration을 수정하지 않는다.

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
