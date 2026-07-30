-- P0 4.6: atomically persist an owner review selection and its audit event.

create or replace function public.update_review_item_selection_with_audit(
    p_owner_id uuid,
    p_contract_id uuid,
    p_item_id uuid,
    p_user_choice text,
    p_target_status text,
    p_updated_at timestamptz
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
    v_item public.review_items%rowtype;
    v_expected_status text;
begin
    if p_user_choice is null
       or p_user_choice not in ('ACCEPT', 'COMPROMISE', 'REQUEST') then
        raise exception 'invalid review item choice' using errcode = '22023';
    end if;

    v_expected_status := case
        when p_user_choice = 'ACCEPT' then 'RESOLVED'
        else 'SELECTED'
    end;
    if p_target_status is null or p_target_status <> v_expected_status then
        raise exception 'review item choice and target status do not match'
            using errcode = '22023';
    end if;

    select item.*
    into v_item
    from public.review_items item
    join public.contracts contract on contract.id = item.contract_id
    where item.id = p_item_id
      and item.contract_id = p_contract_id
      and contract.owner_id = p_owner_id
    for update of item;

    if not found then
        return jsonb_build_object(
            'outcome', 'NOT_FOUND',
            'item', null
        );
    end if;

    if v_item.status not in ('UNREVIEWED', 'SELECTED') then
        return jsonb_build_object(
            'outcome', 'INVALID_STATUS_TRANSITION',
            'item', to_jsonb(v_item)
        );
    end if;

    if v_item.user_choice is not distinct from p_user_choice
       and v_item.status = p_target_status then
        return jsonb_build_object(
            'outcome', 'UNCHANGED',
            'item', to_jsonb(v_item)
        );
    end if;

    update public.review_items
    set user_choice = p_user_choice,
        status = p_target_status,
        updated_at = p_updated_at
    where id = p_item_id
    returning * into v_item;

    update public.analysis_tasks task
    set result = jsonb_set(
            task.result,
            '{review_items}',
            coalesce(
                (
                    select jsonb_agg(
                        case
                            when entry.item ->> 'id' = p_item_id::text then
                                jsonb_set(
                                    jsonb_set(
                                        entry.item,
                                        '{user_choice}',
                                        to_jsonb(p_user_choice),
                                        false
                                    ),
                                    '{status}',
                                    to_jsonb(p_target_status),
                                    false
                                )
                            else entry.item
                        end
                        order by entry.position
                    )
                    from jsonb_array_elements(
                        task.result -> 'review_items'
                    ) with ordinality as entry(item, position)
                ),
                '[]'::jsonb
            ),
            false
        ),
        updated_at = p_updated_at
    where task.id = v_item.analysis_task_id
      and task.status = 'COMPLETED'
      and task.result is not null;

    insert into public.audit_events (
        contract_id,
        event_type,
        actor_type,
        summary,
        created_at
    ) values (
        p_contract_id,
        'REVIEW_ITEM_SELECTION_UPDATED',
        'OWNER',
        '검토 항목 선택을 변경했습니다.',
        p_updated_at
    );

    return jsonb_build_object(
        'outcome', 'UPDATED',
        'item', to_jsonb(v_item)
    );
end;
$$;

revoke all on function public.update_review_item_selection_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    timestamptz
) from public;

grant execute on function public.update_review_item_selection_with_audit(
    uuid,
    uuid,
    uuid,
    text,
    text,
    timestamptz
) to service_role;
