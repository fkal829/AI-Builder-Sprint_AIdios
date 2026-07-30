-- P0 4.4: durable analysis tasks and evidence-backed analysis results.

create table if not exists public.analysis_tasks (
    id uuid primary key,
    contract_id uuid not null references public.contracts(id) on delete cascade,
    document_id uuid not null references public.documents(id) on delete restrict,
    supporting_document_ids uuid[] not null default '{}'::uuid[]
        check (cardinality(supporting_document_ids) <= 10),
    status text not null check (status in ('QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED')),
    attempt_count integer not null check (attempt_count between 0 and 2),
    error_code text check (
        error_code in ('DOCUMENT_PARSE_FAILED', 'ANALYSIS_SCHEMA_INVALID')
    ),
    result jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (
        (status = 'QUEUED' and attempt_count = 0 and error_code is null and result is null)
        or (
            status = 'PROCESSING'
            and attempt_count between 1 and 2
            and error_code is null
            and result is null
        )
        or (
            status = 'COMPLETED'
            and attempt_count between 1 and 2
            and error_code is null
            and result is not null
        )
        or (
            status = 'FAILED'
            and attempt_count between 1 and 2
            and error_code is not null
            and result is null
        )
    )
);

create unique index if not exists analysis_tasks_one_active_per_contract_idx
    on public.analysis_tasks (contract_id)
    where status in ('QUEUED', 'PROCESSING');

create index if not exists analysis_tasks_contract_created_idx
    on public.analysis_tasks (contract_id, created_at desc, id desc);

create table if not exists public.extracted_terms (
    id uuid primary key,
    analysis_task_id uuid not null references public.analysis_tasks(id) on delete cascade,
    contract_id uuid not null references public.contracts(id) on delete cascade,
    document_id uuid not null references public.documents(id) on delete restrict,
    source_type text not null check (
        source_type in ('CONTRACT_DOCUMENT', 'DOCUMENTED_EXPLANATION')
    ),
    field text not null,
    value_type text not null check (
        value_type in ('TEXT', 'DATE', 'MONEY_KRW', 'INTEGER', 'PERCENT', 'BOOLEAN')
    ),
    value jsonb,
    source_page integer check (source_page >= 1),
    source_text text check (source_text is null or char_length(btrim(source_text)) >= 1),
    confidence double precision not null check (confidence between 0 and 1),
    verification_status text not null check (
        verification_status in ('VERIFIED', 'NOT_FOUND', 'MISSING_EVIDENCE', 'NEEDS_CHECK')
    ),
    created_at timestamptz not null default now(),
    unique (analysis_task_id, document_id, field),
    check ((source_page is null) = (source_text is null)),
    check (
        (verification_status = 'VERIFIED' and value is not null and source_page is not null)
        or (
            verification_status = 'NOT_FOUND'
            and value is null
            and source_page is null
        )
        or (
            verification_status = 'MISSING_EVIDENCE'
            and value is not null
            and source_page is null
        )
        or (
            verification_status = 'NEEDS_CHECK'
            and source_page is not null
        )
    )
);

create index if not exists extracted_terms_contract_field_idx
    on public.extracted_terms (contract_id, field, analysis_task_id);

create table if not exists public.review_items (
    id uuid primary key,
    analysis_task_id uuid not null references public.analysis_tasks(id) on delete cascade,
    contract_id uuid not null references public.contracts(id) on delete cascade,
    type text not null check (type in ('MISMATCH', 'NO_BASIS', 'UNCLEAR', 'MISSING', 'NEEDS_CHECK')),
    severity text not null check (severity in ('INFO', 'CHECK', 'IMPORTANT')),
    detection_method text not null check (
        detection_method in ('DETERMINISTIC', 'MODEL', 'HYBRID')
    ),
    model_confidence double precision check (model_confidence between 0 and 1),
    model_limitations text,
    plain_explanation text not null check (char_length(btrim(plain_explanation)) >= 1),
    basis_type text not null check (basis_type in ('OFFICIAL_SOURCE', 'INTERNAL_RULE')),
    basis_text text not null check (char_length(btrim(basis_text)) >= 1),
    basis_citation jsonb,
    related_extracted_term_ids uuid[] not null
        check (cardinality(related_extracted_term_ids) between 1 and 11),
    source_document_id uuid references public.documents(id) on delete restrict,
    source_page integer check (source_page >= 1),
    source_text text check (source_text is null or char_length(btrim(source_text)) >= 1),
    source_confidence double precision check (source_confidence between 0 and 1),
    verification_status text not null check (
        verification_status in ('VERIFIED', 'NOT_FOUND', 'MISSING_EVIDENCE', 'NEEDS_CHECK')
    ),
    suggestion_accept text not null check (char_length(btrim(suggestion_accept)) >= 1),
    suggestion_compromise text not null check (char_length(btrim(suggestion_compromise)) >= 1),
    suggestion_request text not null check (char_length(btrim(suggestion_request)) >= 1),
    user_choice text check (user_choice in ('ACCEPT', 'COMPROMISE', 'REQUEST')),
    status text not null check (
        status in ('UNREVIEWED', 'SELECTED', 'SENT', 'RESOLVED', 'KEPT_ORIGINAL')
    ),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (
        (source_document_id is null and source_page is null and source_text is null and source_confidence is null)
        or
        (source_document_id is not null and source_page is not null and source_text is not null and source_confidence is not null)
    ),
    check (
        (detection_method = 'DETERMINISTIC' and model_confidence is null and model_limitations is null)
        or
        (
            detection_method in ('MODEL', 'HYBRID')
            and model_confidence is not null
            and char_length(btrim(model_limitations)) >= 1
        )
    ),
    check (
        (basis_type = 'OFFICIAL_SOURCE' and basis_citation is not null)
        or (basis_type = 'INTERNAL_RULE' and basis_citation is null)
    ),
    check (
        (status = 'UNREVIEWED' and user_choice is null)
        or (status <> 'UNREVIEWED' and user_choice is not null)
    )
);

create index if not exists review_items_contract_status_idx
    on public.review_items (contract_id, status, id);

create table if not exists public.obligations (
    id uuid primary key,
    contract_id uuid not null unique references public.contracts(id) on delete cascade,
    title text not null check (char_length(btrim(title)) >= 1),
    due_date date not null,
    assignee text not null check (assignee = 'AGENCY'),
    evidence_type text not null check (evidence_type = 'URL'),
    source_document_id uuid not null references public.documents(id) on delete restrict,
    source_page integer not null check (source_page >= 1),
    source_text text not null check (char_length(btrim(source_text)) >= 1),
    confidence double precision not null check (confidence between 0 and 1),
    evidence_url text check (
        evidence_url is null
        or (
            char_length(evidence_url) <= 2048
            and evidence_url ~ '^https?://'
        )
    ),
    status text not null check (status in ('PENDING', 'SUBMITTED', 'APPROVED', 'DISPUTED')),
    submitted_at timestamptz,
    reviewed_at timestamptz,
    payment_condition_met boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (
        (
            status = 'PENDING'
            and evidence_url is null
            and submitted_at is null
            and reviewed_at is null
            and payment_condition_met = false
        )
        or (
            status = 'SUBMITTED'
            and evidence_url is not null
            and submitted_at is not null
            and reviewed_at is null
            and payment_condition_met = false
        )
        or (
            status = 'APPROVED'
            and evidence_url is not null
            and submitted_at is not null
            and reviewed_at is not null
            and payment_condition_met = true
        )
        or (
            status = 'DISPUTED'
            and evidence_url is not null
            and submitted_at is not null
            and reviewed_at is not null
            and payment_condition_met = false
        )
    )
);

alter table public.analysis_tasks enable row level security;
alter table public.extracted_terms enable row level security;
alter table public.review_items enable row level security;
alter table public.obligations enable row level security;

create policy analysis_tasks_owner_select
    on public.analysis_tasks
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts
            where contracts.id = analysis_tasks.contract_id
              and contracts.owner_id = auth.uid()
        )
    );

create policy extracted_terms_owner_select
    on public.extracted_terms
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts
            where contracts.id = extracted_terms.contract_id
              and contracts.owner_id = auth.uid()
        )
    );

create policy review_items_owner_select
    on public.review_items
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts
            where contracts.id = review_items.contract_id
              and contracts.owner_id = auth.uid()
        )
    );

create policy obligations_owner_select
    on public.obligations
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts
            where contracts.id = obligations.contract_id
              and contracts.owner_id = auth.uid()
        )
    );

revoke all on public.analysis_tasks, public.extracted_terms, public.review_items,
    public.obligations
    from anon, authenticated;
grant all on public.analysis_tasks, public.extracted_terms, public.review_items,
    public.obligations
    to service_role;

create or replace function public.start_analysis_with_audit(
    p_owner_id uuid,
    p_task_id uuid,
    p_contract_id uuid,
    p_document_id uuid,
    p_supporting_document_ids uuid[],
    p_restart boolean,
    p_created_at timestamptz
)
returns public.analysis_tasks
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract_status text;
    v_latest_document_id uuid;
    v_latest_task_status text;
    v_saved public.analysis_tasks;
    v_event_type text;
begin
    select status into v_contract_status
    from public.contracts
    where id = p_contract_id and owner_id = p_owner_id
    for update;
    if not found then
        return null;
    end if;

    if exists (
        select 1 from public.analysis_tasks
        where contract_id = p_contract_id and status in ('QUEUED', 'PROCESSING')
    ) then
        return null;
    end if;

    select id into v_latest_document_id
    from public.documents
    where contract_id = p_contract_id and type = 'CONTRACT'
    order by created_at desc, id desc
    limit 1;
    if v_latest_document_id is distinct from p_document_id then
        return null;
    end if;

    if coalesce(cardinality(p_supporting_document_ids), 0) > 10
       or (
           select count(*) from unnest(coalesce(p_supporting_document_ids, '{}'::uuid[])) item
       ) <> (
           select count(distinct item)
           from unnest(coalesce(p_supporting_document_ids, '{}'::uuid[])) item
       )
       or exists (
           select 1
           from unnest(coalesce(p_supporting_document_ids, '{}'::uuid[])) item
           left join public.documents d
             on d.id = item
            and d.contract_id = p_contract_id
            and d.type in ('PROPOSAL', 'ESTIMATE', 'MESSAGE')
           where d.id is null
       ) then
        return null;
    end if;

    if p_restart then
        select status into v_latest_task_status
        from public.analysis_tasks
        where contract_id = p_contract_id
        order by created_at desc, id desc
        limit 1;
        if v_contract_status <> 'ANALYZING' or v_latest_task_status <> 'FAILED' then
            return null;
        end if;
        v_event_type := 'ANALYSIS_RESTARTED';
    else
        if v_contract_status <> 'DRAFT' then
            return null;
        end if;
        v_event_type := 'ANALYSIS_STARTED';
    end if;

    insert into public.analysis_tasks (
        id,
        contract_id,
        document_id,
        supporting_document_ids,
        status,
        attempt_count,
        error_code,
        result,
        created_at,
        updated_at
    )
    values (
        p_task_id,
        p_contract_id,
        p_document_id,
        coalesce(p_supporting_document_ids, '{}'::uuid[]),
        'QUEUED',
        0,
        null,
        null,
        p_created_at,
        p_created_at
    )
    returning * into v_saved;

    update public.contracts
    set status = 'ANALYZING', updated_at = p_created_at
    where id = p_contract_id;

    insert into public.audit_events (
        contract_id, event_type, actor_type, summary, created_at
    )
    values (
        p_contract_id,
        v_event_type,
        'OWNER',
        case
            when p_restart then '실패한 계약 분석을 다시 접수했습니다.'
            else '계약 분석을 접수했습니다.'
        end,
        p_created_at
    );

    return v_saved;
end;
$$;

create or replace function public.mark_analysis_processing(p_task_id uuid)
returns public.analysis_tasks
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_saved public.analysis_tasks;
begin
    update public.analysis_tasks
    set status = 'PROCESSING', attempt_count = 1, updated_at = now()
    where id = p_task_id and status = 'QUEUED'
    returning * into v_saved;
    return v_saved;
end;
$$;

create or replace function public.complete_analysis_result_with_audit(
    p_task_id uuid,
    p_attempt_count integer,
    p_result jsonb
)
returns public.analysis_tasks
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_task public.analysis_tasks;
    v_saved public.analysis_tasks;
    v_obligation_created integer := 0;
begin
    if p_attempt_count not between 1 and 2 then
        raise exception 'attempt_count must be between 1 and 2' using errcode = '22023';
    end if;

    select * into v_task
    from public.analysis_tasks
    where id = p_task_id and status = 'PROCESSING'
    for update;
    if not found then
        return null;
    end if;

    perform 1
    from public.contracts
    where id = v_task.contract_id and status = 'ANALYZING'
    for update;
    if not found then
        return null;
    end if;

    if p_result is null
       or p_result ->> 'contract_id' is distinct from v_task.contract_id::text
       or jsonb_typeof(p_result -> 'extracted_terms') is distinct from 'array'
       or jsonb_typeof(p_result -> 'review_items') is distinct from 'array'
       or exists (
           select 1
           from jsonb_array_elements(p_result -> 'extracted_terms') item
           where (item ->> 'contract_id')::uuid is distinct from v_task.contract_id
              or (item ->> 'document_id')::uuid
                 <> all(array[v_task.document_id] || v_task.supporting_document_ids)
              or (
                  (item ->> 'document_id')::uuid = v_task.document_id
                  and item ->> 'source_type' <> 'CONTRACT_DOCUMENT'
              )
              or (
                  (item ->> 'document_id')::uuid = any(v_task.supporting_document_ids)
                  and item ->> 'source_type' <> 'DOCUMENTED_EXPLANATION'
              )
       )
       or exists (
           select 1
           from jsonb_array_elements(p_result -> 'review_items') item
           where (item ->> 'contract_id')::uuid is distinct from v_task.contract_id
       ) then
        raise exception 'analysis result does not belong to the task'
            using errcode = '22023';
    end if;

    insert into public.extracted_terms (
        id,
        analysis_task_id,
        contract_id,
        document_id,
        source_type,
        field,
        value_type,
        value,
        source_page,
        source_text,
        confidence,
        verification_status
    )
    select
        (item ->> 'id')::uuid,
        p_task_id,
        (item ->> 'contract_id')::uuid,
        (item ->> 'document_id')::uuid,
        item ->> 'source_type',
        item ->> 'field',
        item ->> 'value_type',
        nullif(item -> 'value', 'null'::jsonb),
        (item ->> 'source_page')::integer,
        item ->> 'source_text',
        (item ->> 'confidence')::double precision,
        item ->> 'verification_status'
    from jsonb_array_elements(p_result -> 'extracted_terms') item;

    if exists (
        select 1
        from public.extracted_terms term
        join public.documents document on document.id = term.document_id
        where term.analysis_task_id = p_task_id
          and term.source_page is not null
          and term.source_page > document.page_count
    ) then
        raise exception 'analysis evidence page is outside the source document'
            using errcode = '22023';
    end if;

    insert into public.review_items (
        id,
        analysis_task_id,
        contract_id,
        type,
        severity,
        detection_method,
        model_confidence,
        model_limitations,
        plain_explanation,
        basis_type,
        basis_text,
        basis_citation,
        related_extracted_term_ids,
        source_document_id,
        source_page,
        source_text,
        source_confidence,
        verification_status,
        suggestion_accept,
        suggestion_compromise,
        suggestion_request,
        user_choice,
        status
    )
    select
        (item ->> 'id')::uuid,
        p_task_id,
        (item ->> 'contract_id')::uuid,
        item ->> 'type',
        item ->> 'severity',
        item ->> 'detection_method',
        (item ->> 'model_confidence')::double precision,
        item ->> 'model_limitations',
        item ->> 'plain_explanation',
        item ->> 'basis_type',
        item ->> 'basis_text',
        nullif(item -> 'basis_citation', 'null'::jsonb),
        array(
            select value::uuid
            from jsonb_array_elements_text(item -> 'related_extracted_term_ids') value
        ),
        (item ->> 'source_document_id')::uuid,
        (item ->> 'source_page')::integer,
        item ->> 'source_text',
        (item ->> 'source_confidence')::double precision,
        item ->> 'verification_status',
        item ->> 'suggestion_accept',
        item ->> 'suggestion_compromise',
        item ->> 'suggestion_request',
        item ->> 'user_choice',
        item ->> 'status'
    from jsonb_array_elements(p_result -> 'review_items') item;

    with due as (
        select *
        from public.extracted_terms
        where analysis_task_id = p_task_id
          and document_id = v_task.document_id
          and source_type = 'CONTRACT_DOCUMENT'
          and field = 'deliverable_due_date'
          and value_type = 'DATE'
          and verification_status = 'VERIFIED'
        limit 1
    )
    insert into public.obligations (
        id,
        contract_id,
        title,
        due_date,
        assignee,
        evidence_type,
        source_document_id,
        source_page,
        source_text,
        confidence,
        evidence_url,
        status,
        submitted_at,
        reviewed_at,
        payment_condition_met
    )
    select
        gen_random_uuid(),
        v_task.contract_id,
        concat_ws(
            ' ',
            (
                select value #>> '{}'
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = due.document_id
                  and source_page = due.source_page
                  and source_text = due.source_text
                  and field = 'advertising_channel'
                  and verification_status = 'VERIFIED'
                limit 1
            ),
            (
                select value #>> '{}'
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = due.document_id
                  and source_page = due.source_page
                  and source_text = due.source_text
                  and field = 'content_type'
                  and verification_status = 'VERIFIED'
                limit 1
            ),
            (
                select (value #>> '{}') || '건'
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = due.document_id
                  and source_page = due.source_page
                  and source_text = due.source_text
                  and field = 'content_quantity'
                  and verification_status = 'VERIFIED'
                limit 1
            )
        ),
        (due.value #>> '{}')::date,
        'AGENCY',
        'URL',
        due.document_id,
        due.source_page,
        due.source_text,
        least(
            due.confidence,
            (
                select min(confidence)
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = due.document_id
                  and source_page = due.source_page
                  and source_text = due.source_text
                  and field in (
                      'advertising_channel',
                      'content_type',
                      'content_quantity'
                  )
                  and verification_status = 'VERIFIED'
            )
        ),
        null,
        'PENDING',
        null,
        null,
        false
    from due
    where exists (
        select 1
        from public.extracted_terms
        where analysis_task_id = p_task_id
          and document_id = due.document_id
          and source_page = due.source_page
          and source_text = due.source_text
          and field in ('advertising_channel', 'content_type', 'content_quantity')
          and verification_status = 'VERIFIED'
    )
    on conflict (contract_id) do nothing;

    get diagnostics v_obligation_created = row_count;

    update public.analysis_tasks
    set
        status = 'COMPLETED',
        attempt_count = p_attempt_count,
        error_code = null,
        result = p_result,
        updated_at = now()
    where id = p_task_id
    returning * into v_saved;

    update public.documents
    set parse_status = 'COMPLETED'
    where id = v_task.document_id or id = any(v_task.supporting_document_ids);

    update public.contracts
    set
        signed_date = coalesce(
            signed_date,
            (
                select (value #>> '{}')::date
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = v_task.document_id
                  and source_type = 'CONTRACT_DOCUMENT'
                  and field = 'contract_signed_date'
                  and value_type = 'DATE'
                  and verification_status = 'VERIFIED'
                limit 1
            )
        ),
        start_date = coalesce(
            start_date,
            (
                select (value #>> '{}')::date
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = v_task.document_id
                  and source_type = 'CONTRACT_DOCUMENT'
                  and field = 'contract_start_date'
                  and value_type = 'DATE'
                  and verification_status = 'VERIFIED'
                limit 1
            )
        ),
        end_date = coalesce(
            end_date,
            (
                select (value #>> '{}')::date
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = v_task.document_id
                  and source_type = 'CONTRACT_DOCUMENT'
                  and field = 'contract_end_date'
                  and value_type = 'DATE'
                  and verification_status = 'VERIFIED'
                limit 1
            )
        ),
        termination_notice_date = coalesce(
            termination_notice_date,
            (
                select (value #>> '{}')::date
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = v_task.document_id
                  and source_type = 'CONTRACT_DOCUMENT'
                  and field = 'termination_notice_date'
                  and value_type = 'DATE'
                  and verification_status = 'VERIFIED'
                limit 1
            )
        ),
        renewal_type = coalesce(
            renewal_type,
            (
                select value #>> '{}'
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = v_task.document_id
                  and source_type = 'CONTRACT_DOCUMENT'
                  and field = 'contract_renewal_type'
                  and value_type = 'TEXT'
                  and verification_status = 'VERIFIED'
                  and (value #>> '{}') in ('AUTO', 'MANUAL', 'NONE')
                limit 1
            )
        ),
        total_amount = coalesce(
            total_amount,
            (
                select (value #>> '{}')::bigint
                from public.extracted_terms
                where analysis_task_id = p_task_id
                  and document_id = v_task.document_id
                  and source_type = 'CONTRACT_DOCUMENT'
                  and field = 'contract_total_amount'
                  and value_type = 'MONEY_KRW'
                  and verification_status = 'VERIFIED'
                limit 1
            )
        ),
        status = 'REVIEW_REQUIRED',
        updated_at = now()
    where id = v_task.contract_id;

    if v_obligation_created = 1 then
        insert into public.audit_events (
            contract_id, event_type, actor_type, summary
        )
        values (
            v_task.contract_id,
            'OBLIGATION_CREATED',
            'SYSTEM',
            '대표 산출물 이행 항목을 생성했습니다.'
        );
    end if;

    insert into public.audit_events (
        contract_id, event_type, actor_type, summary
    )
    values (
        v_task.contract_id,
        'ANALYSIS_COMPLETED',
        'SYSTEM',
        '계약 분석을 완료했습니다.'
    );

    return v_saved;
end;
$$;

create or replace function public.fail_analysis_with_audit(
    p_task_id uuid,
    p_attempt_count integer,
    p_error_code text
)
returns public.analysis_tasks
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_task public.analysis_tasks;
    v_saved public.analysis_tasks;
begin
    if p_attempt_count not between 1 and 2
       or p_error_code not in ('DOCUMENT_PARSE_FAILED', 'ANALYSIS_SCHEMA_INVALID') then
        raise exception 'invalid analysis failure payload' using errcode = '22023';
    end if;

    select * into v_task
    from public.analysis_tasks
    where id = p_task_id and status = 'PROCESSING'
    for update;
    if not found then
        return null;
    end if;

    update public.analysis_tasks
    set
        status = 'FAILED',
        attempt_count = p_attempt_count,
        error_code = p_error_code,
        result = null,
        updated_at = now()
    where id = p_task_id
    returning * into v_saved;

    update public.documents
    set parse_status = 'FAILED'
    where id = v_task.document_id;

    insert into public.audit_events (
        contract_id, event_type, actor_type, summary
    )
    values (
        v_task.contract_id,
        'ANALYSIS_FAILED',
        'SYSTEM',
        '계약 분석에 실패했습니다.'
    );

    return v_saved;
end;
$$;

revoke all on function public.start_analysis_with_audit(
    uuid, uuid, uuid, uuid, uuid[], boolean, timestamptz
) from public, anon, authenticated;
grant execute on function public.start_analysis_with_audit(
    uuid, uuid, uuid, uuid, uuid[], boolean, timestamptz
) to service_role;

revoke all on function public.mark_analysis_processing(uuid)
    from public, anon, authenticated;
grant execute on function public.mark_analysis_processing(uuid)
    to service_role;

revoke all on function public.complete_analysis_result_with_audit(uuid, integer, jsonb)
    from public, anon, authenticated;
grant execute on function public.complete_analysis_result_with_audit(uuid, integer, jsonb)
    to service_role;

revoke all on function public.fail_analysis_with_audit(uuid, integer, text)
    from public, anon, authenticated;
grant execute on function public.fail_analysis_with_audit(uuid, integer, text)
    to service_role;
