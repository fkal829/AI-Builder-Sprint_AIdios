-- C-7: embedded Modusign drafts are stored separately from the short-lived editor URL.

alter table public.audit_events
  drop constraint if exists audit_events_event_type_check;

alter table public.audit_events
  add constraint audit_events_event_type_check
  check (event_type in (
    'CONTRACT_CREATED', 'CONTRACT_STARTED', 'CONTRACT_COMPLETED', 'CONTRACT_RENEWAL_DUE',
    'DOCUMENT_UPLOADED', 'UNDERSTOOD_TERMS_SAVED',
    'ANALYSIS_STARTED', 'ANALYSIS_RESTARTED', 'ANALYSIS_COMPLETED', 'ANALYSIS_FAILED',
    'REVIEW_ITEM_SELECTION_UPDATED',
    'ADJUSTMENT_DRAFT_CREATED', 'ADJUSTMENT_SENT', 'ADJUSTMENT_OPENED',
    'ADJUSTMENT_RESPONDED', 'ADJUSTMENT_CONFIRMED', 'ADJUSTMENT_EXPIRED',
    'AGREEMENT_CREATED',
    'SIGNATURE_DRAFT_CREATED', 'SIGNATURE_REQUESTED', 'SIGNATURE_STARTED',
    'SIGNATURE_COMPLETED', 'SIGNATURE_ABORTED', 'SIGNATURE_FAILED',
    'OBLIGATION_CREATED', 'EVIDENCE_LINK_CREATED', 'EVIDENCE_SUBMITTED',
    'EVIDENCE_APPROVED', 'EVIDENCE_DISPUTED', 'RENEWAL_DECISION_SAVED'
  ));

create table public.signatures (
  id uuid primary key,
  contract_id uuid not null references public.contracts(id) on delete cascade,
  agreement_id uuid not null references public.agreements(id) on delete restrict,
  agreement_version integer not null check (agreement_version >= 1),
  idempotency_key uuid not null,
  status text not null check (status in ('REQUEST_READY', 'REQUESTING', 'EDITING', 'SIGNING', 'COMPLETED', 'ABORTED', 'FAILED')),
  modusign_status text check (modusign_status in ('DRAFT', 'SCHEDULED', 'ON_PROCESSING', 'ON_GOING', 'COMPLETED', 'ABORTED', 'PROCESSING_FAILED')),
  modusign_draft_id text unique,
  modusign_document_id text unique,
  last_event_id text,
  requested_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  check (
    (status = 'REQUESTING' and requested_at is not null and completed_at is null)
    or (status in ('EDITING', 'SIGNING') and requested_at is not null and completed_at is null)
    or (status in ('COMPLETED', 'ABORTED', 'FAILED') and requested_at is not null and completed_at is not null)
    or (status = 'REQUEST_READY' and requested_at is null and completed_at is null)
  )
);

create unique index signatures_one_active_attempt_per_contract_idx
  on public.signatures (contract_id)
  where status in ('REQUEST_READY', 'REQUESTING', 'EDITING', 'SIGNING');
create index signatures_contract_requested_idx
  on public.signatures (contract_id, requested_at desc, id desc);

alter table public.signatures enable row level security;
revoke all on table public.signatures from anon, authenticated;
grant select, insert, update, delete on table public.signatures to service_role;

create or replace function public.signature_json(p_signature_id uuid)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'signature', jsonb_build_object(
      'id', signature.id,
      'contract_id', signature.contract_id,
      'status', signature.status,
      'modusign_status', signature.modusign_status,
      'modusign_draft_id', signature.modusign_draft_id,
      'modusign_document_id', signature.modusign_document_id,
      'last_event_id', signature.last_event_id,
      'requested_at', signature.requested_at,
      'completed_at', signature.completed_at
    ),
    'agreement_id', signature.agreement_id,
    'agreement_version', signature.agreement_version,
    'idempotency_key', signature.idempotency_key
  )
  from public.signatures signature
  where signature.id = p_signature_id;
$$;

create or replace function public.prepare_embedded_signature_draft(
  p_owner_id uuid,
  p_signature_id uuid,
  p_contract_id uuid,
  p_agreement_id uuid,
  p_agreement_version integer,
  p_idempotency_key uuid,
  p_requested_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
begin
  if not exists (
    select 1 from public.contracts
    where id = p_contract_id and owner_id = p_owner_id and status = 'READY_TO_SIGN'
    for update
  ) or not exists (
    select 1 from public.agreements
    where id = p_agreement_id
      and contract_id = p_contract_id
      and version = p_agreement_version
  ) or exists (
    select 1 from public.signatures
    where contract_id = p_contract_id
      and status in ('REQUEST_READY', 'REQUESTING', 'EDITING', 'SIGNING')
  ) then
    return null;
  end if;

  if exists (
    select 1 from public.signatures
    where contract_id = p_contract_id
      and status = 'FAILED'
      and idempotency_key = p_idempotency_key
  ) then
    return (
      select public.signature_json(id) from public.signatures
      where contract_id = p_contract_id
        and status = 'FAILED'
        and idempotency_key = p_idempotency_key
      order by requested_at desc, id desc
      limit 1
    );
  end if;

  insert into public.signatures (
    id, contract_id, agreement_id, agreement_version, idempotency_key, status, requested_at
  ) values (
    p_signature_id, p_contract_id, p_agreement_id, p_agreement_version, p_idempotency_key, 'REQUESTING', p_requested_at
  );
  return public.signature_json(p_signature_id);
end;
$$;

create or replace function public.complete_embedded_signature_draft(
  p_owner_id uuid,
  p_signature_id uuid,
  p_modusign_draft_id text
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_contract_id uuid;
begin
  select signature.contract_id into v_contract_id
  from public.signatures signature
  join public.contracts contract on contract.id = signature.contract_id
  where signature.id = p_signature_id
    and contract.owner_id = p_owner_id
    and signature.status = 'REQUESTING'
  for update of signature, contract;
  if not found then
    return null;
  end if;

  update public.signatures
    set modusign_draft_id = p_modusign_draft_id,
        modusign_status = 'DRAFT',
        status = 'EDITING'
    where id = p_signature_id;
  insert into public.audit_events (contract_id, event_type, actor_type, summary)
  values (v_contract_id, 'SIGNATURE_DRAFT_CREATED', 'OWNER', 'Embedded signature draft was created.');
  return public.signature_json(p_signature_id);
end;
$$;

create or replace function public.fail_embedded_signature_draft(
  p_owner_id uuid,
  p_signature_id uuid,
  p_completed_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_contract_id uuid;
begin
  select signature.contract_id into v_contract_id
  from public.signatures signature
  join public.contracts contract on contract.id = signature.contract_id
  where signature.id = p_signature_id
    and contract.owner_id = p_owner_id
    and signature.status = 'REQUESTING'
  for update of signature;
  if not found then
    return null;
  end if;
  update public.signatures
    set status = 'FAILED', completed_at = p_completed_at
    where id = p_signature_id;
  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (v_contract_id, 'SIGNATURE_FAILED', 'SYSTEM', 'Signature request creation failed.', p_completed_at);
  return public.signature_json(p_signature_id);
end;
$$;

create or replace function public.get_latest_owned_signature(
  p_owner_id uuid,
  p_contract_id uuid
)
returns jsonb
language sql
stable
set search_path = public
as $$
  select public.signature_json(signature.id)
  from public.signatures signature
  join public.contracts contract on contract.id = signature.contract_id
  where signature.contract_id = p_contract_id and contract.owner_id = p_owner_id
  order by signature.requested_at desc, signature.id desc
  limit 1;
$$;

revoke all on function public.signature_json(uuid) from public;
grant execute on function public.signature_json(uuid) to service_role;
revoke all on function public.prepare_embedded_signature_draft(uuid, uuid, uuid, uuid, integer, uuid, timestamptz) from public;
grant execute on function public.prepare_embedded_signature_draft(uuid, uuid, uuid, uuid, integer, uuid, timestamptz) to service_role;
revoke all on function public.complete_embedded_signature_draft(uuid, uuid, text) from public;
grant execute on function public.complete_embedded_signature_draft(uuid, uuid, text) to service_role;
revoke all on function public.fail_embedded_signature_draft(uuid, uuid, timestamptz) from public;
grant execute on function public.fail_embedded_signature_draft(uuid, uuid, timestamptz) to service_role;
revoke all on function public.get_latest_owned_signature(uuid, uuid) from public;
grant execute on function public.get_latest_owned_signature(uuid, uuid) to service_role;
