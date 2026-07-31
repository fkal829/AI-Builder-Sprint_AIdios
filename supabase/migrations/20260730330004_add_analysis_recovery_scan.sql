-- P0 4.4: deterministic worker scan for tasks left QUEUED after an in-process request ends.
-- This function reads candidates only; the worker claims each task in the existing processor.

create index if not exists analysis_tasks_queued_recovery_idx
    on public.analysis_tasks (created_at asc, id asc)
    where status = 'QUEUED';

create or replace function public.list_stale_queued_analysis_jobs(
    p_stale_before timestamptz,
    p_limit integer
)
returns table (
    owner_id uuid,
    task_id uuid,
    created_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
begin
    if p_stale_before is null then
        raise exception 'p_stale_before is required' using errcode = '22004';
    end if;
    if p_limit not between 1 and 100 then
        raise exception 'p_limit must be between 1 and 100' using errcode = '22023';
    end if;

    return query
    select
        contracts.owner_id,
        tasks.id,
        tasks.created_at
    from public.analysis_tasks as tasks
    join public.contracts as contracts on contracts.id = tasks.contract_id
    where tasks.status = 'QUEUED'
      and tasks.created_at <= p_stale_before
    order by tasks.created_at asc, tasks.id asc
    limit p_limit;
end;
$$;

revoke all on function public.list_stale_queued_analysis_jobs(timestamptz, integer)
    from public, anon, authenticated;
grant execute on function public.list_stale_queued_analysis_jobs(timestamptz, integer)
    to service_role;
