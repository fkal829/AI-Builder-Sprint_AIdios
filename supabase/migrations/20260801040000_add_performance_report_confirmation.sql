-- P2-C-3: append-only revision/flag/inquiry-draft persistence and the atomic
-- first-confirmation/correction RPC. Builds on the report identity from
-- 20260801010000_add_performance_report_foundation.sql; does not modify it.

create table public.performance_report_revisions (
    id uuid primary key,
    report_id uuid not null references public.performance_reports(id) on delete cascade,
    version integer not null check (version >= 1),
    status text not null check (status in ('CONFIRMED', 'FLAGGED')),
    confirmed_payload jsonb not null,
    engagement_rate numeric(9, 6),
    corrected_from_revision_id uuid references public.performance_report_revisions(id),
    correction_reason text,
    confirmed_at timestamptz not null,
    constraint performance_report_revisions_report_version_key
        unique (report_id, version),
    constraint performance_report_revisions_correction_pairing_check
        check (
            (version = 1 and corrected_from_revision_id is null and correction_reason is null)
            or (
                version > 1
                and corrected_from_revision_id is not null
                and btrim(correction_reason) <> ''
            )
        ),
    constraint performance_report_revisions_confirmed_payload_check
        check (jsonb_typeof(confirmed_payload) = 'object')
);

create index performance_report_revisions_report_version_idx
    on public.performance_report_revisions (report_id, version);

alter table public.performance_reports
    add constraint performance_reports_current_revision_id_fkey
    foreign key (current_revision_id)
    references public.performance_report_revisions (id);

create table public.performance_flags (
    id uuid primary key,
    report_revision_id uuid not null
        references public.performance_report_revisions(id) on delete cascade,
    flag_type text not null check (
        flag_type in ('DELIVERABLE_COUNT_SHORTFALL', 'ENGAGEMENT_RATE_DROP', 'OWNER_REPORTED_ISSUE')
    ),
    comparison_report_revision_id uuid references public.performance_report_revisions(id),
    expected_content_count integer check (expected_content_count is null or expected_content_count >= 1),
    expected_period_unit text check (expected_period_unit is null or expected_period_unit = 'MONTH'),
    actual_content_count integer check (actual_content_count is null or actual_content_count >= 0),
    previous_engagement_rate numeric(9, 6) check (previous_engagement_rate is null or previous_engagement_rate >= 0),
    current_engagement_rate numeric(9, 6) check (current_engagement_rate is null or current_engagement_rate >= 0),
    issue_note text,
    created_at timestamptz not null,
    constraint performance_flags_shape_check
        check (
            (
                flag_type = 'DELIVERABLE_COUNT_SHORTFALL'
                and comparison_report_revision_id is null
                and expected_content_count is not null
                and expected_period_unit is not null
                and actual_content_count is not null
                and actual_content_count < expected_content_count
                and previous_engagement_rate is null
                and current_engagement_rate is null
                and issue_note is null
            )
            or (
                flag_type = 'ENGAGEMENT_RATE_DROP'
                and comparison_report_revision_id is not null
                and expected_content_count is null
                and expected_period_unit is null
                and actual_content_count is null
                and previous_engagement_rate is not null
                and previous_engagement_rate > 0
                and current_engagement_rate is not null
                and current_engagement_rate < previous_engagement_rate
                and issue_note is null
            )
            or (
                flag_type = 'OWNER_REPORTED_ISSUE'
                and comparison_report_revision_id is null
                and expected_content_count is null
                and expected_period_unit is null
                and actual_content_count is null
                and previous_engagement_rate is null
                and current_engagement_rate is null
                and btrim(issue_note) <> ''
            )
        )
);

create index performance_flags_revision_idx
    on public.performance_flags (report_revision_id);

create table public.performance_flag_basis_terms (
    flag_id uuid not null references public.performance_flags(id) on delete cascade,
    extracted_term_id uuid not null references public.extracted_terms(id) on delete restrict,
    document_id uuid not null,
    field text not null check (field in ('content_quantity', 'posting_frequency')),
    source_type text not null check (source_type = 'CONTRACT_DOCUMENT'),
    source_page integer not null check (source_page >= 1),
    source_text text not null check (btrim(source_text) <> ''),
    confidence double precision not null check (confidence between 0 and 1),
    verification_status text not null check (verification_status = 'VERIFIED'),
    primary key (flag_id, extracted_term_id)
);

create table public.performance_inquiry_drafts (
    id uuid primary key,
    flag_id uuid not null unique references public.performance_flags(id) on delete cascade,
    text text not null check (char_length(text) between 1 and 1000),
    template_version text not null check (template_version = 'performance-inquiry-copy-v1'),
    created_at timestamptz not null
);

alter table public.performance_report_revisions enable row level security;
alter table public.performance_flags enable row level security;
alter table public.performance_flag_basis_terms enable row level security;
alter table public.performance_inquiry_drafts enable row level security;

create policy performance_report_revisions_owner_select
    on public.performance_report_revisions
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.performance_reports report
            join public.contracts on contracts.id = report.contract_id
            where report.id = performance_report_revisions.report_id
              and contracts.owner_id = auth.uid()
        )
    );

create policy performance_flags_owner_select
    on public.performance_flags
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.performance_report_revisions revision
            join public.performance_reports report on report.id = revision.report_id
            join public.contracts on contracts.id = report.contract_id
            where revision.id = performance_flags.report_revision_id
              and contracts.owner_id = auth.uid()
        )
    );

create policy performance_flag_basis_terms_owner_select
    on public.performance_flag_basis_terms
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.performance_flags flag
            join public.performance_report_revisions revision on revision.id = flag.report_revision_id
            join public.performance_reports report on report.id = revision.report_id
            join public.contracts on contracts.id = report.contract_id
            where flag.id = performance_flag_basis_terms.flag_id
              and contracts.owner_id = auth.uid()
        )
    );

create policy performance_inquiry_drafts_owner_select
    on public.performance_inquiry_drafts
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.performance_flags flag
            join public.performance_report_revisions revision on revision.id = flag.report_revision_id
            join public.performance_reports report on report.id = revision.report_id
            join public.contracts on contracts.id = report.contract_id
            where flag.id = performance_inquiry_drafts.flag_id
              and contracts.owner_id = auth.uid()
        )
    );

revoke all on table public.performance_report_revisions, public.performance_flags,
    public.performance_flag_basis_terms, public.performance_inquiry_drafts
    from anon, authenticated;
grant select, insert on table public.performance_report_revisions, public.performance_flags,
    public.performance_flag_basis_terms, public.performance_inquiry_drafts
    to service_role;

create function public.confirm_performance_report_with_audit(
    p_owner_id uuid,
    p_contract_id uuid,
    p_report_id uuid,
    p_expected_revision integer,
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
    v_report public.performance_reports%rowtype;
    v_version integer;
    v_audit_event_type text;
    v_later_period text;
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

    perform 1
    from public.contracts
    where id = p_contract_id and owner_id = p_owner_id
    for key share;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    select report.* into v_report
    from public.performance_reports as report
    where report.id = p_report_id and report.contract_id = p_contract_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    if v_report.status = 'UPLOADED' then
        return jsonb_build_object('outcome', 'INVALID_STATUS');
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

        -- Only the latest confirmed month may be corrected, so a stale
        -- comparison never gets silently rewritten out from under a later
        -- month that already compared against it.
        select report.period into v_later_period
        from public.performance_reports report
        where report.contract_id = p_contract_id
          and report.status in ('CONFIRMED', 'FLAGGED')
          and report.period > v_report.period
        limit 1;
        if v_later_period is not null then
            return jsonb_build_object('outcome', 'CORRECTION_DEPENDENCY_EXISTS');
        end if;
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
        nullif(item ->> 'expected_content_count', '')::integer,
        nullif(item ->> 'expected_period_unit', ''),
        nullif(item ->> 'actual_content_count', '')::integer,
        nullif(item ->> 'previous_engagement_rate', '')::numeric,
        nullif(item ->> 'current_engagement_rate', '')::numeric,
        item ->> 'issue_note',
        p_confirmed_at
    from jsonb_array_elements(p_flags) item;

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
    from jsonb_array_elements(p_flags) item,
         jsonb_array_elements(item -> 'basis_snapshots') basis;

    insert into public.performance_inquiry_drafts (id, flag_id, text, template_version, created_at)
    select
        (item ->> 'id')::uuid,
        (item ->> 'flag_id')::uuid,
        item ->> 'text',
        item ->> 'template_version',
        p_confirmed_at
    from jsonb_array_elements(p_inquiry_drafts) item;

    update public.performance_reports
    set status = p_status,
        current_revision_id = p_revision_id,
        revision_count = v_version,
        updated_at = p_confirmed_at
    where id = p_report_id and contract_id = p_contract_id
    returning * into v_report;

    if v_version = 1 then
        v_audit_event_type := p_status; -- 'CONFIRMED' or 'FLAGGED'
        v_audit_event_type := 'PERFORMANCE_REPORT_' || v_audit_event_type;
    else
        v_audit_event_type := 'PERFORMANCE_REPORT_CORRECTED';
    end if;

    insert into public.audit_events (contract_id, event_type, actor_type, summary, payload, created_at)
    values (
        p_contract_id,
        v_audit_event_type,
        'OWNER',
        case
            when v_version = 1 then '광고효과 리포트를 확정했습니다.'
            else '광고효과 리포트를 정정했습니다.'
        end,
        jsonb_build_object('report_id', p_report_id, 'revision_id', p_revision_id, 'version', v_version),
        p_confirmed_at
    );

    return jsonb_build_object('outcome', 'CONFIRMED');
end;
$$;

revoke all on function public.confirm_performance_report_with_audit(
    uuid, uuid, uuid, integer, uuid, text, jsonb, numeric, uuid, text, timestamptz, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.confirm_performance_report_with_audit(
    uuid, uuid, uuid, integer, uuid, text, jsonb, numeric, uuid, text, timestamptz, jsonb, jsonb
) to service_role;
