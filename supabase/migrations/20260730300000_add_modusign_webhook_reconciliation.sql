-- C-8: authenticated webhook receipts and atomic Modusign status reconciliation.

create table public.modusign_webhook_events (
  id uuid primary key default gen_random_uuid(),
  deduplication_key text not null unique,
  event_id text,
  event_type text not null check (event_type in (
    'document_started', 'document_signed', 'document_all_signed', 'document_rejected',
    'document_request_canceled', 'document_signing_canceled'
  )),
  document_id text not null,
  received_at timestamptz not null,
  processed_at timestamptz,
  created_at timestamptz not null default now()
);

create unique index modusign_webhook_events_event_id_idx
  on public.modusign_webhook_events (event_id)
  where event_id is not null;

alter table public.modusign_webhook_events enable row level security;
revoke all on table public.modusign_webhook_events from anon, authenticated;
grant select, insert, update on table public.modusign_webhook_events to service_role;

create or replace function public.record_modusign_webhook_event(
  p_deduplication_key text,
  p_event_id text,
  p_event_type text,
  p_document_id text,
  p_received_at timestamptz
)
returns boolean
language plpgsql
set search_path = public
as $$
begin
  insert into public.modusign_webhook_events (
    deduplication_key, event_id, event_type, document_id, received_at
  ) values (
    p_deduplication_key, p_event_id, p_event_type, p_document_id, p_received_at
  ) on conflict do nothing;
  return found;
end;
$$;

create or replace function public.mark_modusign_webhook_processed(
  p_deduplication_key text,
  p_processed_at timestamptz
)
returns void
language sql
set search_path = public
as $$
  update public.modusign_webhook_events
  set processed_at = coalesce(processed_at, p_processed_at)
  where deduplication_key = p_deduplication_key;
$$;

create or replace function public.apply_modusign_document_status(
  p_signature_id uuid,
  p_modusign_document_id text,
  p_last_event_id text,
  p_modusign_status text,
  p_processed_at timestamptz
)
returns boolean
language plpgsql
set search_path = public
as $$
declare
  v_signature public.signatures%rowtype;
  v_contract public.contracts%rowtype;
  v_signature_status text;
  v_contract_status text;
  v_audit_event text;
begin
  if p_modusign_status not in (
    'DRAFT', 'SCHEDULED', 'ON_PROCESSING', 'ON_GOING',
    'COMPLETED', 'ABORTED', 'PROCESSING_FAILED'
  ) then
    return false;
  end if;

  select signature.* into v_signature
  from public.signatures signature
  where signature.id = p_signature_id
  for update;
  if not found or v_signature.status in ('COMPLETED', 'ABORTED', 'FAILED') then
    return false;
  end if;
  if v_signature.modusign_document_id is not null
     and v_signature.modusign_document_id <> p_modusign_document_id then
    return false;
  end if;
  if exists (
    select 1 from public.signatures
    where modusign_document_id = p_modusign_document_id and id <> p_signature_id
  ) then
    return false;
  end if;

  select * into v_contract from public.contracts where id = v_signature.contract_id for update;
  if not found then
    return false;
  end if;

  v_signature_status := v_signature.status;
  v_contract_status := v_contract.status;
  v_audit_event := null;

  if p_modusign_status = 'ON_GOING' then
    if v_signature.status = 'EDITING' and v_contract.status = 'READY_TO_SIGN' then
      v_signature_status := 'SIGNING';
      v_contract_status := 'SIGNING';
      v_audit_event := 'SIGNATURE_STARTED';
    elsif v_signature.status <> 'SIGNING' then
      return false;
    end if;
  elsif p_modusign_status = 'COMPLETED' then
    if v_signature.status not in ('EDITING', 'SIGNING')
       or v_contract.status not in ('READY_TO_SIGN', 'SIGNING') then
      return false;
    end if;
    v_signature_status := 'COMPLETED';
    v_contract_status := 'SIGNED';
    v_audit_event := 'SIGNATURE_COMPLETED';
  elsif p_modusign_status = 'ABORTED' then
    if v_signature.status not in ('EDITING', 'SIGNING') then
      return false;
    end if;
    v_signature_status := 'ABORTED';
    if v_contract.status = 'SIGNING' then v_contract_status := 'READY_TO_SIGN'; end if;
    v_audit_event := 'SIGNATURE_ABORTED';
  elsif p_modusign_status = 'PROCESSING_FAILED' then
    if v_signature.status not in ('EDITING', 'SIGNING') then
      return false;
    end if;
    v_signature_status := 'FAILED';
    if v_contract.status = 'SIGNING' then v_contract_status := 'READY_TO_SIGN'; end if;
    v_audit_event := 'SIGNATURE_FAILED';
  elsif v_signature.status <> 'EDITING' then
    return false;
  end if;

  update public.signatures
  set modusign_document_id = p_modusign_document_id,
      modusign_status = p_modusign_status,
      last_event_id = p_last_event_id,
      status = v_signature_status,
      completed_at = case
        when v_signature_status in ('COMPLETED', 'ABORTED', 'FAILED') then p_processed_at
        else completed_at
      end
  where id = p_signature_id;

  if v_contract_status <> v_contract.status then
    update public.contracts set status = v_contract_status where id = v_contract.id;
  end if;
  if v_audit_event is not null then
    insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
    values (v_contract.id, v_audit_event, 'SYSTEM', 'Modusign document status was reconciled.', p_processed_at);
  end if;
  return true;
end;
$$;

revoke all on function public.record_modusign_webhook_event(text, text, text, text, timestamptz) from public;
grant execute on function public.record_modusign_webhook_event(text, text, text, text, timestamptz) to service_role;
revoke all on function public.mark_modusign_webhook_processed(text, timestamptz) from public;
grant execute on function public.mark_modusign_webhook_processed(text, timestamptz) to service_role;
revoke all on function public.apply_modusign_document_status(uuid, text, text, text, timestamptz) from public;
grant execute on function public.apply_modusign_document_status(uuid, text, text, text, timestamptz) to service_role;
