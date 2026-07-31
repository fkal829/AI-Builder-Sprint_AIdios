-- P2 16.1: private monthly performance-report identity and document boundary.
-- Revisions, flags, inquiry snapshots, and their projection RPCs are added by
-- the follow-up confirmation/aggregation migration.

-- This is the first P2 persistence migration, so the planned performance audit
-- values become real AuditEventType values before any write RPC can use them.
alter table public.audit_events
    drop constraint if exists audit_events_event_type_check;

alter table public.audit_events
    add constraint audit_events_event_type_check
    check (
        event_type in (
            'CONTRACT_CREATED',
            'CONTRACT_STARTED',
            'CONTRACT_COMPLETED',
            'CONTRACT_RENEWAL_DUE',
            'DOCUMENT_UPLOADED',
            'UNDERSTOOD_TERMS_SAVED',
            'ANALYSIS_STARTED',
            'ANALYSIS_RESTARTED',
            'ANALYSIS_COMPLETED',
            'ANALYSIS_FAILED',
            'REVIEW_ITEM_SELECTION_UPDATED',
            'ADJUSTMENT_DRAFT_CREATED',
            'ADJUSTMENT_SENT',
            'ADJUSTMENT_OPENED',
            'ADJUSTMENT_RESPONDED',
            'ADJUSTMENT_CONFIRMED',
            'ADJUSTMENT_EXPIRED',
            'AGREEMENT_CREATED',
            'REVISED_CONTRACT_REVIEW_CREATED',
            'REVISED_CONTRACT_CONFIRMED',
            'SIGNATURE_DRAFT_CREATED',
            'SIGNATURE_REQUESTED',
            'SIGNATURE_STARTED',
            'SIGNATURE_COMPLETED',
            'SIGNATURE_ABORTED',
            'SIGNATURE_FAILED',
            'OBLIGATION_CREATED',
            'EVIDENCE_LINK_CREATED',
            'EVIDENCE_SUBMITTED',
            'EVIDENCE_APPROVED',
            'EVIDENCE_DISPUTED',
            'RENEWAL_DECISION_SAVED',
            'PERFORMANCE_REPORT_UPLOADED',
            'PERFORMANCE_REPORT_EXTRACTED',
            'PERFORMANCE_REPORT_CONFIRMED',
            'PERFORMANCE_REPORT_FLAGGED',
            'PERFORMANCE_REPORT_CORRECTED',
            'PERFORMANCE_REPORT_EXTRACTION_RECOVERED'
        )
    );

alter table public.documents
    drop constraint if exists documents_type_check;

alter table public.documents
    add constraint documents_type_check
    check (
        type in (
            'CONTRACT',
            'REVISED_CONTRACT',
            'PROPOSAL',
            'ESTIMATE',
            'MESSAGE',
            'PERFORMANCE_REPORT'
        )
    );

alter table public.documents
    add constraint documents_performance_report_content_type_check
    check (
        type <> 'PERFORMANCE_REPORT'
        or content_type in ('application/pdf', 'image/png', 'image/jpeg')
    );

-- The generic P0 upload RPC must stay unable to create the newly persisted
-- type. 16.2 adds a dedicated atomic Document + report + audit RPC.
alter function public.create_document_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    text,
    text,
    bigint,
    integer,
    timestamptz
) rename to create_contract_document_with_audit_legacy;

revoke all on function public.create_contract_document_with_audit_legacy(
    uuid,
    uuid,
    uuid,
    text,
    text,
    text,
    text,
    bigint,
    integer,
    timestamptz
) from public, anon, authenticated, service_role;

create function public.create_document_with_audit(
    p_owner_id uuid,
    p_document_id uuid,
    p_contract_id uuid,
    p_document_type text,
    p_parse_status text,
    p_storage_path text,
    p_content_type text,
    p_size_bytes bigint,
    p_page_count integer,
    p_created_at timestamptz
)
returns public.documents
language plpgsql
security definer
set search_path = ''
as $$
begin
    if p_document_type = 'PERFORMANCE_REPORT' then
        raise exception 'PERFORMANCE_REPORT requires its dedicated upload RPC'
            using errcode = '23514',
                  constraint = 'documents_performance_report_dedicated_upload_check';
    end if;

    return public.create_contract_document_with_audit_legacy(
        p_owner_id,
        p_document_id,
        p_contract_id,
        p_document_type,
        p_parse_status,
        p_storage_path,
        p_content_type,
        p_size_bytes,
        p_page_count,
        p_created_at
    );
end;
$$;

revoke all on function public.create_document_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    text,
    text,
    bigint,
    integer,
    timestamptz
) from public, anon, authenticated;

grant execute on function public.create_document_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    text,
    text,
    bigint,
    integer,
    timestamptz
) to service_role;

-- A composite candidate key lets the report FK enforce that its source
-- document belongs to the same contract. Document.type is guarded separately
-- because PostgreSQL cannot reference a predicate-only unique index.
alter table public.documents
    add constraint documents_contract_id_id_key unique (contract_id, id);

create table public.performance_reports (
    id uuid primary key,
    contract_id uuid not null references public.contracts(id) on delete cascade,
    period text not null,
    source_document_id uuid not null,
    status text not null default 'UPLOADED',
    extracted_payload jsonb,
    current_revision_id uuid,
    revision_count integer not null default 0,
    extraction_attempt_id uuid,
    extraction_started_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint performance_reports_contract_period_key unique (contract_id, period),
    constraint performance_reports_source_document_id_key unique (source_document_id),
    constraint performance_reports_source_document_same_contract_fkey
        foreign key (contract_id, source_document_id)
        references public.documents (contract_id, id)
        on delete restrict,
    constraint performance_reports_period_check
        check (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    constraint performance_reports_status_check
        check (status in ('UPLOADED', 'EXTRACTED', 'CONFIRMED', 'FLAGGED')),
    constraint performance_reports_extracted_payload_check
        check (
            (status = 'UPLOADED' and extracted_payload is null)
            or (
                status in ('EXTRACTED', 'CONFIRMED', 'FLAGGED')
                and extracted_payload is not null
                and jsonb_typeof(extracted_payload) = 'object'
            )
        ),
    constraint performance_reports_revision_projection_check
        check (
            (
                status in ('UPLOADED', 'EXTRACTED')
                and current_revision_id is null
                and revision_count = 0
            )
            or (
                status in ('CONFIRMED', 'FLAGGED')
                and current_revision_id is not null
                and revision_count >= 1
            )
        ),
    constraint performance_reports_extraction_attempt_check
        check (
            (extraction_attempt_id is null) = (extraction_started_at is null)
        ),
    constraint performance_reports_timestamps_check
        check (updated_at >= created_at)
);

create index performance_reports_contract_created_idx
    on public.performance_reports (contract_id, created_at desc, id desc);

create function public.enforce_performance_report_contract_status()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    perform 1
    from public.contracts
    where id = new.contract_id
      and status in ('SIGNED', 'IN_PROGRESS', 'RENEWAL_DUE', 'COMPLETED')
    for key share;

    if not found then
        raise exception 'performance report writes require an allowed contract status'
            using errcode = '23514',
                  constraint = 'performance_reports_contract_status_check';
    end if;

    return new;
end;
$$;

create trigger performance_reports_contract_status_guard
    before insert or update on public.performance_reports
    for each row
    execute function public.enforce_performance_report_contract_status();

create function public.enforce_performance_report_source_document()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    perform 1
    from public.documents
    where id = new.source_document_id
      and contract_id = new.contract_id
      and type = 'PERFORMANCE_REPORT'
    for key share;

    if not found then
        raise exception 'performance report source must be a same-contract PERFORMANCE_REPORT document'
            using errcode = '23514',
                  constraint = 'performance_reports_source_document_type_check';
    end if;

    return new;
end;
$$;

create trigger performance_reports_source_document_guard
    before insert or update of contract_id, source_document_id
    on public.performance_reports
    for each row
    execute function public.enforce_performance_report_source_document();

-- Keep the predicate true after a report is linked. The composite FK already
-- protects contract_id, while this trigger also protects Document.type and
-- produces one explicit integrity error for both mutations.
create function public.protect_performance_report_source_document()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if exists (
        select 1
        from public.performance_reports
        where source_document_id = old.id
          and (
              contract_id is distinct from new.contract_id
              or new.type is distinct from 'PERFORMANCE_REPORT'
          )
    ) then
        raise exception 'a linked performance report document cannot change contract or type'
            using errcode = '23514',
                  constraint = 'performance_reports_source_document_type_check';
    end if;

    return new;
end;
$$;

create trigger documents_performance_report_source_guard
    before update of contract_id, type on public.documents
    for each row
    execute function public.protect_performance_report_source_document();

alter table public.performance_reports enable row level security;

create policy performance_reports_owner_select
    on public.performance_reports
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts
            where contracts.id = performance_reports.contract_id
              and contracts.owner_id = auth.uid()
        )
    );

revoke all on table public.performance_reports from anon, authenticated;
grant select, insert, update on table public.performance_reports to service_role;

revoke all on function public.enforce_performance_report_contract_status()
    from public, anon, authenticated;
revoke all on function public.enforce_performance_report_source_document()
    from public, anon, authenticated;
revoke all on function public.protect_performance_report_source_document()
    from public, anon, authenticated;
