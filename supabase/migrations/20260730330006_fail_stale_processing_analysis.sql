-- P0 4.4: close analysis tasks that remain PROCESSING beyond the worker timeout.
-- The batch transition, document failure marker and audit event are one DB transaction.

create index if not exists analysis_tasks_processing_recovery_idx
    on public.analysis_tasks (updated_at asc, id asc)
    where status = 'PROCESSING';

create or replace function public.fail_stale_processing_analysis_jobs(
    p_stale_before timestamptz,
    p_limit integer
)
returns setof public.analysis_tasks
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_task public.analysis_tasks;
    v_saved public.analysis_tasks;
begin
    if p_stale_before is null then
        raise exception 'p_stale_before is required' using errcode = '22004';
    end if;
    if p_stale_before > now() then
        raise exception 'p_stale_before must not be in the future' using errcode = '22023';
    end if;
    if p_limit not between 1 and 100 then
        raise exception 'p_limit must be between 1 and 100' using errcode = '22023';
    end if;

    for v_task in
        select tasks.*
        from public.analysis_tasks as tasks
        where tasks.status = 'PROCESSING'
          and tasks.updated_at <= p_stale_before
        order by tasks.updated_at asc, tasks.id asc
        for update of tasks skip locked
        limit p_limit
    loop
        -- Recheck both predicates after the row lock in case processing completed first.
        update public.analysis_tasks
        set
            status = 'FAILED',
            error_code = 'DOCUMENT_PARSE_FAILED',
            result = null,
            updated_at = now()
        where id = v_task.id
          and status = 'PROCESSING'
          and updated_at <= p_stale_before
        returning * into v_saved;

        if not found then
            continue;
        end if;

        update public.documents
        set parse_status = 'FAILED'
        where id = v_saved.document_id
           or id = any(v_saved.supporting_document_ids);

        insert into public.audit_events (
            contract_id, event_type, actor_type, summary
        )
        values (
            v_saved.contract_id,
            'ANALYSIS_FAILED',
            'SYSTEM',
            '처리 제한 시간을 초과한 계약 분석을 실패 처리했습니다.'
        );

        return next v_saved;
    end loop;

    return;
end;
$$;

-- Correct the original failure RPC as well: every document claimed by the task must leave
-- PROCESSING on failure, not only the primary contract document.
create or replace function public.fail_analysis_with_audit(
    p_task_id uuid,
    p_attempt_count integer,
    p_error_code text
)
returns public.analysis_tasks
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_task public.analysis_tasks;
    v_saved public.analysis_tasks;
begin
    if p_attempt_count not between 1 and 2
       or p_error_code not in ('DOCUMENT_PARSE_FAILED', 'ANALYSIS_SCHEMA_INVALID') then
        raise exception 'invalid analysis failure payload' using errcode = '22023';
    end if;

    select * into v_task
    from public.analysis_tasks
    where id = p_task_id and status = 'PROCESSING'
    for update;
    if not found then
        return null;
    end if;

    update public.analysis_tasks
    set
        status = 'FAILED',
        attempt_count = p_attempt_count,
        error_code = p_error_code,
        result = null,
        updated_at = now()
    where id = p_task_id
    returning * into v_saved;

    update public.documents
    set parse_status = 'FAILED'
    where id = v_task.document_id
       or id = any(v_task.supporting_document_ids);

    insert into public.audit_events (
        contract_id, event_type, actor_type, summary
    )
    values (
        v_task.contract_id,
        'ANALYSIS_FAILED',
        'SYSTEM',
        '계약 분석에 실패했습니다.'
    );

    return v_saved;
end;
$$;

revoke all on function public.fail_stale_processing_analysis_jobs(timestamptz, integer)
    from public, anon, authenticated;
grant execute on function public.fail_stale_processing_analysis_jobs(timestamptz, integer)
    to service_role;

revoke all on function public.fail_analysis_with_audit(uuid, integer, text)
    from public, anon, authenticated;
grant execute on function public.fail_analysis_with_audit(uuid, integer, text)
    to service_role;
