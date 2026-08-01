-- P2 17.2: atomically claim, complete, or fail one performance-report
-- extraction attempt. External Parse/Solar calls run outside these short RPCs.

create function public.claim_performance_report_extraction(
    p_owner_id uuid,
    p_contract_id uuid,
    p_report_id uuid,
    p_attempt_id uuid,
    p_started_at timestamptz,
    p_stale_before timestamptz,
    p_idempotency_key uuid
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract_status text;
    v_report public.performance_reports%rowtype;
    v_document public.documents%rowtype;
    v_previous_attempt_id uuid;
    v_recovered boolean := false;
begin
    if p_owner_id is null
       or p_contract_id is null
       or p_report_id is null
       or p_attempt_id is null
       or p_started_at is null
       or p_stale_before is null
       or p_idempotency_key is null then
        raise exception 'performance report extraction claim arguments are required'
            using errcode = '22004';
    end if;
    if p_stale_before > p_started_at then
        raise exception 'p_stale_before must not be later than p_started_at'
            using errcode = '22023';
    end if;
    if p_attempt_id <> p_idempotency_key then
        raise exception 'p_attempt_id must equal the current idempotency key'
            using errcode = '22023';
    end if;

    -- All three rows use the same lock order in the claim/complete/fail RPCs.
    -- The owner predicate is part of the contract lookup so a foreign contract
    -- and a missing contract have the same outcome.
    select contract.status into v_contract_status
    from public.contracts as contract
    where contract.id = p_contract_id
      and contract.owner_id = p_owner_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    select report.* into v_report
    from public.performance_reports as report
    where report.id = p_report_id
      and report.contract_id = p_contract_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    select document.* into v_document
    from public.documents as document
    where document.id = v_report.source_document_id
      and document.contract_id = p_contract_id
      and document.type = 'PERFORMANCE_REPORT'
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    if v_contract_status not in ('SIGNED', 'IN_PROGRESS', 'RENEWAL_DUE', 'COMPLETED')
       or v_report.status <> 'UPLOADED'
       or v_report.extracted_payload is not null
       or v_report.current_revision_id is not null
       or v_report.revision_count <> 0 then
        return jsonb_build_object('outcome', 'INVALID_STATUS');
    end if;
    if p_started_at < v_report.created_at
       or p_started_at < v_report.updated_at then
        raise exception 'p_started_at precedes the persisted report timestamps'
            using errcode = '22023';
    end if;

    if v_document.parse_status = 'PROCESSING' then
        -- The first claim may have committed even if its RPC response was lost.
        -- Replaying that exact attempt returns the already-claimed rows and must
        -- neither call it stale nor create a second recovery audit event.
        if v_report.extraction_attempt_id = p_attempt_id
           and v_report.extraction_started_at is not null then
            return jsonb_build_object(
                'outcome', 'CLAIMED',
                'report', to_jsonb(v_report),
                'source_document', to_jsonb(v_document)
            );
        end if;

        if v_report.extraction_attempt_id is null
           or v_report.extraction_started_at is null then
            return jsonb_build_object('outcome', 'IN_PROGRESS');
        end if;

        -- started_at <= stale_before is exactly the documented >= 15 minute
        -- boundary. A newer attempt remains active and must not call AI again.
        if v_report.extraction_started_at > p_stale_before then
            return jsonb_build_object(
                'outcome', 'IN_PROGRESS',
                'attempt_id', v_report.extraction_attempt_id,
                'started_at', v_report.extraction_started_at
            );
        end if;
        v_previous_attempt_id := v_report.extraction_attempt_id;

        -- The new key has already been reserved by the common idempotency
        -- service. Remove only older unfinished extract reservations. Completed
        -- responses remain immutable and the current reservation is preserved.
        delete from public.idempotency_records
        where owner_id = p_owner_id
          and operation = 'PERFORMANCE_REPORT_EXTRACT'
          and resource_id = p_report_id
          and idempotency_key <> p_idempotency_key
          and response_status is null;

        insert into public.audit_events (
            contract_id,
            event_type,
            actor_type,
            summary,
            payload,
            created_at
        )
        values (
            p_contract_id,
            'PERFORMANCE_REPORT_EXTRACTION_RECOVERED',
            'OWNER',
            '15분 이상 지연된 광고효과 리포트 추출을 명시적으로 재시도했습니다.',
            jsonb_build_object(
                'report_id', p_report_id,
                'previous_attempt_id', v_previous_attempt_id,
                'attempt_id', p_attempt_id
            ),
            p_started_at
        );
        v_recovered := true;
    end if;

    update public.documents
    set parse_status = 'PROCESSING'
    where id = v_document.id
      and contract_id = p_contract_id
      and type = 'PERFORMANCE_REPORT'
    returning * into v_document;
    if not found then
        raise exception 'performance report source document changed during claim'
            using errcode = '40001';
    end if;

    update public.performance_reports
    set extraction_attempt_id = p_attempt_id,
        extraction_started_at = p_started_at,
        updated_at = p_started_at
    where id = p_report_id
      and contract_id = p_contract_id
      and status = 'UPLOADED'
    returning * into v_report;
    if not found then
        raise exception 'performance report changed during extraction claim'
            using errcode = '40001';
    end if;

    return jsonb_build_object(
        'outcome', case when v_recovered then 'RECOVERED' else 'CLAIMED' end,
        'report', to_jsonb(v_report),
        'source_document', to_jsonb(v_document)
    );
end;
$$;

create function public.complete_performance_report_extraction(
    p_owner_id uuid,
    p_contract_id uuid,
    p_report_id uuid,
    p_attempt_id uuid,
    p_extracted_payload jsonb,
    p_completed_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract_status text;
    v_report public.performance_reports%rowtype;
    v_document public.documents%rowtype;
begin
    if p_owner_id is null
       or p_contract_id is null
       or p_report_id is null
       or p_attempt_id is null
       or p_extracted_payload is null
       or p_completed_at is null then
        raise exception 'performance report extraction completion arguments are required'
            using errcode = '22004';
    end if;
    if jsonb_typeof(p_extracted_payload) is distinct from 'object' then
        raise exception 'p_extracted_payload must be an object'
            using errcode = '22023';
    end if;

    select contract.status into v_contract_status
    from public.contracts as contract
    where contract.id = p_contract_id
      and contract.owner_id = p_owner_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    select report.* into v_report
    from public.performance_reports as report
    where report.id = p_report_id
      and report.contract_id = p_contract_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    select document.* into v_document
    from public.documents as document
    where document.id = v_report.source_document_id
      and document.contract_id = p_contract_id
      and document.type = 'PERFORMANCE_REPORT'
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    if v_contract_status not in ('SIGNED', 'IN_PROGRESS', 'RENEWAL_DUE', 'COMPLETED') then
        return jsonb_build_object('outcome', 'INVALID_STATUS');
    end if;

    -- A replaced attempt can never change Document/report state or create an
    -- audit event, regardless of whether its late response is success or error.
    if v_report.extraction_attempt_id is distinct from p_attempt_id then
        return jsonb_build_object('outcome', 'STALE');
    end if;

    -- Make a retried RPC safe after an ambiguous committed response without
    -- duplicating PERFORMANCE_REPORT_EXTRACTED.
    if v_report.status = 'EXTRACTED'
       and v_report.extracted_payload is not distinct from p_extracted_payload
       and v_document.parse_status = 'COMPLETED' then
        return jsonb_build_object(
            'outcome', 'APPLIED',
            'report', to_jsonb(v_report),
            'source_document', to_jsonb(v_document)
        );
    end if;

    if v_report.status <> 'UPLOADED'
       or v_report.extracted_payload is not null
       or v_report.current_revision_id is not null
       or v_report.revision_count <> 0
       or v_document.parse_status <> 'PROCESSING'
       or v_report.extraction_started_at is null then
        return jsonb_build_object('outcome', 'INVALID_STATUS');
    end if;
    if p_completed_at < v_report.extraction_started_at then
        raise exception 'p_completed_at precedes extraction_started_at'
            using errcode = '22023';
    end if;

    update public.documents
    set parse_status = 'COMPLETED'
    where id = v_document.id
      and contract_id = p_contract_id
      and type = 'PERFORMANCE_REPORT'
      and parse_status = 'PROCESSING'
    returning * into v_document;
    if not found then
        raise exception 'performance report source document changed during completion'
            using errcode = '40001';
    end if;

    update public.performance_reports
    set status = 'EXTRACTED',
        extracted_payload = p_extracted_payload,
        updated_at = p_completed_at
    where id = p_report_id
      and contract_id = p_contract_id
      and status = 'UPLOADED'
      and extraction_attempt_id = p_attempt_id
    returning * into v_report;
    if not found then
        raise exception 'performance report changed during extraction completion'
            using errcode = '40001';
    end if;

    insert into public.audit_events (
        contract_id,
        event_type,
        actor_type,
        summary,
        payload,
        created_at
    )
    values (
        p_contract_id,
        'PERFORMANCE_REPORT_EXTRACTED',
        'SYSTEM',
        '광고효과 리포트의 지표 후보와 근거를 추출했습니다.',
        jsonb_build_object(
            'report_id', p_report_id,
            'attempt_id', p_attempt_id
        ),
        p_completed_at
    );

    return jsonb_build_object(
        'outcome', 'APPLIED',
        'report', to_jsonb(v_report),
        'source_document', to_jsonb(v_document)
    );
end;
$$;

create function public.fail_performance_report_extraction(
    p_owner_id uuid,
    p_contract_id uuid,
    p_report_id uuid,
    p_attempt_id uuid,
    p_document_parse_status text,
    p_failed_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract_status text;
    v_report public.performance_reports%rowtype;
    v_document public.documents%rowtype;
begin
    if p_owner_id is null
       or p_contract_id is null
       or p_report_id is null
       or p_attempt_id is null
       or p_document_parse_status is null
       or p_failed_at is null then
        raise exception 'performance report extraction failure arguments are required'
            using errcode = '22004';
    end if;
    if p_document_parse_status not in ('FAILED', 'COMPLETED') then
        raise exception 'p_document_parse_status must be FAILED or COMPLETED'
            using errcode = '22023';
    end if;

    select contract.status into v_contract_status
    from public.contracts as contract
    where contract.id = p_contract_id
      and contract.owner_id = p_owner_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    select report.* into v_report
    from public.performance_reports as report
    where report.id = p_report_id
      and report.contract_id = p_contract_id
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    select document.* into v_document
    from public.documents as document
    where document.id = v_report.source_document_id
      and document.contract_id = p_contract_id
      and document.type = 'PERFORMANCE_REPORT'
    for update;
    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    if v_contract_status not in ('SIGNED', 'IN_PROGRESS', 'RENEWAL_DUE', 'COMPLETED') then
        return jsonb_build_object('outcome', 'INVALID_STATUS');
    end if;
    if v_report.extraction_attempt_id is distinct from p_attempt_id then
        return jsonb_build_object('outcome', 'STALE');
    end if;

    -- A repeated call after an ambiguous committed response is applied already;
    -- do not create a second audit event.
    if v_report.status = 'UPLOADED'
       and v_report.extracted_payload is null
       and v_report.current_revision_id is null
       and v_report.revision_count = 0
       and v_document.parse_status = p_document_parse_status then
        return jsonb_build_object(
            'outcome', 'APPLIED',
            'report', to_jsonb(v_report),
            'source_document', to_jsonb(v_document)
        );
    end if;

    if v_report.status <> 'UPLOADED'
       or v_report.extracted_payload is not null
       or v_report.current_revision_id is not null
       or v_report.revision_count <> 0
       or v_document.parse_status <> 'PROCESSING'
       or v_report.extraction_started_at is null then
        return jsonb_build_object('outcome', 'INVALID_STATUS');
    end if;
    if p_failed_at < v_report.extraction_started_at then
        raise exception 'p_failed_at precedes extraction_started_at'
            using errcode = '22023';
    end if;

    update public.documents
    set parse_status = p_document_parse_status
    where id = v_document.id
      and contract_id = p_contract_id
      and type = 'PERFORMANCE_REPORT'
      and parse_status = 'PROCESSING'
    returning * into v_document;
    if not found then
        raise exception 'performance report source document changed during failure'
            using errcode = '40001';
    end if;

    -- Keep the user workflow at UPLOADED and do not persist a partial result.
    update public.performance_reports
    set status = 'UPLOADED',
        extracted_payload = null,
        current_revision_id = null,
        revision_count = 0,
        updated_at = p_failed_at
    where id = p_report_id
      and contract_id = p_contract_id
      and status = 'UPLOADED'
      and extraction_attempt_id = p_attempt_id
    returning * into v_report;
    if not found then
        raise exception 'performance report changed during extraction failure'
            using errcode = '40001';
    end if;

    return jsonb_build_object(
        'outcome', 'APPLIED',
        'report', to_jsonb(v_report),
        'source_document', to_jsonb(v_document)
    );
end;
$$;

-- Application writes must use the lock-ordered RPCs. Removing direct UPDATE
-- prevents a report-first lock from racing with the contract-first workflow.
revoke update on table public.performance_reports from service_role;

revoke all on function public.claim_performance_report_extraction(
    uuid, uuid, uuid, uuid, timestamptz, timestamptz, uuid
) from public, anon, authenticated;
grant execute on function public.claim_performance_report_extraction(
    uuid, uuid, uuid, uuid, timestamptz, timestamptz, uuid
) to service_role;

revoke all on function public.complete_performance_report_extraction(
    uuid, uuid, uuid, uuid, jsonb, timestamptz
) from public, anon, authenticated;
grant execute on function public.complete_performance_report_extraction(
    uuid, uuid, uuid, uuid, jsonb, timestamptz
) to service_role;

revoke all on function public.fail_performance_report_extraction(
    uuid, uuid, uuid, uuid, text, timestamptz
) from public, anon, authenticated;
grant execute on function public.fail_performance_report_extraction(
    uuid, uuid, uuid, uuid, text, timestamptz
) to service_role;
