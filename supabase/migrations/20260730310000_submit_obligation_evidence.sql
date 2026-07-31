-- B 7.4: validate an obligation-scoped token and submit URL evidence atomically.
-- The server stores the URL string only and never fetches the external resource.

create or replace function public.submit_obligation_evidence_with_audit(
    p_public_token_id uuid,
    p_token_hash text,
    p_obligation_id uuid,
    p_evidence_url text,
    p_submitted_at timestamptz
)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract_id uuid;
    v_expires_at timestamptz;
    v_status text;
begin
    select token.expires_at
    into v_expires_at
    from public.public_tokens token
    where token.id = p_public_token_id
      and token.token_hash = p_token_hash
      and token.scope = 'OBLIGATION_EVIDENCE'
      and token.resource_id = p_obligation_id
      and token.revoked_at is null
    for update;

    if not found then
        return 'NOT_FOUND';
    end if;
    if v_expires_at <= p_submitted_at then
        return 'EXPIRED';
    end if;
    if p_evidence_url is null
       or btrim(p_evidence_url) = ''
       or char_length(p_evidence_url) > 2048
       or p_evidence_url !~* '^https?://' then
        raise exception 'invalid evidence URL'
            using errcode = '22023';
    end if;

    select obligation.contract_id, obligation.status
    into v_contract_id, v_status
    from public.obligations obligation
    where obligation.id = p_obligation_id
    for update;

    if not found then
        return 'NOT_FOUND';
    end if;
    if v_status <> 'PENDING' then
        return 'INVALID_STATUS_TRANSITION';
    end if;

    update public.obligations
    set
        evidence_url = p_evidence_url,
        status = 'SUBMITTED',
        submitted_at = p_submitted_at,
        reviewed_at = null,
        payment_condition_met = false,
        updated_at = p_submitted_at
    where id = p_obligation_id;

    insert into public.audit_events (
        contract_id,
        event_type,
        actor_type,
        summary,
        created_at
    )
    values (
        v_contract_id,
        'EVIDENCE_SUBMITTED',
        'AGENCY',
        '대행사가 산출물 증빙 URL을 제출했습니다.',
        p_submitted_at
    );

    return 'SUBMITTED';
end;
$$;

revoke all on function public.submit_obligation_evidence_with_audit(
    uuid,
    text,
    uuid,
    text,
    timestamptz
) from public;

grant execute on function public.submit_obligation_evidence_with_audit(
    uuid,
    text,
    uuid,
    text,
    timestamptz
) to service_role;
