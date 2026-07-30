create table public.renewal_decisions (
    contract_id uuid primary key references public.contracts(id) on delete cascade,
    decision text not null check (
        decision in ('RENEW_SAME_TERMS', 'RENEW_WITH_CHANGES', 'TERMINATE')
    ),
    decided_at timestamptz not null,
    revisit_review_item_ids uuid[] not null default '{}'::uuid[],
    check (
        decision = 'RENEW_WITH_CHANGES'
        or cardinality(revisit_review_item_ids) = 0
    )
);

alter table public.renewal_decisions enable row level security;

create policy renewal_decisions_owner_select
    on public.renewal_decisions
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.contracts contract
            where contract.id = renewal_decisions.contract_id
              and contract.owner_id = auth.uid()
        )
    );

revoke all on public.renewal_decisions from anon, authenticated;
grant all on public.renewal_decisions to service_role;

create or replace function public.save_renewal_decision_with_audit(
    p_owner_id uuid,
    p_contract_id uuid,
    p_decision text,
    p_today date,
    p_decided_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract public.contracts%rowtype;
    v_existing public.renewal_decisions%rowtype;
    v_saved public.renewal_decisions%rowtype;
    v_revisit_review_item_ids uuid[] := '{}'::uuid[];
    v_expiry_d_day integer;
    v_termination_notice_d_day integer;
    v_auto_renewal_d_day integer;
begin
    if p_decision is null
       or p_decision not in ('RENEW_SAME_TERMS', 'RENEW_WITH_CHANGES', 'TERMINATE')
       or p_today is null
       or p_decided_at is null then
        raise exception 'Invalid renewal decision parameters' using errcode = '22023';
    end if;

    select contract.*
    into v_contract
    from public.contracts contract
    where contract.id = p_contract_id
      and contract.owner_id = p_owner_id
    for update;

    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND', 'decision', null);
    end if;

    v_expiry_d_day := case
        when v_contract.end_date is not null
        then v_contract.end_date - p_today
        else null
    end;
    v_termination_notice_d_day := case
        when v_contract.termination_notice_date is not null
        then v_contract.termination_notice_date - p_today
        else null
    end;
    v_auto_renewal_d_day := case
        when v_contract.renewal_type = 'AUTO' and v_contract.end_date is not null
        then v_contract.end_date - p_today
        else null
    end;

    if not (
        v_expiry_d_day between 0 and 30
        or v_termination_notice_d_day between 0 and 14
        or v_auto_renewal_d_day between 0 and 7
    ) then
        return jsonb_build_object(
            'outcome', 'OUTSIDE_REVIEW_WINDOW',
            'decision', null
        );
    end if;

    select renewal_decision.*
    into v_existing
    from public.renewal_decisions renewal_decision
    where renewal_decision.contract_id = p_contract_id;

    if found and v_existing.decision = p_decision then
        return jsonb_build_object(
            'outcome', 'UNCHANGED',
            'decision', to_jsonb(v_existing)
        );
    end if;

    if p_decision = 'RENEW_WITH_CHANGES' then
        select coalesce(
            array_agg(distinct item.id order by item.id),
            '{}'::uuid[]
        )
        into v_revisit_review_item_ids
        from public.review_items item
        where item.contract_id = p_contract_id
          and (
              item.status = 'KEPT_ORIGINAL'
              or exists (
                  select 1
                  from public.adjustment_responses response
                  join public.adjustment_requests adjustment
                    on adjustment.id = response.adjustment_request_id
                  where adjustment.contract_id = p_contract_id
                    and response.review_item_id = item.id
                    and response.decision = 'REJECT'
              )
          );
    end if;

    insert into public.renewal_decisions (
        contract_id,
        decision,
        decided_at,
        revisit_review_item_ids
    )
    values (
        p_contract_id,
        p_decision,
        p_decided_at,
        v_revisit_review_item_ids
    )
    on conflict (contract_id) do update
    set decision = excluded.decision,
        decided_at = excluded.decided_at,
        revisit_review_item_ids = excluded.revisit_review_item_ids
    returning * into v_saved;

    insert into public.audit_events (
        contract_id,
        event_type,
        actor_type,
        summary,
        created_at
    )
    values (
        p_contract_id,
        'RENEWAL_DECISION_SAVED',
        'OWNER',
        '만료·재계약 의사를 저장했습니다.',
        p_decided_at
    );

    return jsonb_build_object(
        'outcome', 'SAVED',
        'decision', to_jsonb(v_saved)
    );
end;
$$;

revoke all on function public.save_renewal_decision_with_audit(
    uuid,
    uuid,
    text,
    date,
    timestamptz
) from public, anon, authenticated;

grant execute on function public.save_renewal_decision_with_audit(
    uuid,
    uuid,
    text,
    date,
    timestamptz
) to service_role;
