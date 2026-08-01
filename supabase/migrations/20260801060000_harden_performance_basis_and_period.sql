-- P2 16.4 / 16.5 follow-up hardening. 20260801050000 may already be applied,
-- so this migration only adds invariants and replaces the existing RPC with
-- the exact same public signature.

-- Performance periods represent AD calendar months. Keep the original shape
-- constraint and reject the otherwise shape-valid but non-existent year 0000.
alter table public.performance_reports
    add constraint performance_reports_period_ad_year_check
    check (substring(period from 1 for 4) <> '0000')
    not valid;

alter table public.performance_reports
    validate constraint performance_reports_period_ad_year_check;

-- A basis row is an immutable copy of a VERIFIED ExtractedTerm. Validate both
-- the copied values and the complete target-report -> source-term tenant path.
create function public.enforce_performance_flag_basis_term_snapshot()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    perform 1
    from public.performance_flags as flag
    join public.performance_report_revisions as revision
      on revision.id = flag.report_revision_id
    join public.performance_reports as report
      on report.id = revision.report_id
    join public.extracted_terms as term
      on term.id = new.extracted_term_id
     and term.contract_id = report.contract_id
    join public.analysis_tasks as task
      on task.id = term.analysis_task_id
     and task.contract_id = report.contract_id
    join public.documents as document
      on document.id = term.document_id
     and document.contract_id = report.contract_id
    where flag.id = new.flag_id
      and term.document_id is not distinct from new.document_id
      and term.field is not distinct from new.field
      and term.source_type is not distinct from new.source_type
      and term.source_type = 'CONTRACT_DOCUMENT'
      and term.source_page is not distinct from new.source_page
      and term.source_text is not distinct from new.source_text
      and term.confidence is not distinct from new.confidence
      and term.verification_status is not distinct from new.verification_status
      and term.verification_status = 'VERIFIED';

    if not found then
        raise exception 'performance flag basis must exactly match a same-contract VERIFIED term'
            using errcode = '23514',
                  constraint = 'performance_flag_basis_terms_same_contract_verified_check';
    end if;

    return new;
end;
$$;

revoke all on function public.enforce_performance_flag_basis_term_snapshot()
    from public, anon, authenticated, service_role;

-- Take the table lock before auditing historical rows. A writer that started
-- before this migration must finish before CREATE TRIGGER acquires its lock;
-- rows written after that point are checked by the trigger.
create trigger performance_flag_basis_terms_same_contract_verified_guard
    before insert or update
    on public.performance_flag_basis_terms
    for each row
    execute function public.enforce_performance_flag_basis_term_snapshot();

do $$
begin
    if exists (
        select 1
        from public.performance_flag_basis_terms as basis
        where not exists (
            select 1
            from public.performance_flags as flag
            join public.performance_report_revisions as revision
              on revision.id = flag.report_revision_id
            join public.performance_reports as report
              on report.id = revision.report_id
            join public.extracted_terms as term
              on term.id = basis.extracted_term_id
             and term.contract_id = report.contract_id
            join public.analysis_tasks as task
              on task.id = term.analysis_task_id
             and task.contract_id = report.contract_id
            join public.documents as document
              on document.id = term.document_id
             and document.contract_id = report.contract_id
            where flag.id = basis.flag_id
              and term.document_id is not distinct from basis.document_id
              and term.field is not distinct from basis.field
              and term.source_type is not distinct from basis.source_type
              and term.source_type = 'CONTRACT_DOCUMENT'
              and term.source_page is not distinct from basis.source_page
              and term.source_text is not distinct from basis.source_text
              and term.confidence is not distinct from basis.confidence
              and term.verification_status is not distinct from basis.verification_status
              and term.verification_status = 'VERIFIED'
        )
    ) then
        raise exception 'existing performance flag basis violates same-contract snapshot rules'
            using errcode = '23514',
                  constraint = 'performance_flag_basis_terms_same_contract_verified_check';
    end if;
end;
$$;

create or replace function public.confirm_performance_report_with_audit(
    p_owner_id uuid,
    p_contract_id uuid,
    p_report_id uuid,
    p_expected_revision integer,
    p_expected_comparison_revision_id uuid,
    p_revision_id uuid,
    p_status text,
    p_confirmed_payload jsonb,
    p_engagement_rate numeric,
    p_corrected_from_revision_id uuid,
    p_correction_reason text,
    p_confirmed_at timestamptz,
    p_flags jsonb,
    p_inquiry_drafts jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract_status text;
    v_report public.performance_reports%rowtype;
    v_version integer;
    v_period_year integer;
    v_period_month integer;
    v_previous_period text;
    v_current_comparison_revision_id uuid;
    v_later_period text;
    v_audit_event_type text;
    v_snapshot jsonb;
begin
    if p_owner_id is null
       or p_contract_id is null
       or p_report_id is null
       or p_expected_revision is null
       or p_expected_revision < 0
       or p_revision_id is null
       or p_status is null
       or p_confirmed_payload is null
       or p_confirmed_at is null
       or p_flags is null
       or p_inquiry_drafts is null then
        raise exception 'performance report confirmation arguments are required'
            using errcode = '22004';
    end if;
    if p_status not in ('CONFIRMED', 'FLAGGED') then
        raise exception 'p_status must be CONFIRMED or FLAGGED' using errcode = '22023';
    end if;
    if jsonb_typeof(p_flags) is distinct from 'array'
       or jsonb_typeof(p_inquiry_drafts) is distinct from 'array' then
        raise exception 'p_flags and p_inquiry_drafts must be arrays' using errcode = '22023';
    end if;
    if (p_status = 'FLAGGED') is distinct from (jsonb_array_length(p_flags) > 0)
       or jsonb_array_length(p_flags) <> jsonb_array_length(p_inquiry_drafts) then
        raise exception 'status, flags, and inquiry drafts must describe one revision'
            using errcode = '22023';
    end if;

    -- Contract-wide serialization keeps target and comparison revisions stable.
    select contract.status into v_contract_status
    from public.contracts as contract
    where contract.id = p_contract_id
      and contract.owner_id = p_owner_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;
    if v_contract_status not in ('SIGNED', 'IN_PROGRESS', 'RENEWAL_DUE', 'COMPLETED') then
        return jsonb_build_object('outcome', 'CONTRACT_INVALID_STATUS');
    end if;

    select report.* into v_report
    from public.performance_reports as report
    where report.id = p_report_id
      and report.contract_id = p_contract_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;
    if v_report.status = 'UPLOADED' then
        return jsonb_build_object('outcome', 'REPORT_INVALID_STATUS');
    end if;
    if v_report.revision_count <> p_expected_revision then
        return jsonb_build_object('outcome', 'REVISION_CONFLICT');
    end if;

    v_version := p_expected_revision + 1;
    if v_version = 1 then
        if p_corrected_from_revision_id is not null or p_correction_reason is not null then
            raise exception 'version 1 must not reference a prior revision'
                using errcode = '22023';
        end if;
    else
        if p_corrected_from_revision_id is distinct from v_report.current_revision_id
           or p_correction_reason is null or btrim(p_correction_reason) = '' then
            raise exception 'correction must reference the report''s current revision'
                using errcode = '22023';
        end if;
    end if;

    -- Avoid PostgreSQL BC-date formatting at the AD boundary. 0001-01 has no
    -- preceding month representable by the public four-digit AD period type.
    v_period_year := substring(v_report.period from 1 for 4)::integer;
    v_period_month := substring(v_report.period from 6 for 2)::integer;
    if v_period_month > 1 then
        v_previous_period := lpad(v_period_year::text, 4, '0')
            || '-'
            || lpad((v_period_month - 1)::text, 2, '0');
    elsif v_period_year > 1 then
        v_previous_period := lpad((v_period_year - 1)::text, 4, '0') || '-12';
    else
        v_previous_period := null;
    end if;

    v_current_comparison_revision_id := null;
    if v_previous_period is not null then
        select previous.current_revision_id into v_current_comparison_revision_id
        from public.performance_reports as previous
        where previous.contract_id = p_contract_id
          and previous.period = v_previous_period
          and previous.status in ('CONFIRMED', 'FLAGGED');
    end if;

    if v_current_comparison_revision_id is distinct from p_expected_comparison_revision_id then
        return jsonb_build_object('outcome', 'COMPARISON_REVISION_CONFLICT');
    end if;
    if exists (
        select 1
        from jsonb_array_elements(p_flags) as item
        where item ->> 'flag_type' = 'ENGAGEMENT_RATE_DROP'
          and nullif(item ->> 'comparison_report_revision_id', '')::uuid
              is distinct from p_expected_comparison_revision_id
    ) then
        raise exception 'engagement comparison flag does not match expected prior revision'
            using errcode = '22023';
    end if;

    select later.period into v_later_period
    from public.performance_reports as later
    where later.contract_id = p_contract_id
      and later.status in ('CONFIRMED', 'FLAGGED')
      and later.period > v_report.period
    order by later.period
    limit 1;
    if v_later_period is not null then
        if v_version = 1 then
            return jsonb_build_object('outcome', 'PERIOD_ORDER_CONFLICT');
        end if;
        return jsonb_build_object('outcome', 'CORRECTION_DEPENDENCY_EXISTS');
    end if;

    insert into public.performance_report_revisions (
        id, report_id, version, status, confirmed_payload, engagement_rate,
        corrected_from_revision_id, correction_reason, confirmed_at
    ) values (
        p_revision_id, p_report_id, v_version, p_status, p_confirmed_payload, p_engagement_rate,
        p_corrected_from_revision_id, p_correction_reason, p_confirmed_at
    );

    insert into public.performance_flags (
        id, report_revision_id, flag_type, comparison_report_revision_id,
        expected_content_count, expected_period_unit, actual_content_count,
        previous_engagement_rate, current_engagement_rate, issue_note, created_at
    )
    select
        (item ->> 'id')::uuid,
        p_revision_id,
        item ->> 'flag_type',
        nullif(item ->> 'comparison_report_revision_id', '')::uuid,
        nullif(item ->> 'expected_content_count', '')::bigint,
        nullif(item ->> 'expected_period_unit', ''),
        nullif(item ->> 'actual_content_count', '')::bigint,
        nullif(item ->> 'previous_engagement_rate', '')::numeric,
        nullif(item ->> 'current_engagement_rate', '')::numeric,
        item ->> 'issue_note',
        p_confirmed_at
    from jsonb_array_elements(p_flags) as item;

    insert into public.performance_flag_basis_terms (
        flag_id, extracted_term_id, document_id, field, source_type,
        source_page, source_text, confidence, verification_status
    )
    select
        (item ->> 'id')::uuid,
        (basis ->> 'extracted_term_id')::uuid,
        (basis ->> 'document_id')::uuid,
        basis ->> 'field',
        basis ->> 'source_type',
        (basis ->> 'source_page')::integer,
        basis ->> 'source_text',
        (basis ->> 'confidence')::double precision,
        basis ->> 'verification_status'
    from jsonb_array_elements(p_flags) as item,
         jsonb_array_elements(item -> 'basis_snapshots') as basis;

    insert into public.performance_inquiry_drafts (
        id, flag_id, text, template_version, created_at
    )
    select
        (item ->> 'id')::uuid,
        (item ->> 'flag_id')::uuid,
        item ->> 'text',
        item ->> 'template_version',
        p_confirmed_at
    from jsonb_array_elements(p_inquiry_drafts) as item;

    update public.performance_reports
    set status = p_status,
        current_revision_id = p_revision_id,
        revision_count = v_version,
        updated_at = p_confirmed_at
    where id = p_report_id
      and contract_id = p_contract_id
    returning * into v_report;

    if v_version = 1 then
        v_audit_event_type := 'PERFORMANCE_REPORT_' || p_status;
    else
        v_audit_event_type := 'PERFORMANCE_REPORT_CORRECTED';
    end if;

    insert into public.audit_events (
        contract_id, event_type, actor_type, summary, payload, created_at
    ) values (
        p_contract_id,
        v_audit_event_type,
        'OWNER',
        case
            when v_version = 1 then '광고효과 리포트를 확정했습니다.'
            else '광고효과 리포트를 정정했습니다.'
        end,
        jsonb_build_object(
            'report_id', p_report_id,
            'revision_id', p_revision_id,
            'version', v_version
        ),
        p_confirmed_at
    );

    select jsonb_build_object(
        'report', to_jsonb(report),
        'revisions', coalesce((
            select jsonb_agg(to_jsonb(revision) order by revision.version)
            from public.performance_report_revisions as revision
            where revision.report_id = p_report_id
        ), '[]'::jsonb),
        'flags', coalesce((
            select jsonb_agg(to_jsonb(flag) order by flag.created_at, flag.id)
            from public.performance_flags as flag
            join public.performance_report_revisions as revision
              on revision.id = flag.report_revision_id
            where revision.report_id = p_report_id
        ), '[]'::jsonb),
        'basis_terms', coalesce((
            select jsonb_agg(to_jsonb(basis) order by basis.flag_id, basis.extracted_term_id)
            from public.performance_flag_basis_terms as basis
            join public.performance_flags as flag on flag.id = basis.flag_id
            join public.performance_report_revisions as revision
              on revision.id = flag.report_revision_id
            where revision.report_id = p_report_id
        ), '[]'::jsonb),
        'inquiry_drafts', coalesce((
            select jsonb_agg(to_jsonb(draft) order by draft.created_at, draft.id)
            from public.performance_inquiry_drafts as draft
            join public.performance_flags as flag on flag.id = draft.flag_id
            join public.performance_report_revisions as revision
              on revision.id = flag.report_revision_id
            where revision.report_id = p_report_id
        ), '[]'::jsonb)
    ) into v_snapshot
    from public.performance_reports as report
    where report.id = p_report_id;

    return jsonb_build_object(
        'outcome', 'CONFIRMED',
        'report_snapshot', v_snapshot
    );
end;
$$;

revoke all on function public.confirm_performance_report_with_audit(
    uuid, uuid, uuid, integer, uuid, uuid, text, jsonb, numeric, uuid, text,
    timestamptz, jsonb, jsonb
) from public, anon, authenticated;

grant execute on function public.confirm_performance_report_with_audit(
    uuid, uuid, uuid, integer, uuid, uuid, text, jsonb, numeric, uuid, text,
    timestamptz, jsonb, jsonb
) to service_role;
