-- Replace the generated amendment-agreement path with an owner-confirmed
-- revised-contract review. Existing agreement rows remain readable for history.

alter table public.documents drop constraint if exists documents_type_check;
alter table public.documents add constraint documents_type_check
  check (type in ('CONTRACT', 'REVISED_CONTRACT', 'PROPOSAL', 'ESTIMATE', 'MESSAGE'));

alter table public.audit_events drop constraint if exists audit_events_event_type_check;
alter table public.audit_events add constraint audit_events_event_type_check
  check (event_type in (
    'CONTRACT_CREATED', 'CONTRACT_STARTED', 'CONTRACT_COMPLETED', 'CONTRACT_RENEWAL_DUE',
    'DOCUMENT_UPLOADED', 'UNDERSTOOD_TERMS_SAVED',
    'ANALYSIS_STARTED', 'ANALYSIS_RESTARTED', 'ANALYSIS_COMPLETED', 'ANALYSIS_FAILED',
    'REVIEW_ITEM_SELECTION_UPDATED',
    'ADJUSTMENT_DRAFT_CREATED', 'ADJUSTMENT_SENT', 'ADJUSTMENT_OPENED',
    'ADJUSTMENT_RESPONDED', 'ADJUSTMENT_CONFIRMED', 'ADJUSTMENT_EXPIRED',
    'AGREEMENT_CREATED', 'REVISED_CONTRACT_REVIEW_CREATED', 'REVISED_CONTRACT_CONFIRMED',
    'SIGNATURE_DRAFT_CREATED', 'SIGNATURE_REQUESTED', 'SIGNATURE_STARTED',
    'SIGNATURE_COMPLETED', 'SIGNATURE_ABORTED', 'SIGNATURE_FAILED',
    'OBLIGATION_CREATED', 'EVIDENCE_LINK_CREATED', 'EVIDENCE_SUBMITTED',
    'EVIDENCE_APPROVED', 'EVIDENCE_DISPUTED', 'RENEWAL_DECISION_SAVED'
  ));

-- Preserve the previous implementation and wrap it so adjustment confirmation
-- no longer makes a contract signable before the revised PDF is reviewed.
alter function public.confirm_adjustment_with_audit(uuid, uuid, uuid, timestamptz, jsonb)
  rename to confirm_adjustment_with_audit_legacy;

create function public.confirm_adjustment_with_audit(
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
  v_result jsonb;
begin
  v_result := public.confirm_adjustment_with_audit_legacy(
    p_owner_id,
    p_contract_id,
    p_adjustment_request_id,
    p_confirmed_at,
    p_confirmed_items
  );
  if v_result is null then return null; end if;
  update public.contracts
  set status = 'NEGOTIATING', updated_at = p_confirmed_at
  where id = p_contract_id and owner_id = p_owner_id and status = 'READY_TO_SIGN';
  if not found then raise exception 'confirmed contract transition was not preserved'; end if;
  return v_result;
end;
$$;

revoke all on function public.confirm_adjustment_with_audit_legacy(
  uuid, uuid, uuid, timestamptz, jsonb
) from public, anon, authenticated;
grant execute on function public.confirm_adjustment_with_audit(
  uuid, uuid, uuid, timestamptz, jsonb
) to service_role;

create table public.revised_contract_reviews (
  id uuid primary key,
  contract_id uuid not null references public.contracts(id) on delete cascade,
  adjustment_request_id uuid not null references public.adjustment_requests(id) on delete restrict,
  document_id uuid not null unique references public.documents(id) on delete restrict,
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  status text not null check (status in ('REVIEW_REQUIRED', 'CONFIRMED')),
  items jsonb not null check (jsonb_typeof(items) = 'array' and jsonb_array_length(items) between 1 and 4),
  created_at timestamptz not null,
  confirmed_at timestamptz,
  check (
    (status = 'REVIEW_REQUIRED' and confirmed_at is null)
    or (status = 'CONFIRMED' and confirmed_at is not null)
  )
);

create index revised_contract_reviews_contract_created_idx
  on public.revised_contract_reviews (contract_id, created_at desc, id desc);
alter table public.revised_contract_reviews enable row level security;
revoke all on table public.revised_contract_reviews from anon, authenticated;
grant select, insert, update, delete on table public.revised_contract_reviews to service_role;

create function public.get_revised_contract_context(
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
    'contract_title', contract.title,
    'final_clauses', coalesce((
      select jsonb_agg(jsonb_build_object(
        'review_item_id', clause.review_item_id,
        'category', clause.category,
        'resolution', clause.resolution,
        'outcome', clause.outcome,
        'disposition', clause.disposition,
        'before_text', clause.before_text,
        'after_text', clause.after_text,
        'reason', clause.reason
      ) order by clause.review_item_id)
      from public.adjustment_final_clauses clause
      where clause.adjustment_request_id = request.id
    ), '[]'::jsonb)
  )
  from public.contracts contract
  join public.adjustment_requests request
    on request.id = p_adjustment_request_id
   and request.contract_id = contract.id
   and request.status = 'CONFIRMED'
  where contract.id = p_contract_id
    and contract.owner_id = p_owner_id
    and contract.status = 'NEGOTIATING';
$$;

create function public.create_revised_contract_review_with_audit(
  p_owner_id uuid,
  p_review jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_review public.revised_contract_reviews%rowtype;
begin
  if not exists (
    select 1 from public.contracts
    where id = (p_review->>'contract_id')::uuid
      and owner_id = p_owner_id
      and status = 'NEGOTIATING'
    for update
  ) or not exists (
    select 1 from public.adjustment_requests
    where id = (p_review->>'adjustment_request_id')::uuid
      and contract_id = (p_review->>'contract_id')::uuid
      and status = 'CONFIRMED'
  ) or not exists (
    select 1 from public.documents
    where id = (p_review->>'document_id')::uuid
      and contract_id = (p_review->>'contract_id')::uuid
      and type = 'REVISED_CONTRACT'
      and id = (
        select latest.id
        from public.documents latest
        where latest.contract_id = (p_review->>'contract_id')::uuid
          and latest.type = 'REVISED_CONTRACT'
        order by latest.created_at desc, latest.id desc
        limit 1
      )
  ) then return null;
  end if;

  insert into public.revised_contract_reviews (
    id, contract_id, adjustment_request_id, document_id, document_sha256,
    status, items, created_at, confirmed_at
  ) values (
    (p_review->>'id')::uuid,
    (p_review->>'contract_id')::uuid,
    (p_review->>'adjustment_request_id')::uuid,
    (p_review->>'document_id')::uuid,
    p_review->>'document_sha256',
    p_review->>'status',
    p_review->'items',
    (p_review->>'created_at')::timestamptz,
    null
  ) returning * into v_review;

  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (
    v_review.contract_id,
    'REVISED_CONTRACT_REVIEW_CREATED',
    'OWNER',
    '수정 계약서 대조를 생성했습니다.',
    v_review.created_at
  );
  return to_jsonb(v_review);
end;
$$;

create function public.get_latest_owned_revised_contract_review(
  p_owner_id uuid,
  p_contract_id uuid
)
returns jsonb
language sql
stable
set search_path = public
as $$
  select to_jsonb(review)
  from public.revised_contract_reviews review
  join public.contracts contract on contract.id = review.contract_id
  where review.contract_id = p_contract_id and contract.owner_id = p_owner_id
  order by review.created_at desc, review.id desc
  limit 1;
$$;

create function public.confirm_revised_contract_review_with_audit(
  p_owner_id uuid,
  p_contract_id uuid,
  p_review_id uuid,
  p_confirmed_review_item_ids uuid[],
  p_confirmed_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_review public.revised_contract_reviews%rowtype;
  v_expected_count integer;
  v_distinct_count integer;
begin
  if not exists (
    select 1 from public.contracts
    where id = p_contract_id and owner_id = p_owner_id and status = 'NEGOTIATING'
    for update
  ) then return null;
  end if;
  select * into v_review from public.revised_contract_reviews
  where id = p_review_id and contract_id = p_contract_id and status = 'REVIEW_REQUIRED'
  for update;
  if not found or p_review_id <> (
    select id from public.revised_contract_reviews
    where contract_id = p_contract_id order by created_at desc, id desc limit 1
  ) then return null;
  end if;
  select jsonb_array_length(v_review.items) into v_expected_count;
  select count(distinct item_id) into v_distinct_count
  from unnest(p_confirmed_review_item_ids) item_id;
  if cardinality(p_confirmed_review_item_ids) <> v_expected_count
    or v_distinct_count <> v_expected_count
    or exists (
      select 1
      from jsonb_array_elements(v_review.items) item
      where (item->>'review_item_id')::uuid <> all(p_confirmed_review_item_ids)
    ) then return null;
  end if;

  update public.revised_contract_reviews
  set status = 'CONFIRMED',
      items = (
        select jsonb_agg(jsonb_set(item, '{owner_confirmed}', 'true'::jsonb))
        from jsonb_array_elements(v_review.items) item
      ),
      confirmed_at = p_confirmed_at
  where id = p_review_id
  returning * into v_review;
  update public.contracts
  set status = 'READY_TO_SIGN', updated_at = p_confirmed_at
  where id = p_contract_id;
  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (
    p_contract_id,
    'REVISED_CONTRACT_CONFIRMED',
    'OWNER',
    '수정 계약서 대조 결과를 확인했습니다.',
    p_confirmed_at
  );
  return to_jsonb(v_review);
end;
$$;

alter table public.signatures alter column agreement_id drop not null;
alter table public.signatures alter column agreement_version drop not null;
alter table public.signatures
  add column revised_contract_review_id uuid references public.revised_contract_reviews(id) on delete restrict,
  add column document_id uuid references public.documents(id) on delete restrict,
  add column document_sha256 text check (document_sha256 ~ '^[0-9a-f]{64}$');
alter table public.signatures add constraint signatures_source_check check (
  (revised_contract_review_id is not null and document_id is not null and document_sha256 is not null
    and agreement_id is null and agreement_version is null)
  or
  (revised_contract_review_id is null and document_id is null and document_sha256 is null
    and agreement_id is not null and agreement_version is not null)
);

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
    'revised_contract_review_id', signature.revised_contract_review_id,
    'document_id', signature.document_id,
    'document_sha256', signature.document_sha256,
    'agreement_id', signature.agreement_id,
    'agreement_version', signature.agreement_version,
    'idempotency_key', signature.idempotency_key
  )
  from public.signatures signature
  where signature.id = p_signature_id;
$$;

create function public.prepare_embedded_signature_draft(
  p_owner_id uuid,
  p_signature_id uuid,
  p_contract_id uuid,
  p_revised_contract_review_id uuid,
  p_document_id uuid,
  p_document_sha256 text,
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
    select 1 from public.revised_contract_reviews
    where id = p_revised_contract_review_id
      and contract_id = p_contract_id
      and document_id = p_document_id
      and document_sha256 = p_document_sha256
      and status = 'CONFIRMED'
  ) or p_revised_contract_review_id <> (
    select id from public.revised_contract_reviews
    where contract_id = p_contract_id order by created_at desc, id desc limit 1
  ) or exists (
    select 1 from public.signatures
    where contract_id = p_contract_id
      and status in ('REQUEST_READY', 'REQUESTING', 'EDITING', 'SIGNING')
  ) then return null;
  end if;
  insert into public.signatures (
    id, contract_id, revised_contract_review_id, document_id, document_sha256,
    agreement_id, agreement_version, idempotency_key, status, requested_at
  ) values (
    p_signature_id, p_contract_id, p_revised_contract_review_id, p_document_id,
    p_document_sha256, null, null, p_idempotency_key, 'REQUESTING', p_requested_at
  );
  return public.signature_json(p_signature_id);
end;
$$;

revoke all on function public.get_revised_contract_context(uuid, uuid, uuid) from public;
grant execute on function public.get_revised_contract_context(uuid, uuid, uuid) to service_role;
revoke all on function public.create_revised_contract_review_with_audit(uuid, jsonb) from public;
grant execute on function public.create_revised_contract_review_with_audit(uuid, jsonb) to service_role;
revoke all on function public.get_latest_owned_revised_contract_review(uuid, uuid) from public;
grant execute on function public.get_latest_owned_revised_contract_review(uuid, uuid) to service_role;
revoke all on function public.confirm_revised_contract_review_with_audit(
  uuid, uuid, uuid, uuid[], timestamptz
) from public;
grant execute on function public.confirm_revised_contract_review_with_audit(
  uuid, uuid, uuid, uuid[], timestamptz
) to service_role;
revoke all on function public.prepare_embedded_signature_draft(
  uuid, uuid, uuid, uuid, uuid, text, uuid, integer, uuid, timestamptz
) from public;
grant execute on function public.prepare_embedded_signature_draft(
  uuid, uuid, uuid, uuid, uuid, text, uuid, integer, uuid, timestamptz
) to service_role;
