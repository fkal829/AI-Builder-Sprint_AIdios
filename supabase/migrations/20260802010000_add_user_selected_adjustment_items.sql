-- Allow an owner-selected document clause to travel through the existing adjustment lifecycle.
-- The public API sends only the deterministic document_clause_id and request copy. This RPC
-- resolves source evidence from the latest completed analysis before creating a review-item key.

alter table public.review_items
  add column if not exists origin text not null default 'ANALYSIS'
    check (origin in ('ANALYSIS', 'USER_SELECTED')),
  add column if not exists document_clause_id uuid;

create unique index if not exists review_items_user_selected_clause_idx
  on public.review_items (contract_id, document_clause_id)
  where origin = 'USER_SELECTED';

do $$
declare
  constraint_name text;
begin
  for constraint_name in
    select con.conname
    from pg_constraint con
    where con.conrelid = 'public.review_items'::regclass
      and con.contype = 'c'
      and pg_get_constraintdef(con.oid) like '%cardinality(related_extracted_term_ids)%'
  loop
    execute format('alter table public.review_items drop constraint %I', constraint_name);
  end loop;
end;
$$;

alter table public.review_items
  add constraint review_items_related_evidence_by_origin_check check (
    (
      origin = 'ANALYSIS'
      and cardinality(related_extracted_term_ids) between 1 and 11
      and document_clause_id is null
    )
    or
    (
      origin = 'USER_SELECTED'
      and cardinality(related_extracted_term_ids) = 0
      and document_clause_id is not null
      and type = 'NEEDS_CHECK'
      and detection_method = 'DETERMINISTIC'
    )
  );

do $$
declare
  constraint_name text;
begin
  for constraint_name in
    select con.conname
    from pg_constraint con
    where con.conrelid = 'public.review_items'::regclass
      and con.contype = 'c'
      and pg_get_constraintdef(con.oid) like '%source_document_id%'
      and pg_get_constraintdef(con.oid) like '%source_page%'
      and pg_get_constraintdef(con.oid) like '%source_text%'
      and pg_get_constraintdef(con.oid) like '%source_confidence%'
  loop
    execute format('alter table public.review_items drop constraint %I', constraint_name);
  end loop;
end;
$$;

alter table public.review_items
  add constraint review_items_source_evidence_bundle_check check (
    (
      source_document_id is null
      and source_page is null
      and source_text is null
      and source_confidence is null
    )
    or
    (
      source_document_id is not null
      and source_page is not null
      and source_text is not null
    )
  );

create or replace function public.enforce_review_item_evidence_links()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.origin = 'USER_SELECTED' then
    if new.verification_status <> 'NEEDS_CHECK'
      or new.source_document_id is null
      or not exists (
        select 1
        from public.analysis_tasks task
        cross join lateral jsonb_array_elements(
          coalesce(task.result->'document_clauses', '[]'::jsonb)
        ) clause
        where task.id = new.analysis_task_id
          and task.contract_id = new.contract_id
          and task.status = 'COMPLETED'
          and (clause->>'id')::uuid = new.document_clause_id
          and (clause->>'document_id')::uuid = new.source_document_id
          and (clause->>'source_page')::integer = new.source_page
          and clause->>'source_text' = new.source_text
          and new.source_confidence is not distinct from case
            when clause->'confidence' is null or clause->'confidence' = 'null'::jsonb then null
            else (clause->>'confidence')::double precision
          end
      )
    then
      raise exception 'user-selected review item must match a document clause'
        using errcode = '23514';
    end if;
    return new;
  end if;

  if cardinality(new.related_extracted_term_ids) <> (
    select count(distinct related_id)
    from unnest(new.related_extracted_term_ids) as related(related_id)
  ) then
    raise exception 'review item related extracted terms must be unique'
      using errcode = '23514';
  end if;

  if exists (
    select 1
    from unnest(new.related_extracted_term_ids) as related(related_id)
    left join public.extracted_terms term
      on term.id = related_id
     and term.analysis_task_id = new.analysis_task_id
     and term.contract_id = new.contract_id
    where term.id is null
  ) then
    raise exception 'review item evidence must belong to the same analysis result'
      using errcode = '23514';
  end if;

  if (
    new.verification_status in ('VERIFIED', 'NEEDS_CHECK')
    and new.source_document_id is null
  ) or (
    new.verification_status in ('NOT_FOUND', 'MISSING_EVIDENCE')
    and new.source_document_id is not null
  ) then
    raise exception 'review item evidence fields do not match verification status'
      using errcode = '23514';
  end if;

  if new.source_document_id is not null and not exists (
    select 1
    from public.extracted_terms term
    where term.id = any(new.related_extracted_term_ids)
      and term.analysis_task_id = new.analysis_task_id
      and term.contract_id = new.contract_id
      and term.source_type = 'CONTRACT_DOCUMENT'
      and term.verification_status in ('VERIFIED', 'NEEDS_CHECK')
      and term.document_id = new.source_document_id
      and term.source_page = new.source_page
      and term.source_text = new.source_text
      and term.confidence = new.source_confidence
  ) then
    raise exception 'review item source fields must match a related contract term'
      using errcode = '23514';
  end if;

  return new;
end;
$$;

drop function if exists public.create_adjustment_draft_with_audit(
  uuid, uuid, uuid, integer, uuid[], timestamptz
);

create function public.create_adjustment_draft_with_audit(
  p_owner_id uuid,
  p_adjustment_request_id uuid,
  p_contract_id uuid,
  p_expires_in_hours integer,
  p_items jsonb,
  p_manual_items jsonb,
  p_created_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_count integer;
  v_item_count integer;
  v_manual_count integer;
begin
  if not exists (
    select 1 from public.contracts where id = p_contract_id and owner_id = p_owner_id
  ) then
    return null;
  end if;

  if jsonb_typeof(p_items) <> 'array' or jsonb_typeof(p_manual_items) <> 'array' then
    return null;
  end if;
  v_item_count := jsonb_array_length(p_items);
  v_manual_count := jsonb_array_length(p_manual_items);
  if v_item_count not between 1 and 4 or v_manual_count > v_item_count then
    return null;
  end if;

  select count(*) into v_count
  from jsonb_to_recordset(p_items) as item(
    review_item_id uuid,
    user_choice text,
    request_text text
  )
  where item.user_choice in ('COMPROMISE', 'REQUEST')
    and btrim(item.request_text) <> ''
    and char_length(btrim(item.request_text)) <= 1200;
  if v_count <> v_item_count then
    return null;
  end if;

  with latest_analysis as (
    select task.id, task.document_id, task.result
    from public.analysis_tasks task
    where task.contract_id = p_contract_id
      and task.status = 'COMPLETED'
      and task.result is not null
    order by task.created_at desc, task.id desc
    limit 1
  ),
  requested_manual as (
    select *
    from jsonb_to_recordset(p_manual_items) as item(
      review_item_id uuid,
      document_clause_id uuid
    )
  ),
  resolved_manual as (
    select
      requested.review_item_id,
      requested.document_clause_id,
      analysis.id as analysis_task_id,
      analysis.document_id,
      (clause->>'source_page')::integer as source_page,
      clause->>'source_text' as source_text,
      case
        when clause->'confidence' is null or clause->'confidence' = 'null'::jsonb then null
        else (clause->>'confidence')::double precision
      end as source_confidence
    from latest_analysis analysis
    cross join lateral jsonb_array_elements(
      coalesce(analysis.result->'document_clauses', '[]'::jsonb)
    ) clause
    join requested_manual requested
      on requested.document_clause_id = (clause->>'id')::uuid
     and analysis.document_id = (clause->>'document_id')::uuid
  )
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
    status,
    category,
    original_text,
    origin,
    document_clause_id,
    created_at,
    updated_at
  )
  select
    manual.review_item_id,
    manual.analysis_task_id,
    p_contract_id,
    'NEEDS_CHECK',
    'INFO',
    'DETERMINISTIC',
    null,
    null,
    '사용자가 계약 원문 조항을 직접 선택해 조정을 요청했습니다.',
    'INTERNAL_RULE',
    '사용자가 직접 선택한 계약 원문 조항',
    null,
    '{}'::uuid[],
    manual.document_id,
    manual.source_page,
    manual.source_text,
    manual.source_confidence,
    'NEEDS_CHECK',
    '현재 계약 원문을 그대로 유지합니다.',
    requested.request_text,
    requested.request_text,
    'REQUEST',
    'SELECTED',
    'OTHER',
    manual.source_text,
    'USER_SELECTED',
    manual.document_clause_id,
    p_created_at,
    p_created_at
  from resolved_manual manual
  join jsonb_to_recordset(p_items) as requested(
    review_item_id uuid,
    user_choice text,
    request_text text
  ) on requested.review_item_id = manual.review_item_id
  where requested.user_choice = 'REQUEST'
  on conflict do nothing;

  select count(*) into v_count
  from jsonb_to_recordset(p_manual_items) as requested(
    review_item_id uuid,
    document_clause_id uuid
  )
  join public.review_items review
    on review.id = requested.review_item_id
   and review.contract_id = p_contract_id
   and review.origin = 'USER_SELECTED'
   and review.document_clause_id = requested.document_clause_id;
  if v_count <> v_manual_count then
    return null;
  end if;

  select count(*) into v_count
  from jsonb_to_recordset(p_items) as requested(
    review_item_id uuid,
    user_choice text,
    request_text text
  )
  join public.review_items review
    on review.id = requested.review_item_id
   and review.contract_id = p_contract_id
   and review.status = 'SELECTED'
   and review.user_choice = requested.user_choice;
  if v_count <> v_item_count then
    return null;
  end if;

  insert into public.adjustment_requests (
    id, contract_id, status, expires_in_hours, created_at, updated_at
  ) values (
    p_adjustment_request_id, p_contract_id, 'DRAFT', p_expires_in_hours, p_created_at, p_created_at
  );

  insert into public.adjustment_request_items (
    adjustment_request_id, review_item_id, user_choice, request_text
  )
  select
    p_adjustment_request_id,
    requested.review_item_id,
    requested.user_choice,
    btrim(requested.request_text)
  from jsonb_to_recordset(p_items) with ordinality as requested(
    review_item_id uuid,
    user_choice text,
    request_text text,
    position bigint
  )
  order by requested.position;

  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (
    p_contract_id,
    'ADJUSTMENT_DRAFT_CREATED',
    'OWNER',
    '조정 요청 초안을 생성했습니다.',
    p_created_at
  );

  return public.adjustment_request_json(p_adjustment_request_id);
end;
$$;

revoke all on function public.create_adjustment_draft_with_audit(
  uuid, uuid, uuid, integer, jsonb, jsonb, timestamptz
) from public, anon, authenticated;
grant execute on function public.create_adjustment_draft_with_audit(
  uuid, uuid, uuid, integer, jsonb, jsonb, timestamptz
) to service_role;
