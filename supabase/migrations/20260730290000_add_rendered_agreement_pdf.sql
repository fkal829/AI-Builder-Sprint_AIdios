-- C-6 extension: preserve the source contract and store one immutable rendered
-- amendment-agreement PDF. The file itself lives in private Storage; this table
-- only contains non-sensitive integrity and location metadata.

create table public.agreement_files (
  agreement_id uuid primary key references public.agreements(id) on delete cascade,
  storage_path text not null unique
    check (storage_path <> '' and storage_path !~ '(^|/)\.\.?(/|$)'),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  content_type text not null check (content_type = 'application/pdf'),
  size_bytes bigint not null check (size_bytes between 1 and 20971520),
  page_count integer not null check (page_count between 1 and 100),
  created_at timestamptz not null default now()
);

alter table public.agreement_files enable row level security;
revoke all on table public.agreement_files from anon, authenticated;
grant select, insert, update, delete on table public.agreement_files to service_role;

create or replace function public.create_rendered_agreement_with_audit(
  p_owner_id uuid,
  p_contract_id uuid,
  p_agreement_id uuid,
  p_adjustment_request_id uuid,
  p_agreement jsonb,
  p_pdf_storage_path text,
  p_pdf_sha256 text,
  p_pdf_size_bytes bigint,
  p_pdf_page_count integer,
  p_created_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_version integer;
  v_record public.agreements%rowtype;
  v_file public.agreement_files%rowtype;
begin
  if p_pdf_storage_path is null
    or p_pdf_storage_path = ''
    or p_pdf_sha256 is null
    or p_pdf_sha256 !~ '^[0-9a-f]{64}$'
    or p_pdf_size_bytes not between 1 and 20971520
    or p_pdf_page_count not between 1 and 100
    or not exists (
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

  insert into public.agreement_files (
    agreement_id, storage_path, content_sha256, content_type, size_bytes, page_count, created_at
  ) values (
    v_record.id, p_pdf_storage_path, p_pdf_sha256, 'application/pdf',
    p_pdf_size_bytes, p_pdf_page_count, p_created_at
  ) returning * into v_file;

  insert into public.audit_events (contract_id, event_type, actor_type, summary, created_at)
  values (p_contract_id, 'AGREEMENT_CREATED', 'OWNER', '변경·확인 합의서와 PDF를 생성했습니다.', p_created_at);

  return jsonb_build_object(
    'agreement', v_record.agreement,
    'adjustment_request_id', v_record.adjustment_request_id,
    'pdf_storage_path', v_file.storage_path,
    'pdf_sha256', v_file.content_sha256,
    'pdf_size_bytes', v_file.size_bytes,
    'pdf_page_count', v_file.page_count,
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
    'pdf_storage_path', file.storage_path,
    'pdf_sha256', file.content_sha256,
    'pdf_size_bytes', file.size_bytes,
    'pdf_page_count', file.page_count,
    'created_at', agreement.created_at
  )
  from public.agreements agreement
  join public.agreement_files file on file.agreement_id = agreement.id
  join public.contracts contract on contract.id = agreement.contract_id
  where agreement.contract_id = p_contract_id and contract.owner_id = p_owner_id
  order by agreement.version desc
  limit 1;
$$;

revoke all on function public.create_rendered_agreement_with_audit(
  uuid, uuid, uuid, uuid, jsonb, text, text, bigint, integer, timestamptz
) from public;
grant execute on function public.create_rendered_agreement_with_audit(
  uuid, uuid, uuid, uuid, jsonb, text, text, bigint, integer, timestamptz
) to service_role;
revoke all on function public.get_owned_agreement(uuid, uuid) from public;
grant execute on function public.get_owned_agreement(uuid, uuid) to service_role;
