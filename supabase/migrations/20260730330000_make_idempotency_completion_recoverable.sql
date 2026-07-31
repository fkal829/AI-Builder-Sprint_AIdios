-- Make replay completion safe to retry after an ambiguous network failure.
-- A retry may observe that the first RPC committed even though its response was lost.

create or replace function public.complete_idempotency(
  p_owner_id uuid,
  p_operation text,
  p_resource_id uuid,
  p_idempotency_key uuid,
  p_request_hash text,
  p_response_status integer,
  p_response_payload jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_record public.idempotency_records%rowtype;
begin
  select *
    into v_record
    from public.idempotency_records
    where owner_id = p_owner_id
      and operation = p_operation
      and resource_id = p_resource_id
      and idempotency_key = p_idempotency_key
    for update;

  if not found or v_record.request_hash <> p_request_hash then
    raise exception 'Idempotency reservation does not match'
      using errcode = '40001';
  end if;

  if v_record.response_status is null then
    update public.idempotency_records
      set response_status = p_response_status,
          response_payload = p_response_payload
      where owner_id = p_owner_id
        and operation = p_operation
        and resource_id = p_resource_id
        and idempotency_key = p_idempotency_key
      returning * into v_record;
    return to_jsonb(v_record);
  end if;

  if v_record.response_status = p_response_status
     and v_record.response_payload is not distinct from p_response_payload then
    return to_jsonb(v_record);
  end if;

  raise exception 'Completed idempotency response cannot be changed'
    using errcode = '40001';
end;
$$;

revoke all on function public.complete_idempotency(
  uuid,
  text,
  uuid,
  uuid,
  text,
  integer,
  jsonb
) from public;

grant execute on function public.complete_idempotency(
  uuid,
  text,
  uuid,
  uuid,
  text,
  integer,
  jsonb
) to service_role;
