-- B 7.3: create an obligation evidence link and its audit event atomically.
-- Raw public tokens and public URLs are never persisted.

create or replace function public.create_obligation_evidence_link_with_audit(
    p_owner_id uuid,
    p_contract_id uuid,
    p_obligation_id uuid,
    p_public_token_id uuid,
    p_token_hash text,
    p_token_scope text,
    p_token_resource_id uuid,
    p_token_expires_at timestamptz,
    p_token_created_at timestamptz
)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_status text;
    v_contract_status text;
begin
    select obligation.status, contract.status
    into v_status, v_contract_status
    from public.obligations obligation
    join public.contracts contract on contract.id = obligation.contract_id
    where obligation.id = p_obligation_id
      and obligation.contract_id = p_contract_id
      and contract.owner_id = p_owner_id
    for update of obligation, contract;

    if not found then
        return 'NOT_FOUND';
    end if;
    if v_status <> 'PENDING'
       or v_contract_status not in ('SIGNED', 'IN_PROGRESS') then
        return 'INVALID_STATUS_TRANSITION';
    end if;
    if p_token_scope <> 'OBLIGATION_EVIDENCE'
       or p_token_resource_id <> p_obligation_id
       or p_token_expires_at <= p_token_created_at then
        raise exception 'invalid obligation evidence token'
            using errcode = '22023';
    end if;

    insert into public.public_tokens (
        id,
        token_hash,
        scope,
        resource_id,
        expires_at,
        revoked_at,
        created_at
    )
    values (
        p_public_token_id,
        p_token_hash,
        p_token_scope,
        p_token_resource_id,
        p_token_expires_at,
        null,
        p_token_created_at
    );

    insert into public.audit_events (
        contract_id,
        event_type,
        actor_type,
        summary,
        created_at
    )
    values (
        p_contract_id,
        'EVIDENCE_LINK_CREATED',
        'OWNER',
        '산출물 증빙 제출 링크를 생성했습니다.',
        p_token_created_at
    );

    return 'CREATED';
end;
$$;

revoke all on function public.create_obligation_evidence_link_with_audit(
    uuid,
    uuid,
    uuid,
    uuid,
    text,
    text,
    uuid,
    timestamptz,
    timestamptz
) from public;

grant execute on function public.create_obligation_evidence_link_with_audit(
    uuid,
    uuid,
    uuid,
    uuid,
    text,
    text,
    uuid,
    timestamptz,
    timestamptz
) to service_role;
