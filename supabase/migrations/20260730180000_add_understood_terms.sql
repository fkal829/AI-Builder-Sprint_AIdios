create table if not exists public.understood_terms (
    contract_id uuid primary key references public.contracts(id) on delete cascade,
    duration_text text not null check (char_length(btrim(duration_text)) >= 1),
    monthly_amount bigint check (monthly_amount >= 0),
    total_amount bigint check (total_amount >= 0),
    refund_text text not null check (char_length(btrim(refund_text)) >= 1),
    termination_text text not null check (char_length(btrim(termination_text)) >= 1),
    source_type text not null default 'USER_MEMORY'
        check (source_type = 'USER_MEMORY')
);

alter table public.understood_terms enable row level security;

create policy understood_terms_owner_select
    on public.understood_terms
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts
            where contracts.id = understood_terms.contract_id
              and contracts.owner_id = auth.uid()
        )
    );

revoke all on public.understood_terms from anon, authenticated;
grant all on public.understood_terms to service_role;

create or replace function public.save_understood_term_with_audit(
    p_owner_id uuid,
    p_contract_id uuid,
    p_duration_text text,
    p_monthly_amount bigint,
    p_total_amount bigint,
    p_refund_text text,
    p_termination_text text
)
returns public.understood_terms
language plpgsql
security definer
set search_path = ''
as $$
declare
    existing_term public.understood_terms;
    saved_term public.understood_terms;
begin
    perform 1
    from public.contracts
    where id = p_contract_id
      and owner_id = p_owner_id
    for update;

    if not found then
        return null;
    end if;

    select *
    into existing_term
    from public.understood_terms
    where contract_id = p_contract_id;

    if found
       and existing_term.duration_text is not distinct from p_duration_text
       and existing_term.monthly_amount is not distinct from p_monthly_amount
       and existing_term.total_amount is not distinct from p_total_amount
       and existing_term.refund_text is not distinct from p_refund_text
       and existing_term.termination_text is not distinct from p_termination_text
       and existing_term.source_type = 'USER_MEMORY' then
        return existing_term;
    end if;

    insert into public.understood_terms (
        contract_id,
        duration_text,
        monthly_amount,
        total_amount,
        refund_text,
        termination_text,
        source_type
    )
    values (
        p_contract_id,
        p_duration_text,
        p_monthly_amount,
        p_total_amount,
        p_refund_text,
        p_termination_text,
        'USER_MEMORY'
    )
    on conflict (contract_id) do update
    set duration_text = excluded.duration_text,
        monthly_amount = excluded.monthly_amount,
        total_amount = excluded.total_amount,
        refund_text = excluded.refund_text,
        termination_text = excluded.termination_text,
        source_type = 'USER_MEMORY'
    returning * into saved_term;

    insert into public.audit_events (
        contract_id,
        event_type,
        actor_type,
        summary
    )
    values (
        p_contract_id,
        'UNDERSTOOD_TERMS_SAVED',
        'OWNER',
        '사용자가 이해한 계약 조건이 저장되었습니다.'
    );

    return saved_term;
end;
$$;

revoke all on function public.save_understood_term_with_audit(
    uuid,
    uuid,
    text,
    bigint,
    bigint,
    text,
    text
) from public, anon, authenticated;

grant execute on function public.save_understood_term_with_audit(
    uuid,
    uuid,
    text,
    bigint,
    bigint,
    text,
    text
) to service_role;
