-- C-2: contract creation and CONTRACT_CREATED audit append are a single
-- transaction.  The shared core schema owns the tables; this function checks
-- for it at call time so migration ordering remains safe.

create or replace function public.create_contract_with_audit(
  p_contract_id uuid,
  p_owner_id uuid,
  p_title text,
  p_counterparty_name text,
  p_created_at timestamptz,
  p_summary text
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_contract jsonb;
begin
  if to_regclass('public.contracts') is null
    or to_regclass('public.audit_events') is null then
    raise exception 'Core contract tables do not exist' using errcode = '42P01';
  end if;

  execute
    'insert into public.contracts as c
       (id, owner_id, title, counterparty_name, status, created_at, updated_at)
     values ($1, $2, $3, $4, ''DRAFT'', $5, $5)
     returning to_jsonb(c)'
    into v_contract
    using p_contract_id, p_owner_id, p_title, p_counterparty_name, p_created_at;

  execute
    'insert into public.audit_events (contract_id, event_type, actor_type, summary)
     values ($1, ''CONTRACT_CREATED'', ''OWNER'', $2)'
    using p_contract_id, p_summary;

  return v_contract;
end;
$$;

revoke all on function public.create_contract_with_audit(uuid, uuid, text, text, timestamptz, text)
  from public;
grant execute on function public.create_contract_with_audit(uuid, uuid, text, text, timestamptz, text)
  to service_role;
