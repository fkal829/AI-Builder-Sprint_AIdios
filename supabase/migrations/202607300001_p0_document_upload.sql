create extension if not exists pgcrypto;

create table if not exists public.contracts (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete restrict,
    title text not null check (char_length(btrim(title)) between 1 and 120),
    counterparty_name text not null
        check (char_length(btrim(counterparty_name)) between 1 and 120),
    status text not null default 'DRAFT' check (
        status in (
            'DRAFT',
            'ANALYZING',
            'REVIEW_REQUIRED',
            'NEGOTIATING',
            'READY_TO_SIGN',
            'SIGNING',
            'SIGNED',
            'IN_PROGRESS',
            'COMPLETED',
            'RENEWAL_DUE'
        )
    ),
    signed_date date,
    start_date date,
    end_date date,
    termination_notice_date date,
    renewal_type text check (renewal_type in ('AUTO', 'MANUAL', 'NONE')),
    total_amount bigint check (total_amount >= 0),
    modusign_document_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists contracts_owner_id_idx
    on public.contracts (owner_id, id);

create table if not exists public.documents (
    id uuid primary key,
    contract_id uuid not null references public.contracts(id) on delete cascade,
    type text not null check (type in ('CONTRACT', 'PROPOSAL', 'ESTIMATE', 'MESSAGE')),
    parse_status text not null check (
        parse_status in ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')
    ),
    storage_path text not null unique
        check (storage_path <> '' and storage_path !~ '(^|/)\.\.?(/|$)'),
    content_type text not null check (
        content_type in ('application/pdf', 'image/png', 'image/jpeg', 'text/plain')
    ),
    size_bytes bigint not null check (size_bytes between 1 and 20971520),
    page_count integer not null check (page_count between 1 and 100),
    created_at timestamptz not null default now()
);

create index if not exists documents_contract_created_idx
    on public.documents (contract_id, created_at desc, id);

create table if not exists public.audit_events (
    id uuid primary key default gen_random_uuid(),
    contract_id uuid not null references public.contracts(id) on delete cascade,
    event_type text not null check (
        event_type in (
            'CONTRACT_CREATED',
            'DOCUMENT_UPLOADED',
            'UNDERSTOOD_TERMS_SAVED',
            'ANALYSIS_STARTED',
            'ANALYSIS_RESTARTED',
            'ANALYSIS_COMPLETED',
            'ANALYSIS_FAILED',
            'REVIEW_ITEM_SELECTION_UPDATED',
            'ADJUSTMENT_DRAFT_CREATED',
            'ADJUSTMENT_SENT',
            'ADJUSTMENT_OPENED',
            'ADJUSTMENT_RESPONDED',
            'ADJUSTMENT_CONFIRMED',
            'ADJUSTMENT_EXPIRED',
            'AGREEMENT_CREATED',
            'SIGNATURE_REQUESTED',
            'SIGNATURE_STARTED',
            'SIGNATURE_COMPLETED',
            'SIGNATURE_ABORTED',
            'SIGNATURE_FAILED',
            'OBLIGATION_CREATED',
            'EVIDENCE_LINK_CREATED',
            'EVIDENCE_SUBMITTED',
            'EVIDENCE_APPROVED',
            'EVIDENCE_DISPUTED',
            'RENEWAL_DECISION_SAVED'
        )
    ),
    actor_type text not null check (actor_type in ('OWNER', 'AGENCY', 'SYSTEM')),
    summary text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists audit_events_contract_created_idx
    on public.audit_events (contract_id, created_at, id);

alter table public.contracts enable row level security;
alter table public.documents enable row level security;
alter table public.audit_events enable row level security;

create policy contracts_owner_select
    on public.contracts
    for select
    to authenticated
    using (owner_id = auth.uid());

create policy documents_owner_select
    on public.documents
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts
            where contracts.id = documents.contract_id
              and contracts.owner_id = auth.uid()
        )
    );

create policy audit_events_owner_select
    on public.audit_events
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts
            where contracts.id = audit_events.contract_id
              and contracts.owner_id = auth.uid()
        )
    );

revoke all on public.contracts, public.documents, public.audit_events
    from anon, authenticated;
grant all on public.contracts, public.documents, public.audit_events
    to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'contracts',
    'contracts',
    false,
    20971520,
    array['application/pdf', 'image/png', 'image/jpeg', 'text/plain']
)
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.create_document_with_audit(
    p_owner_id uuid,
    p_document_id uuid,
    p_contract_id uuid,
    p_document_type text,
    p_parse_status text,
    p_storage_path text,
    p_content_type text,
    p_size_bytes bigint,
    p_page_count integer,
    p_created_at timestamptz
)
returns public.documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    saved_document public.documents;
begin
    if not exists (
        select 1
        from public.contracts
        where id = p_contract_id
          and owner_id = p_owner_id
    ) then
        return null;
    end if;

    insert into public.documents (
        id,
        contract_id,
        type,
        parse_status,
        storage_path,
        content_type,
        size_bytes,
        page_count,
        created_at
    )
    values (
        p_document_id,
        p_contract_id,
        p_document_type,
        p_parse_status,
        p_storage_path,
        p_content_type,
        p_size_bytes,
        p_page_count,
        p_created_at
    )
    returning * into saved_document;

    insert into public.audit_events (
        contract_id,
        event_type,
        actor_type,
        summary,
        created_at
    )
    values (
        p_contract_id,
        'DOCUMENT_UPLOADED',
        'OWNER',
        '계약 문서가 업로드되었습니다.',
        p_created_at
    );

    return saved_document;
end;
$$;

revoke all on function public.create_document_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    text,
    text,
    bigint,
    integer,
    timestamptz
) from public, anon, authenticated;

grant execute on function public.create_document_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    text,
    text,
    bigint,
    integer,
    timestamptz
) to service_role;
