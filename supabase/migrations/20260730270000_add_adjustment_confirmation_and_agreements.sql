-- C-6: final owner confirmation and deterministic agreement persistence.

alter table public.review_items
  add column if not exists category text not null default 'OTHER'
    check (category in ('TERM_AND_PAYMENT', 'DELIVERABLES', 'TERMINATION_AND_RENEWAL', 'RIGHTS_AND_SAFETY', 'OTHER')),
  add column if not exists original_text text not null default '원계약에서 확인되지 않아 추가 확인 필요'
    check (btrim(original_text) <> '');

create or replace function public.adjustment_request_json(p_adjustment_request_id uuid)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'id', request.id,
    'contract_id', request.contract_id,
    'status', request.status,
    'expires_in_hours', request.expires_in_hours,
    'sent_at', request.sent_at,
    'expires_at', request.expires_at,
    'opened_at', request.opened_at,
    'responded_at', request.responded_at,
    'created_at', request.created_at,
    'updated_at', request.updated_at,
    'items', coalesce(
      (
        select jsonb_agg(
          jsonb_build_object(
            'review_item_id', item.review_item_id,
            'user_choice', item.user_choice,
            'request_text', item.request_text,
            'category', review.category,
            'before_text', review.original_text
          ) order by item.review_item_id
        )
        from public.adjustment_request_items item
        join public.review_items review on review.id = item.review_item_id
        where item.adjustment_request_id = request.id
      ),
      '[]'::jsonb
    )
  )
  from public.adjustment_requests request
  where request.id = p_adjustment_request_id;
$$;

create table public.adjustment_final_clauses (
  adjustment_request_id uuid not null references public.adjustment_requests(id) on delete cascade,
  review_item_id uuid not null references public.review_items(id) on delete restrict,
  category text not null check (category in ('TERM_AND_PAYMENT', 'DELIVERABLES', 'TERMINATION_AND_RENEWAL', 'RIGHTS_AND_SAFETY', 'OTHER')),
  resolution text not null check (resolution in ('ACCEPT_REQUEST', 'ACCEPT_COUNTERPROPOSAL', 'KEEP_ORIGINAL')),
  outcome text not null check (outcome in ('AGREED', 'KEPT_ORIGINAL')),
  disposition text not null check (disposition in ('AGREED', 'REJECTED', 'WITHDRAWN')),
  before_text text not null check (btrim(before_text) <> ''),
  after_text text not null check (btrim(after_text) <> ''),
  reason text,
  primary key (adjustment_request_id, review_item_id),
  check (
    (outcome = 'AGREED' and disposition = 'AGREED')
    or (outcome = 'KEPT_ORIGINAL' and disposition in ('REJECTED', 'WITHDRAWN'))
  ),
  check (disposition <> 'REJECTED' or (reason is not null and btrim(reason) <> ''))
);

create table public.agreements (
  id uuid primary key,
  contract_id uuid not null references public.contracts(id) on delete cascade,
  adjustment_request_id uuid not null unique references public.adjustment_requests(id) on delete restrict,
  version integer not null check (version >= 1),
  agreement jsonb not null,
  created_at timestamptz not null default now(),
  unique (contract_id, version)
);

alter table public.adjustment_final_clauses enable row level security;
alter table public.agreements enable row level security;
revoke all on table public.adjustment_final_clauses, public.agreements from anon, authenticated;
grant select, insert, update, delete on table public.adjustment_final_clauses, public.agreements to service_role;

create or replace function public.confirm_adjustment_with_audit(
  p_owner_id uuid,
  p_contract_id uuid,
  p_adjustment_request_id uuid,
  p_confirmed_at timestamptz,
  p_confirmed_items jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_request public.adjustment_requests%rowtype;
  v_expected_count integer;
  v_input_count integer;
  v_distinct_count integer;
  v_matched_count integer;
begin
  if not exists (
    select 1 from public.contracts
    where id = p_contract_id and owner_id = p_owner_id and status = 'NEGOTIATING'
    for update
  ) then
    return null;
  end if;

  select * into v_request
  from public.adjustment_requests
  where id = p_adjustment_request_id
    and contract_id = p_contract_id
    and status = 'RESPONDED'
  for update;
  if not found then
    return null;
  end if;

  select count(*) into v_expected_count
  from public.adjustment_request_items
  where adjustment_request_id = p_adjustment_request_id;
  select count(*), count(distinct item.review_item_id)
    into v_input_count, v_distinct_count
  from jsonb_to_recordset(p_confirmed_items) as item(review_item_id uuid, resolution text);
  select count(*) into v_matched_count
  from public.adjustment_request_items expected
  join jsonb_to_recordset(p_confirmed_items) as item(review_item_id uuid, resolution text)
    on item.review_item_id = expected.review_item_id
  where expected.adjustment_request_id = p_adjustment_request_id;
  if v_expected_count < 1
    or v_input_count <> v_expected_count
    or v_distinct_count <> v_expected_count
    or v_matched_count <> v_expected_count
    or exists (
      select 1
      from jsonb_to_recordset(p_confirmed_items) as item(review_item_id uuid, resolution text)
      join public.adjustment_responses response
        on response.adjustment_request_id = p_adjustment_request_id
       and response.review_item_id = item.review_item_id
      where item.resolution not in ('ACCEPT_REQUEST', 'ACCEPT_COUNTERPROPOSAL', 'KEEP_ORIGINAL')
        or (item.resolution = 'ACCEPT_REQUEST' and response.decision <> 'ACCEPT')
        or (item.resolution = 'ACCEPT_COUNTERPROPOSAL' and response.decision <> 'COUNTER')
    )
    or exists (
      select 1
      from public.adjustment_request_items item
      join public.review_items review on review.id = item.review_item_id
      where item.adjustment_request_id = p_adjustment_request_id
        and review.status <> 'SENT'
    ) then
    return null;
  end if;

  insert into public.adjustment_final_clauses (
    adjustment_request_id, review_item_id, category, resolution, outcome,
    disposition, before_text, after_text, reason
  )
  select
    p_adjustment_request_id,
    item.review_item_id,
    review.category,
    confirmed.resolution,
    case when confirmed.resolution = 'KEEP_ORIGINAL' then 'KEPT_ORIGINAL' else 'AGREED' end,
    case
      when confirmed.resolution <> 'KEEP_ORIGINAL' then 'AGREED'
      when response.decision = 'REJECT' then 'REJECTED'
      else 'WITHDRAWN'
    end,
    review.original_text,
    case
      when confirmed.resolution = 'ACCEPT_REQUEST' then item.request_text
      when confirmed.resolution = 'ACCEPT_COUNTERPROPOSAL' then response.counter_text
      else review.original_text
    end,
    case
      when confirmed.resolution <> 'KEEP_ORIGINAL' then null
      when response.decision = 'REJECT' then response.reason
      else '소상공인이 원계약 유지를 선택했습니다.'
    end
  from public.adjustment_request_items item
  join public.review_items review on review.id = item.review_item_id
  join public.adjustment_responses response
    on response.adjustment_request_id = item.adjustment_request_id
   and response.review_item_id = item.review_item_id
  join jsonb_to_recordset(p_confirmed_items) as confirmed(review_item_id uuid, resolution text)
    on confirmed.review_item_id = item.review_item_id
  where item.adjustment_request_id = p_adjustment_request_id;

  update public.review_items review
    set status = case
      when confirmed.resolution = 'KEEP_ORIGINAL' then 'KEPT_ORIGINAL'
      else 'RESOLVED'
    end
  from jsonb_to_recordset(p_confirmed_items) as confirmed(review_item_id uuid, resolution text)
  where review.id = confirmed.review_item_id;
  update public.adjustment_requests
    set status = 'CONFIRMED', updated_at = p_confirmed_at
    where id = p_adjustment_request_id;
  update public.contracts
    set status = 'READY_TO_SIGN', updated_at = p_confirmed_at
    where id = p_contract_id and status = 'NEGOTIATING';
  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (p_contract_id, 'ADJUSTMENT_CONFIRMED', 'OWNER', '조정 결과를 확정했습니다.', p_confirmed_at);

  return public.adjustment_request_json(p_adjustment_request_id);
end;
$$;

create or replace function public.get_agreement_creation_context(
  p_owner_id uuid,
  p_contract_id uuid
)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'contract', to_jsonb(contract),
    'original_document_id', document.id,
    'adjustment_request_id', request.id,
    'final_clauses', coalesce(
      (
        select jsonb_agg(
          jsonb_build_object(
            'review_item_id', clause.review_item_id,
            'category', clause.category,
            'resolution', clause.resolution,
            'outcome', clause.outcome,
            'disposition', clause.disposition,
            'before_text', clause.before_text,
            'after_text', clause.after_text,
            'reason', clause.reason
          ) order by clause.review_item_id
        )
        from public.adjustment_final_clauses clause
        where clause.adjustment_request_id = request.id
      ),
      '[]'::jsonb
    )
  )
  from public.contracts contract
  join public.adjustment_requests request
    on request.contract_id = contract.id and request.status = 'CONFIRMED'
  left join lateral (
    select id from public.documents
    where contract_id = contract.id and type = 'CONTRACT'
    order by created_at desc, id desc
    limit 1
  ) document on true
  where contract.id = p_contract_id and contract.owner_id = p_owner_id;
$$;

create or replace function public.create_agreement_with_audit(
  p_owner_id uuid,
  p_contract_id uuid,
  p_agreement_id uuid,
  p_adjustment_request_id uuid,
  p_agreement jsonb,
  p_created_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_version integer;
  v_record public.agreements%rowtype;
begin
  if not exists (
    select 1 from public.contracts
    where id = p_contract_id
      and owner_id = p_owner_id
      and status = 'READY_TO_SIGN'
      and signed_date is not null
    for update
  )
    or not exists (
      select 1 from public.adjustment_requests
      where id = p_adjustment_request_id
        and contract_id = p_contract_id
        and status = 'CONFIRMED'
    )
    or not exists (
      select 1 from public.documents
      where id = nullif(p_agreement #>> '{original_contract,document_id}', '')::uuid
        and contract_id = p_contract_id
        and type = 'CONTRACT'
    )
    or exists (select 1 from public.agreements where contract_id = p_contract_id)
  then
    return null;
  end if;
  select coalesce(max(version), 0) + 1 into v_version
  from public.agreements where contract_id = p_contract_id;

  insert into public.agreements (
    id, contract_id, adjustment_request_id, version, agreement, created_at
  ) values (
    p_agreement_id, p_contract_id, p_adjustment_request_id, v_version,
    jsonb_set(p_agreement, '{version}', to_jsonb(v_version)), p_created_at
  ) returning * into v_record;
  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (p_contract_id, 'AGREEMENT_CREATED', 'OWNER', '변경·확인 합의서를 생성했습니다.', p_created_at);
  return jsonb_build_object(
    'agreement', v_record.agreement,
    'adjustment_request_id', v_record.adjustment_request_id,
    'created_at', v_record.created_at
  );
end;
$$;

create or replace function public.get_owned_agreement(
  p_owner_id uuid,
  p_contract_id uuid
)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'agreement', agreement.agreement,
    'adjustment_request_id', agreement.adjustment_request_id,
    'created_at', agreement.created_at
  )
  from public.agreements agreement
  join public.contracts contract on contract.id = agreement.contract_id
  where agreement.contract_id = p_contract_id and contract.owner_id = p_owner_id
  order by agreement.version desc
  limit 1;
$$;

revoke all on function public.confirm_adjustment_with_audit(uuid, uuid, uuid, timestamptz, jsonb) from public;
grant execute on function public.confirm_adjustment_with_audit(uuid, uuid, uuid, timestamptz, jsonb) to service_role;
revoke all on function public.get_agreement_creation_context(uuid, uuid) from public;
grant execute on function public.get_agreement_creation_context(uuid, uuid) to service_role;
revoke all on function public.create_agreement_with_audit(uuid, uuid, uuid, uuid, jsonb, timestamptz) from public;
grant execute on function public.create_agreement_with_audit(uuid, uuid, uuid, uuid, jsonb, timestamptz) to service_role;
revoke all on function public.get_owned_agreement(uuid, uuid) from public;
grant execute on function public.get_owned_agreement(uuid, uuid) to service_role;
