-- P2 16.2 / 17.5: atomically append private performance-report upload
-- metadata and its non-sensitive audit event. Storage bytes are written before
-- this RPC and removed by the application if this transaction does not commit.

create function public.create_performance_report_upload_with_audit(
    p_owner_id uuid,
    p_document_id uuid,
    p_report_id uuid,
    p_contract_id uuid,
    p_period text,
    p_storage_path text,
    p_content_type text,
    p_size_bytes bigint,
    p_page_count integer,
    p_created_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_contract public.contracts%rowtype;
    v_document public.documents%rowtype;
    v_report public.performance_reports%rowtype;
begin
    if p_owner_id is null
       or p_document_id is null
       or p_report_id is null
       or p_contract_id is null
       or p_period is null
       or p_storage_path is null
       or p_content_type is null
       or p_size_bytes is null
       or p_page_count is null
       or p_created_at is null then
        raise exception 'performance report upload metadata is required'
            using errcode = '22004';
    end if;
    if p_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' then
        raise exception 'p_period must use YYYY-MM'
            using errcode = '22023';
    end if;

    -- Lock order matches the extraction RPCs: Contract, report, Document.
    -- The owner predicate is part of the lock query so foreign resources remain
    -- indistinguishable from missing resources.
    select contract.*
    into v_contract
    from public.contracts as contract
    where contract.id = p_contract_id
      and contract.owner_id = p_owner_id
    for update;

    if not found then
        return jsonb_build_object('outcome', 'NOT_FOUND');
    end if;

    -- A retry after a committed-but-lost response uses the same pre-generated
    -- IDs. Compare immutable upload identity before checking current status:
    -- extraction may legitimately have advanced both technical statuses.
    select report.*
    into v_report
    from public.performance_reports as report
    where report.id = p_report_id
    for update;

    if found then
        select document.*
        into v_document
        from public.documents as document
        where document.id = v_report.source_document_id
        for update;

        if found
           and v_report.contract_id = p_contract_id
           and v_report.period = p_period
           and v_report.source_document_id = p_document_id
           and v_report.created_at = p_created_at
           and v_document.id = p_document_id
           and v_document.contract_id = p_contract_id
           and v_document.type = 'PERFORMANCE_REPORT'
           and v_document.storage_path = p_storage_path
           and v_document.content_type = p_content_type
           and v_document.size_bytes = p_size_bytes
           and v_document.page_count = p_page_count
           and v_document.created_at = p_created_at then
            return jsonb_build_object(
                'outcome', 'REPLAYED',
                'report', to_jsonb(v_report),
                'source_document', to_jsonb(v_document)
            );
        end if;

        return jsonb_build_object('outcome', 'CONFLICT');
    end if;

    -- Do not allow a caller to attach a new report to an unrelated existing
    -- document ID, even when its metadata happens to look similar.
    perform 1
    from public.documents as document
    where document.id = p_document_id
    for update;

    if found then
        return jsonb_build_object('outcome', 'CONFLICT');
    end if;

    if v_contract.status not in ('SIGNED', 'IN_PROGRESS', 'RENEWAL_DUE', 'COMPLETED') then
        return jsonb_build_object('outcome', 'INVALID_STATUS');
    end if;

    select report.*
    into v_report
    from public.performance_reports as report
    where report.contract_id = p_contract_id
      and report.period = p_period
    for update;

    if found then
        return jsonb_build_object('outcome', 'PERIOD_ALREADY_EXISTS');
    end if;

    insert into public.documents (
        id,
        contract_id,
        type,
        parse_status,
        storage_path,
        content_type,
        size_bytes,
        page_count,
        created_at
    )
    values (
        p_document_id,
        p_contract_id,
        'PERFORMANCE_REPORT',
        'PENDING',
        p_storage_path,
        p_content_type,
        p_size_bytes,
        p_page_count,
        p_created_at
    )
    returning * into v_document;

    insert into public.performance_reports (
        id,
        contract_id,
        period,
        source_document_id,
        status,
        extracted_payload,
        current_revision_id,
        revision_count,
        extraction_attempt_id,
        extraction_started_at,
        created_at,
        updated_at
    )
    values (
        p_report_id,
        p_contract_id,
        p_period,
        p_document_id,
        'UPLOADED',
        null,
        null,
        0,
        null,
        null,
        p_created_at,
        p_created_at
    )
    returning * into v_report;

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
        'PERFORMANCE_REPORT_UPLOADED',
        'OWNER',
        '광고효과 리포트를 업로드했습니다.',
        '{}'::jsonb,
        p_created_at
    );

    return jsonb_build_object(
        'outcome', 'CREATED',
        'report', to_jsonb(v_report),
        'source_document', to_jsonb(v_document)
    );
end;
$$;

-- Upload rows must enter through the owner/status/audit transaction above.
revoke insert on table public.performance_reports from service_role;

revoke all on function public.create_performance_report_upload_with_audit(
    uuid, uuid, uuid, uuid, text, text, text, bigint, integer, timestamptz
) from public, anon, authenticated;
grant execute on function public.create_performance_report_upload_with_audit(
    uuid, uuid, uuid, uuid, text, text, text, bigint, integer, timestamptz
) to service_role;
