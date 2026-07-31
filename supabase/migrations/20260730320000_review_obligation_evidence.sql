-- B 7.5: review submitted obligation evidence and record the owner decision atomically.

create or replace function public.review_obligation_evidence_with_audit(
    p_owner_id uuid,
    p_contract_id uuid,
    p_obligation_id uuid,
    p_decision text,
    p_reviewed_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_obligation public.obligations%rowtype;
    v_event_type text;
    v_summary text;
begin
    if p_decision is null
       or p_decision not in ('APPROVED', 'DISPUTED')
       or p_reviewed_at is null then
        raise exception 'invalid evidence review parameters'
            using errcode = '22023';
    end if;

    select obligation.*
    into v_obligation
    from public.obligations obligation
    join public.contracts contract
      on contract.id = obligation.contract_id
    where contract.id = p_contract_id
      and contract.owner_id = p_owner_id
      and obligation.id = p_obligation_id
    for update of obligation;

    if not found then
        return jsonb_build_object(
            'outcome', 'NOT_FOUND',
            'obligation', null
        );
    end if;
    if v_obligation.status <> 'SUBMITTED' then
        return jsonb_build_object(
            'outcome', 'INVALID_STATUS_TRANSITION',
            'obligation', to_jsonb(v_obligation)
        );
    end if;

    update public.obligations
    set
        status = p_decision,
        reviewed_at = p_reviewed_at,
        payment_condition_met = p_decision = 'APPROVED',
        updated_at = p_reviewed_at
    where id = p_obligation_id
    returning * into v_obligation;

    if p_decision = 'APPROVED' then
        v_event_type := 'EVIDENCE_APPROVED';
        v_summary := '소유자가 산출물 증빙을 승인했습니다.';
    else
        v_event_type := 'EVIDENCE_DISPUTED';
        v_summary := '소유자가 산출물 증빙에 이의를 제기했습니다.';
    end if;

    insert into public.audit_events (
        contract_id,
        event_type,
        actor_type,
        summary,
        created_at
    )
    values (
        p_contract_id,
        v_event_type,
        'OWNER',
        v_summary,
        p_reviewed_at
    );

    return jsonb_build_object(
        'outcome', 'REVIEWED',
        'obligation', to_jsonb(v_obligation)
    );
end;
$$;

revoke all on function public.review_obligation_evidence_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    timestamptz
) from public, anon, authenticated;

grant execute on function public.review_obligation_evidence_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    timestamptz
) to service_role;
