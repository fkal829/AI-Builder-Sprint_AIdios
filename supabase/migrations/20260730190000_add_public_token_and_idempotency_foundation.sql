-- C-3: opaque public-token storage and idempotency reservations.  Neither
-- table contains a raw public token; only a SHA-256 token hash is persisted.

create table if not exists public.public_tokens (
  id uuid primary key,
  token_hash char(64) not null unique,
  scope text not null check (scope in ('ADJUSTMENT_RESPONSE', 'OBLIGATION_EVIDENCE')),
  resource_id uuid not null,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.idempotency_records (
  owner_id uuid not null,
  operation text not null,
  resource_id uuid not null,
  idempotency_key uuid not null,
  request_hash char(64) not null,
  response_status integer,
  response_payload jsonb,
  created_at timestamptz not null default now(),
  primary key (owner_id, operation, resource_id, idempotency_key),
  check (
    (response_status is null and response_payload is null)
    or (response_status between 200 and 599 and response_payload is not null)
  )
);

alter table public.public_tokens enable row level security;
alter table public.idempotency_records enable row level security;
revoke all on table public.public_tokens from anon, authenticated;
revoke all on table public.idempotency_records from anon, authenticated;
grant select, insert, update, delete on table public.public_tokens to service_role;
grant select, insert, update, delete on table public.idempotency_records to service_role;

create or replace function public.claim_idempotency(
  p_owner_id uuid,
  p_operation text,
  p_resource_id uuid,
  p_idempotency_key uuid,
  p_request_hash text,
  p_created_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_record public.idempotency_records%rowtype;
begin
  insert into public.idempotency_records (
    owner_id, operation, resource_id, idempotency_key, request_hash, created_at
  ) values (
    p_owner_id, p_operation, p_resource_id, p_idempotency_key, p_request_hash, p_created_at
  )
  on conflict (owner_id, operation, resource_id, idempotency_key) do nothing
  returning * into v_record;

  if found then
    return jsonb_build_object('outcome', 'NEW', 'record', to_jsonb(v_record));
  end if;

  select * into v_record
    from public.idempotency_records
    where owner_id = p_owner_id
      and operation = p_operation
      and resource_id = p_resource_id
      and idempotency_key = p_idempotency_key
    for update;

  if not found then
    raise exception 'Idempotency reservation disappeared' using errcode = '40001';
  end if;
  if v_record.request_hash <> p_request_hash then
    return jsonb_build_object('outcome', 'CONFLICT', 'record', to_jsonb(v_record));
  end if;
  if v_record.response_status is null then
    return jsonb_build_object('outcome', 'PENDING', 'record', to_jsonb(v_record));
  end if;
  return jsonb_build_object('outcome', 'REPLAY', 'record', to_jsonb(v_record));
end;
$$;

create or replace function public.complete_idempotency(
  p_owner_id uuid,
  p_operation text,
  p_resource_id uuid,
  p_idempotency_key uuid,
  p_request_hash text,
  p_response_status integer,
  p_response_payload jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_record public.idempotency_records%rowtype;
begin
  update public.idempotency_records
    set response_status = p_response_status,
        response_payload = p_response_payload
    where owner_id = p_owner_id
      and operation = p_operation
      and resource_id = p_resource_id
      and idempotency_key = p_idempotency_key
      and request_hash = p_request_hash
      and response_status is null
    returning * into v_record;

  if not found then
    raise exception 'Idempotency reservation is not pending' using errcode = '40001';
  end if;
  return to_jsonb(v_record);
end;
$$;

create or replace function public.abandon_idempotency(
  p_owner_id uuid,
  p_operation text,
  p_resource_id uuid,
  p_idempotency_key uuid,
  p_request_hash text
)
returns void
language sql
set search_path = public
as $$
  delete from public.idempotency_records
    where owner_id = p_owner_id
      and operation = p_operation
      and resource_id = p_resource_id
      and idempotency_key = p_idempotency_key
      and request_hash = p_request_hash
      and response_status is null;
$$;

revoke all on function public.claim_idempotency(uuid, text, uuid, uuid, text, timestamptz)
  from public;
grant execute on function public.claim_idempotency(uuid, text, uuid, uuid, text, timestamptz)
  to service_role;
revoke all on function public.complete_idempotency(uuid, text, uuid, uuid, text, integer, jsonb)
  from public;
grant execute on function public.complete_idempotency(uuid, text, uuid, uuid, text, integer, jsonb)
  to service_role;
revoke all on function public.abandon_idempotency(uuid, text, uuid, uuid, text)
  from public;
grant execute on function public.abandon_idempotency(uuid, text, uuid, uuid, text)
  to service_role;
