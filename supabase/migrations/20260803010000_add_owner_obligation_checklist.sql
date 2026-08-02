-- Let an authenticated owner explicitly check the representative deliverable
-- without first asking the agency to use a public evidence link. The legacy
-- PENDING -> SUBMITTED flow remains valid for existing clients and data.

do $$
declare
    v_constraint_name text;
begin
    select constraint_record.conname
    into v_constraint_name
    from pg_catalog.pg_constraint constraint_record
    where constraint_record.conrelid = 'public.obligations'::regclass
      and constraint_record.contype = 'c'
      and pg_catalog.pg_get_constraintdef(constraint_record.oid) like '%payment_condition_met%'
      and pg_catalog.pg_get_constraintdef(constraint_record.oid) like '%reviewed_at%'
    limit 1;

    if v_constraint_name is not null then
        execute format(
            'alter table public.obligations drop constraint %I',
            v_constraint_name
        );
    end if;
end;
$$;

alter table public.obligations
add constraint obligations_status_fields_check
check (
    (
        status = 'PENDING'
        and evidence_url is null
        and submitted_at is null
        and reviewed_at is null
        and payment_condition_met = false
    )
    or (
        status = 'SUBMITTED'
        and evidence_url is not null
        and submitted_at is not null
        and reviewed_at is null
        and payment_condition_met = false
    )
    or (
        status = 'APPROVED'
        and reviewed_at is not null
        and ((evidence_url is null) = (submitted_at is null))
        and payment_condition_met = true
    )
    or (
        status = 'DISPUTED'
        and reviewed_at is not null
        and ((evidence_url is null) = (submitted_at is null))
        and payment_condition_met = false
    )
);

create or replace function public.check_obligation_with_audit(
    p_owner_id uuid,
    p_contract_id uuid,
    p_obligation_id uuid,
    p_decision text,
    p_evidence_url text,
    p_reviewed_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_obligation public.obligations%rowtype;
    v_contract_status text;
    v_event_type text;
    v_summary text;
begin
    if p_decision is null
       or p_decision not in ('APPROVED', 'DISPUTED')
       or p_reviewed_at is null
       or (
           p_evidence_url is not null
           and (
               char_length(p_evidence_url) > 2048
               or p_evidence_url !~ '^https?://'
           )
       ) then
        raise exception 'invalid owner obligation check parameters'
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
    for update of obligation, contract;

    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND', 'obligation', null);
    end if;

    select contract.status
    into v_contract_status
    from public.contracts contract
    where contract.id = p_contract_id;

    if v_obligation.status not in ('PENDING', 'SUBMITTED')
       or (
           v_obligation.status = 'PENDING'
           and v_contract_status not in ('SIGNED', 'IN_PROGRESS')
       )
       or (
           v_obligation.status = 'SUBMITTED'
           and p_evidence_url is not null
       ) then
        return jsonb_build_object(
            'outcome', 'INVALID_STATUS_TRANSITION',
            'obligation', to_jsonb(v_obligation)
        );
    end if;

    update public.obligations
    set
        status = p_decision,
        evidence_url = case
            when v_obligation.status = 'PENDING' then p_evidence_url
            else evidence_url
        end,
        submitted_at = case
            when v_obligation.status = 'PENDING' and p_evidence_url is not null
                then p_reviewed_at
            else submitted_at
        end,
        reviewed_at = p_reviewed_at,
        payment_condition_met = p_decision = 'APPROVED',
        updated_at = p_reviewed_at
    where id = p_obligation_id
    returning * into v_obligation;

    if p_decision = 'APPROVED' then
        v_event_type := 'EVIDENCE_APPROVED';
        v_summary := '소유자가 산출물 완료를 확인했습니다.';
    else
        v_event_type := 'EVIDENCE_DISPUTED';
        v_summary := '소유자가 산출물에 문제가 있음을 기록했습니다.';
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

revoke all on function public.check_obligation_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    timestamptz
) from public, anon, authenticated;

grant execute on function public.check_obligation_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    timestamptz
) to service_role;
