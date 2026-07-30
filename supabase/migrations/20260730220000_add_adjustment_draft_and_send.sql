-- C-4: owner adjustment draft and explicit send.  B will extend review_items
-- with analysis evidence fields; C only depends on the selection and wording
-- fields declared below.

create table if not exists public.review_items (
  id uuid primary key,
  contract_id uuid not null references public.contracts(id) on delete cascade,
  status text not null check (status in ('UNREVIEWED', 'SELECTED', 'SENT', 'RESOLVED', 'KEPT_ORIGINAL')),
  user_choice text check (user_choice in ('ACCEPT', 'COMPROMISE', 'REQUEST')),
  suggestion_compromise text not null check (btrim(suggestion_compromise) <> ''),
  suggestion_request text not null check (btrim(suggestion_request) <> '')
);

create index if not exists review_items_contract_id_idx on public.review_items (contract_id, id);

create table if not exists public.adjustment_requests (
  id uuid primary key,
  contract_id uuid not null references public.contracts(id) on delete cascade,
  status text not null check (status in ('DRAFT', 'SENT', 'OPENED', 'RESPONDED', 'CONFIRMED', 'EXPIRED')),
  expires_in_hours integer not null check (expires_in_hours between 1 and 168),
  sent_at timestamptz,
  expires_at timestamptz,
  opened_at timestamptz,
  responded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    (status = 'DRAFT' and sent_at is null and expires_at is null and opened_at is null and responded_at is null)
    or (status <> 'DRAFT' and sent_at is not null and expires_at is not null)
  )
);

create index if not exists adjustment_requests_contract_id_idx
  on public.adjustment_requests (contract_id, created_at, id);

create table if not exists public.adjustment_request_items (
  adjustment_request_id uuid not null references public.adjustment_requests(id) on delete cascade,
  review_item_id uuid not null references public.review_items(id) on delete restrict,
  user_choice text not null check (user_choice in ('COMPROMISE', 'REQUEST')),
  request_text text not null check (btrim(request_text) <> ''),
  primary key (adjustment_request_id, review_item_id)
);

alter table public.review_items enable row level security;
alter table public.adjustment_requests enable row level security;
alter table public.adjustment_request_items enable row level security;
revoke all on table public.review_items, public.adjustment_requests, public.adjustment_request_items
  from anon, authenticated;
grant select, insert, update, delete on table public.review_items, public.adjustment_requests,
  public.adjustment_request_items to service_role;

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
            'request_text', item.request_text
          ) order by item.review_item_id
        )
        from public.adjustment_request_items item
        where item.adjustment_request_id = request.id
      ),
      '[]'::jsonb
    )
  )
  from public.adjustment_requests request
  where request.id = p_adjustment_request_id;
$$;

create or replace function public.create_adjustment_draft_with_audit(
  p_owner_id uuid,
  p_adjustment_request_id uuid,
  p_contract_id uuid,
  p_expires_in_hours integer,
  p_review_item_ids uuid[],
  p_created_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_count integer;
begin
  if not exists (
    select 1 from public.contracts where id = p_contract_id and owner_id = p_owner_id
  ) then
    return null;
  end if;

  select count(*) into v_count
  from public.review_items
  where contract_id = p_contract_id
    and id = any(p_review_item_ids)
    and status = 'SELECTED'
    and user_choice in ('COMPROMISE', 'REQUEST');
  if v_count <> cardinality(p_review_item_ids) then
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
    selected.review_item_id,
    review.user_choice,
    case review.user_choice
      when 'COMPROMISE' then review.suggestion_compromise
      else review.suggestion_request
    end
  from unnest(p_review_item_ids) with ordinality as selected(review_item_id, position)
  join public.review_items review on review.id = selected.review_item_id
  order by selected.position;

  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (p_contract_id, 'ADJUSTMENT_DRAFT_CREATED', 'OWNER', '조정 요청 초안을 생성했습니다.', p_created_at);

  return public.adjustment_request_json(p_adjustment_request_id);
end;
$$;

create or replace function public.get_owned_adjustment_request(
  p_owner_id uuid,
  p_contract_id uuid,
  p_adjustment_request_id uuid
)
returns jsonb
language sql
stable
set search_path = public
as $$
  select public.adjustment_request_json(request.id)
  from public.adjustment_requests request
  join public.contracts contract on contract.id = request.contract_id
  where request.id = p_adjustment_request_id
    and request.contract_id = p_contract_id
    and contract.owner_id = p_owner_id;
$$;

create or replace function public.send_adjustment_with_audit(
  p_owner_id uuid,
  p_contract_id uuid,
  p_adjustment_request_id uuid,
  p_sent_at timestamptz,
  p_public_token_id uuid,
  p_token_hash text,
  p_token_scope text,
  p_token_resource_id uuid,
  p_token_expires_at timestamptz,
  p_token_created_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_expires_at timestamptz;
  v_item_count integer;
  v_selected_count integer;
begin
  if not exists (
    select 1 from public.contracts
    where id = p_contract_id and owner_id = p_owner_id and status = 'REVIEW_REQUIRED'
    for update
  ) then
    return null;
  end if;
  if exists (
    select 1 from public.adjustment_requests
    where contract_id = p_contract_id and sent_at is not null
  ) then
    return null;
  end if;
  if not exists (
    select 1 from public.adjustment_requests
    where id = p_adjustment_request_id and contract_id = p_contract_id and status = 'DRAFT'
    for update
  ) then
    return null;
  end if;

  select count(*) into v_item_count
  from public.adjustment_request_items
  where adjustment_request_id = p_adjustment_request_id;
  select count(*) into v_selected_count
  from public.adjustment_request_items item
  join public.review_items review on review.id = item.review_item_id
  where item.adjustment_request_id = p_adjustment_request_id
    and review.status = 'SELECTED'
    and review.user_choice = item.user_choice;
  if v_item_count < 1 or v_item_count <> v_selected_count then
    return null;
  end if;

  select p_sent_at + make_interval(hours => expires_in_hours) into v_expires_at
  from public.adjustment_requests where id = p_adjustment_request_id;
  if p_token_scope <> 'ADJUSTMENT_RESPONSE'
    or p_token_resource_id <> p_adjustment_request_id
    or p_token_expires_at <> v_expires_at then
    return null;
  end if;

  update public.adjustment_requests
    set status = 'SENT', sent_at = p_sent_at, expires_at = v_expires_at, updated_at = p_sent_at
    where id = p_adjustment_request_id;
  update public.review_items review
    set status = 'SENT'
    from public.adjustment_request_items item
    where item.adjustment_request_id = p_adjustment_request_id
      and item.review_item_id = review.id;
  update public.contracts
    set status = 'NEGOTIATING', updated_at = p_sent_at
    where id = p_contract_id and status = 'REVIEW_REQUIRED';
  insert into public.public_tokens (
    id, token_hash, scope, resource_id, expires_at, revoked_at, created_at
  ) values (
    p_public_token_id, p_token_hash, p_token_scope, p_token_resource_id,
    p_token_expires_at, null, p_token_created_at
  );
  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (p_contract_id, 'ADJUSTMENT_SENT', 'OWNER', '조정 요청을 발송했습니다.', p_sent_at);

  return public.adjustment_request_json(p_adjustment_request_id);
end;
$$;

revoke all on function public.create_adjustment_draft_with_audit(uuid, uuid, uuid, integer, uuid[], timestamptz)
  from public;
grant execute on function public.create_adjustment_draft_with_audit(uuid, uuid, uuid, integer, uuid[], timestamptz)
  to service_role;
revoke all on function public.get_owned_adjustment_request(uuid, uuid, uuid) from public;
grant execute on function public.get_owned_adjustment_request(uuid, uuid, uuid) to service_role;
revoke all on function public.send_adjustment_with_audit(uuid, uuid, uuid, timestamptz, uuid, text, text, uuid, timestamptz, timestamptz)
  from public;
grant execute on function public.send_adjustment_with_audit(uuid, uuid, uuid, timestamptz, uuid, text, text, uuid, timestamptz, timestamptz)
  to service_role;
