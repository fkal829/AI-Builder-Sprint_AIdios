-- C-1: a state compare-and-set update and its audit entry are one transaction.
-- The core tables are created by the shared schema migration. This function uses
-- dynamic SQL so it can be applied before that schema migration without relying
-- on a table that does not yet exist at function-definition time.

create or replace function public.apply_state_transition_with_audit(
  p_entity_type text,
  p_entity_id uuid,
  p_contract_id uuid,
  p_current_status text,
  p_target_status text,
  p_event_type text,
  p_actor_type text,
  p_summary text
)
returns boolean
language plpgsql
set search_path = public
as $$
declare
  v_table_name text;
  v_row_count integer;
begin
  case p_entity_type
    when 'CONTRACT' then v_table_name := 'contracts';
    when 'ADJUSTMENT_REQUEST' then v_table_name := 'adjustment_requests';
    when 'INTERNAL_SIGNATURE' then v_table_name := 'signatures';
    when 'OBLIGATION' then v_table_name := 'obligations';
    when 'ANALYSIS_TASK' then v_table_name := 'analysis_tasks';
    else raise exception 'Unknown state entity type: %', p_entity_type using errcode = '22023';
  end case;

  if to_regclass(format('public.%I', v_table_name)) is null then
    raise exception 'State table % does not exist', v_table_name using errcode = '42P01';
  end if;
  if to_regclass('public.audit_events') is null then
    raise exception 'audit_events table does not exist' using errcode = '42P01';
  end if;

  execute format(
    'update public.%I set status = %L, updated_at = now() where id = $1 and status::text = %L',
    v_table_name,
    p_target_status,
    p_current_status
  ) using p_entity_id;
  get diagnostics v_row_count = row_count;

  if v_row_count <> 1 then
    return false;
  end if;

  execute format(
    'insert into public.audit_events (contract_id, event_type, actor_type, summary) values ($1, %L, %L, $2)',
    p_event_type,
    p_actor_type
  ) using p_contract_id, p_summary;

  return true;
end;
$$;

revoke all on function public.apply_state_transition_with_audit(text, uuid, uuid, text, text, text, text, text)
  from public;
grant execute on function public.apply_state_transition_with_audit(text, uuid, uuid, text, text, text, text, text)
  to service_role;

-- Analysis success must not leave AnalysisTask=COMPLETED while its Contract is
-- still ANALYZING. The rows are locked in a stable order before either update.
create or replace function public.complete_analysis_with_audit(
  p_analysis_task_id uuid,
  p_contract_id uuid,
  p_current_task_status text,
  p_current_contract_status text,
  p_event_type text,
  p_actor_type text,
  p_summary text
)
returns boolean
language plpgsql
set search_path = public
as $$
begin
  if to_regclass('public.contracts') is null
    or to_regclass('public.analysis_tasks') is null
    or to_regclass('public.audit_events') is null then
    raise exception 'Core state tables do not exist' using errcode = '42P01';
  end if;

  execute 'select 1 from public.contracts where id = $1 and status::text = $2 for update'
    using p_contract_id, p_current_contract_status;
  if not found then
    return false;
  end if;

  execute 'select 1 from public.analysis_tasks where id = $1 and contract_id = $2 and status::text = $3 for update'
    using p_analysis_task_id, p_contract_id, p_current_task_status;
  if not found then
    return false;
  end if;

  execute 'update public.analysis_tasks set status = $1, updated_at = now() where id = $2'
    using 'COMPLETED', p_analysis_task_id;
  execute 'update public.contracts set status = $1, updated_at = now() where id = $2'
    using 'REVIEW_REQUIRED', p_contract_id;
  execute format(
    'insert into public.audit_events (contract_id, event_type, actor_type, summary) values ($1, %L, %L, $2)',
    p_event_type,
    p_actor_type
  ) using p_contract_id, p_summary;

  return true;
end;
$$;

revoke all on function public.complete_analysis_with_audit(uuid, uuid, text, text, text, text, text)
  from public;
grant execute on function public.complete_analysis_with_audit(uuid, uuid, text, text, text, text, text)
  to service_role;
