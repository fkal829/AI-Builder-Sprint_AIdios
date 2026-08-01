-- Owner-requested hard deletion for contracts that have never crossed an
-- external delivery/signature boundary. The RPC is the only write path so the
-- guard and dependent-row deletion remain one transaction.

create table public.contract_deletion_records (
  contract_id uuid primary key,
  owner_id uuid not null,
  previous_status text not null check (previous_status in (
    'DRAFT', 'ANALYZING', 'REVIEW_REQUIRED', 'NEGOTIATING'
  )),
  storage_paths text[] not null default '{}',
  deleted_at timestamptz not null,
  storage_cleaned_at timestamptz,
  check (storage_cleaned_at is null or storage_cleaned_at >= deleted_at)
);

alter table public.contract_deletion_records enable row level security;
revoke all on table public.contract_deletion_records from anon, authenticated;
grant select, insert, update on table public.contract_deletion_records to service_role;

create function public.delete_discardable_contract(
  p_owner_id uuid,
  p_contract_id uuid,
  p_deleted_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_status text;
  v_storage_paths text[];
  v_adjustment_request_ids uuid[];
  v_obligation_ids uuid[];
begin
  select contract.status
  into v_status
  from public.contracts contract
  where contract.id = p_contract_id
    and contract.owner_id = p_owner_id
  for update;

  if not found then
    return jsonb_build_object('outcome', 'NOT_FOUND', 'storage_paths', '[]'::jsonb);
  end if;

  -- Lock every delivery/signature boundary row before checking it. Concurrent
  -- send/signature creation must either finish first and protect the contract,
  -- or observe that this transaction deleted its parent contract.
  perform 1
  from public.adjustment_requests request
  where request.contract_id = p_contract_id
  order by request.id
  for update;

  perform 1
  from public.signatures signature
  where signature.contract_id = p_contract_id
  order by signature.id
  for update;

  if v_status not in ('DRAFT', 'ANALYZING', 'REVIEW_REQUIRED', 'NEGOTIATING')
     or exists (
       select 1
       from public.adjustment_requests request
       where request.contract_id = p_contract_id
         and request.status <> 'DRAFT'
     )
     or exists (
       select 1 from public.signatures signature
       where signature.contract_id = p_contract_id
     )
     or exists (
       select 1 from public.agreements agreement
       where agreement.contract_id = p_contract_id
     )
     or exists (
       select 1 from public.revised_contract_reviews review
       where review.contract_id = p_contract_id
     )
     or exists (
       select 1 from public.performance_reports report
       where report.contract_id = p_contract_id
     )
  then
    return jsonb_build_object('outcome', 'PROTECTED', 'storage_paths', '[]'::jsonb);
  end if;

  select coalesce(array_agg(document.storage_path order by document.id), '{}')
  into v_storage_paths
  from public.documents document
  where document.contract_id = p_contract_id;

  select coalesce(array_agg(request.id order by request.id), '{}')
  into v_adjustment_request_ids
  from public.adjustment_requests request
  where request.contract_id = p_contract_id;

  select coalesce(array_agg(obligation.id order by obligation.id), '{}')
  into v_obligation_ids
  from public.obligations obligation
  where obligation.contract_id = p_contract_id;

  -- Tokens have a polymorphic resource_id rather than a foreign key.
  delete from public.public_tokens token
  where token.resource_id = any(v_adjustment_request_ids)
     or token.resource_id = any(v_obligation_ids);

  delete from public.idempotency_records record
  where record.owner_id = p_owner_id
    and (
      record.resource_id = p_contract_id
      or record.resource_id = any(v_adjustment_request_ids)
      or record.resource_id = any(v_obligation_ids)
    );

  delete from public.adjustment_request_items item
  where item.adjustment_request_id = any(v_adjustment_request_ids);
  delete from public.adjustment_requests request
  where request.contract_id = p_contract_id;

  -- Remove document-restricting evidence rows before deleting documents.
  delete from public.obligations obligation where obligation.contract_id = p_contract_id;
  delete from public.review_items item where item.contract_id = p_contract_id;
  delete from public.extracted_terms term where term.contract_id = p_contract_id;
  delete from public.analysis_tasks task where task.contract_id = p_contract_id;

  delete from public.understood_terms term where term.contract_id = p_contract_id;
  delete from public.renewal_decisions decision where decision.contract_id = p_contract_id;
  delete from public.audit_events event where event.contract_id = p_contract_id;
  delete from public.documents document where document.contract_id = p_contract_id;

  insert into public.contract_deletion_records (
    contract_id,
    owner_id,
    previous_status,
    storage_paths,
    deleted_at
  ) values (
    p_contract_id,
    p_owner_id,
    v_status,
    v_storage_paths,
    p_deleted_at
  );

  delete from public.contracts contract
  where contract.id = p_contract_id and contract.owner_id = p_owner_id;

  if not found then
    raise exception 'contract disappeared during guarded deletion' using errcode = '40001';
  end if;

  return jsonb_build_object(
    'outcome', 'DELETED',
    'storage_paths', to_jsonb(v_storage_paths)
  );
end;
$$;

create function public.mark_contract_storage_cleaned(
  p_owner_id uuid,
  p_contract_id uuid,
  p_cleaned_at timestamptz
)
returns boolean
language plpgsql
set search_path = public
as $$
begin
  update public.contract_deletion_records record
  set storage_cleaned_at = coalesce(record.storage_cleaned_at, p_cleaned_at)
  where record.contract_id = p_contract_id
    and record.owner_id = p_owner_id;
  return found;
end;
$$;

revoke all on function public.delete_discardable_contract(uuid, uuid, timestamptz) from public;
grant execute on function public.delete_discardable_contract(uuid, uuid, timestamptz)
  to service_role;
revoke all on function public.mark_contract_storage_cleaned(uuid, uuid, timestamptz)
  from public;
grant execute on function public.mark_contract_storage_cleaned(uuid, uuid, timestamptz)
  to service_role;
