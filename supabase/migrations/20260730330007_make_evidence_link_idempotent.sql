-- B 7.3: reserve/validate idempotency, create the evidence token and audit,
-- and persist the replay payload in one transaction.  A lost RPC response can
-- therefore be retried without creating a second token or audit event.

create or replace function public.create_obligation_evidence_link_idempotent(
    p_owner_id uuid,
    p_contract_id uuid,
    p_obligation_id uuid,
    p_idempotency_key uuid,
    p_request_hash text,
    p_public_token_id uuid,
    p_token_hash text,
    p_token_scope text,
    p_token_resource_id uuid,
    p_token_expires_at timestamptz,
    p_token_created_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract_status text;
    v_obligation_status text;
    v_record public.idempotency_records%rowtype;
    v_is_new boolean;
    v_replay_payload jsonb;
begin
    if p_request_hash !~ '^[0-9a-f]{64}$'
       or p_token_hash !~ '^[0-9a-f]{64}$'
       or p_token_scope <> 'OBLIGATION_EVIDENCE'
       or p_token_resource_id <> p_obligation_id
       or p_token_expires_at <= p_token_created_at then
        raise exception 'invalid obligation evidence idempotency payload'
            using errcode = '22023';
    end if;

    insert into public.idempotency_records (
        owner_id,
        operation,
        resource_id,
        idempotency_key,
        request_hash,
        created_at
    )
    values (
        p_owner_id,
        'EVIDENCE_LINK_CREATE',
        p_obligation_id,
        p_idempotency_key,
        p_request_hash,
        p_token_created_at
    )
    on conflict (owner_id, operation, resource_id, idempotency_key) do nothing;
    v_is_new := found;

    select * into v_record
    from public.idempotency_records
    where owner_id = p_owner_id
      and operation = 'EVIDENCE_LINK_CREATE'
      and resource_id = p_obligation_id
      and idempotency_key = p_idempotency_key
    for update;

    if not found then
        raise exception 'idempotency reservation disappeared'
            using errcode = '40001';
    end if;
    if v_record.request_hash <> p_request_hash then
        return jsonb_build_object('outcome', 'IDEMPOTENCY_CONFLICT');
    end if;
    if v_record.response_status is not null then
        if v_record.response_status <> 201
           or v_record.response_payload is null
           or v_record.response_payload ->> 'token_id' is null
           or v_record.response_payload ->> 'expires_at' is null then
            raise exception 'invalid evidence-link replay payload'
                using errcode = '22023';
        end if;
        return jsonb_build_object(
            'outcome', 'REPLAY',
            'token_id', v_record.response_payload ->> 'token_id',
            'expires_at', v_record.response_payload ->> 'expires_at'
        );
    end if;
    if not v_is_new then
        return jsonb_build_object('outcome', 'IDEMPOTENCY_PENDING');
    end if;

    select obligation.status, contract.status
    into v_obligation_status, v_contract_status
    from public.obligations obligation
    join public.contracts contract on contract.id = obligation.contract_id
    where obligation.id = p_obligation_id
      and obligation.contract_id = p_contract_id
      and contract.owner_id = p_owner_id
    for update of obligation, contract;

    if not found then
        delete from public.idempotency_records
        where owner_id = p_owner_id
          and operation = 'EVIDENCE_LINK_CREATE'
          and resource_id = p_obligation_id
          and idempotency_key = p_idempotency_key;
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;
    if v_obligation_status <> 'PENDING'
       or v_contract_status not in ('SIGNED', 'IN_PROGRESS') then
        delete from public.idempotency_records
        where owner_id = p_owner_id
          and operation = 'EVIDENCE_LINK_CREATE'
          and resource_id = p_obligation_id
          and idempotency_key = p_idempotency_key;
        return jsonb_build_object('outcome', 'INVALID_STATUS_TRANSITION');
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

    v_replay_payload := jsonb_build_object(
        'token_id', p_public_token_id::text,
        'expires_at', p_token_expires_at::text
    );
    update public.idempotency_records
    set
        response_status = 201,
        response_payload = v_replay_payload
    where owner_id = p_owner_id
      and operation = 'EVIDENCE_LINK_CREATE'
      and resource_id = p_obligation_id
      and idempotency_key = p_idempotency_key
      and request_hash = p_request_hash
      and response_status is null;
    if not found then
        raise exception 'idempotency completion failed'
            using errcode = '40001';
    end if;

    return jsonb_build_object(
        'outcome', 'CREATED',
        'token_id', p_public_token_id::text,
        'expires_at', p_token_expires_at::text
    );
end;
$$;

revoke all on function public.create_obligation_evidence_link_idempotent(
    uuid, uuid, uuid, uuid, text, uuid, text, text, uuid, timestamptz, timestamptz
) from public, anon, authenticated;
grant execute on function public.create_obligation_evidence_link_idempotent(
    uuid, uuid, uuid, uuid, text, uuid, text, text, uuid, timestamptz, timestamptz
) to service_role;

revoke execute on function public.create_obligation_evidence_link_with_audit(
    uuid, uuid, uuid, uuid, text, text, uuid, timestamptz, timestamptz
) from service_role;
