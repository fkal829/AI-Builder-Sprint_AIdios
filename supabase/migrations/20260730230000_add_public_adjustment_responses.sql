-- C-5: public adjustment view, first-open marker and one-time agency response.
-- Public callers are authorized by a C-3 opaque token before these functions
-- run; raw review item UUIDs never leave the API service.

create table public.adjustment_responses (
  adjustment_request_id uuid not null references public.adjustment_requests(id) on delete cascade,
  review_item_id uuid not null references public.review_items(id) on delete restrict,
  decision text not null check (decision in ('ACCEPT', 'REJECT', 'COUNTER')),
  counter_text text,
  reason text,
  primary key (adjustment_request_id, review_item_id),
  check (
    (decision = 'ACCEPT' and counter_text is null and reason is null)
    or (
      decision = 'REJECT'
      and counter_text is null
      and reason is not null
      and btrim(reason) <> ''
    )
    or (
      decision = 'COUNTER'
      and counter_text is not null
      and reason is not null
      and btrim(counter_text) <> ''
      and btrim(reason) <> ''
    )
  )
);

alter table public.adjustment_responses enable row level security;
revoke all on table public.adjustment_responses from anon, authenticated;
grant select, insert, update, delete on table public.adjustment_responses to service_role;

create or replace function public.adjustment_response_json(p_adjustment_request_id uuid)
returns jsonb
language sql
stable
set search_path = public
as $$
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'review_item_id', response.review_item_id,
        'decision', response.decision,
        'counter_text', response.counter_text,
        'reason', response.reason
      ) order by response.review_item_id
    ),
    '[]'::jsonb
  )
  from public.adjustment_responses response
  where response.adjustment_request_id = p_adjustment_request_id;
$$;

create or replace function public.get_owned_adjustment_detail(
  p_owner_id uuid,
  p_contract_id uuid,
  p_adjustment_request_id uuid
)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'request', public.adjustment_request_json(request.id),
    'responses', public.adjustment_response_json(request.id)
  )
  from public.adjustment_requests request
  join public.contracts contract on contract.id = request.contract_id
  where request.id = p_adjustment_request_id
    and request.contract_id = p_contract_id
    and contract.owner_id = p_owner_id;
$$;

create or replace function public.get_public_adjustment_request(
  p_adjustment_request_id uuid
)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'contract_title', contract.title,
    'request', public.adjustment_request_json(request.id)
  )
  from public.adjustment_requests request
  join public.contracts contract on contract.id = request.contract_id
  where request.id = p_adjustment_request_id;
$$;

create or replace function public.open_public_adjustment_request(
  p_adjustment_request_id uuid,
  p_opened_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_request public.adjustment_requests%rowtype;
begin
  select * into v_request
  from public.adjustment_requests
  where id = p_adjustment_request_id
  for update;

  if not found or v_request.status not in ('SENT', 'OPENED', 'RESPONDED', 'CONFIRMED') then
    return null;
  end if;

  if v_request.status = 'SENT' then
    update public.adjustment_requests
      set status = 'OPENED', opened_at = p_opened_at, updated_at = p_opened_at
      where id = p_adjustment_request_id;
    insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
    values (
      v_request.contract_id,
      'ADJUSTMENT_OPENED',
      'AGENCY',
      '대행사가 조정 요청을 열람했습니다.',
      p_opened_at
    );
  end if;

  return public.adjustment_request_json(p_adjustment_request_id);
end;
$$;

create or replace function public.submit_public_adjustment_responses(
  p_adjustment_request_id uuid,
  p_responded_at timestamptz,
  p_responses jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_request public.adjustment_requests%rowtype;
  v_expected_count integer;
  v_input_count integer;
  v_distinct_input_count integer;
  v_matched_count integer;
begin
  select * into v_request
  from public.adjustment_requests
  where id = p_adjustment_request_id
  for update;

  if not found or v_request.status not in ('SENT', 'OPENED') then
    return null;
  end if;

  select count(*) into v_expected_count
  from public.adjustment_request_items
  where adjustment_request_id = p_adjustment_request_id;
  select count(*), count(distinct response.review_item_id)
    into v_input_count, v_distinct_input_count
  from jsonb_to_recordset(p_responses) as response(
    review_item_id uuid,
    decision text,
    counter_text text,
    reason text
  );
  select count(*) into v_matched_count
  from public.adjustment_request_items expected
  join jsonb_to_recordset(p_responses) as response(
    review_item_id uuid,
    decision text,
    counter_text text,
    reason text
  ) on response.review_item_id = expected.review_item_id
  where expected.adjustment_request_id = p_adjustment_request_id;

  if v_expected_count < 1
    or v_input_count <> v_expected_count
    or v_distinct_input_count <> v_expected_count
    or v_matched_count <> v_expected_count
    or exists (
      select 1
      from jsonb_to_recordset(p_responses) as response(
        review_item_id uuid,
        decision text,
        counter_text text,
        reason text
      )
      where (response.decision = 'ACCEPT' and (response.counter_text is not null or response.reason is not null))
        or (response.decision = 'REJECT' and (
          response.counter_text is not null
          or response.reason is null
          or btrim(response.reason) = ''
        ))
        or (response.decision = 'COUNTER' and (
          response.counter_text is null
          or response.reason is null
          or btrim(response.counter_text) = ''
          or btrim(response.reason) = ''
        ))
        or response.decision is null
        or response.decision not in ('ACCEPT', 'REJECT', 'COUNTER')
    ) then
    return null;
  end if;

  insert into public.adjustment_responses (
    adjustment_request_id, review_item_id, decision, counter_text, reason
  )
  select
    p_adjustment_request_id,
    response.review_item_id,
    response.decision,
    response.counter_text,
    response.reason
  from jsonb_to_recordset(p_responses) as response(
    review_item_id uuid,
    decision text,
    counter_text text,
    reason text
  );

  update public.adjustment_requests
    set status = 'RESPONDED',
        opened_at = coalesce(opened_at, p_responded_at),
        responded_at = p_responded_at,
        updated_at = p_responded_at
    where id = p_adjustment_request_id;
  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (
    v_request.contract_id,
    'ADJUSTMENT_RESPONDED',
    'AGENCY',
    '대행사가 조정 요청에 응답했습니다.',
    p_responded_at
  );

  return public.adjustment_request_json(p_adjustment_request_id);
end;
$$;

revoke all on function public.adjustment_response_json(uuid) from public;
grant execute on function public.adjustment_response_json(uuid) to service_role;
revoke all on function public.get_owned_adjustment_detail(uuid, uuid, uuid) from public;
grant execute on function public.get_owned_adjustment_detail(uuid, uuid, uuid) to service_role;
revoke all on function public.get_public_adjustment_request(uuid) from public;
grant execute on function public.get_public_adjustment_request(uuid) to service_role;
revoke all on function public.open_public_adjustment_request(uuid, timestamptz) from public;
grant execute on function public.open_public_adjustment_request(uuid, timestamptz) to service_role;
revoke all on function public.submit_public_adjustment_responses(uuid, timestamptz, jsonb) from public;
grant execute on function public.submit_public_adjustment_responses(uuid, timestamptz, jsonb) to service_role;
