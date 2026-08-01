-- P2 16.4 follow-up: make performance flag evidence complete and immutable at
-- the database boundary. This is append-only because 20260801060000 is already
-- deployed.

-- Keep the source ExtractedTerm stable between snapshot validation and commit.
-- Extracted terms are analysis output facts and are append-only: corrections
-- create a new analysis task instead of mutating a prior source row. FOR SHARE
-- also keeps the validated source stable for the remainder of the basis write.
create or replace function public.enforce_performance_flag_basis_term_snapshot()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    perform term.id
    from public.performance_flags as flag
    join public.performance_report_revisions as revision
      on revision.id = flag.report_revision_id
    join public.performance_reports as report
      on report.id = revision.report_id
    join public.extracted_terms as term
      on term.id = new.extracted_term_id
     and term.contract_id = report.contract_id
    join public.analysis_tasks as task
      on task.id = term.analysis_task_id
     and task.contract_id = report.contract_id
    join public.documents as document
      on document.id = term.document_id
     and document.contract_id = report.contract_id
    where flag.id = new.flag_id
      and term.document_id is not distinct from new.document_id
      and term.field is not distinct from new.field
      and term.source_type is not distinct from new.source_type
      and term.source_type = 'CONTRACT_DOCUMENT'
      and term.source_page is not distinct from new.source_page
      and term.source_text is not distinct from new.source_text
      and term.confidence is not distinct from new.confidence
      and term.verification_status is not distinct from new.verification_status
      and term.verification_status = 'VERIFIED'
    for share of term;

    if not found then
        raise exception 'performance flag basis must exactly match a same-contract VERIFIED term'
            using errcode = '23514',
                  constraint = 'performance_flag_basis_terms_same_contract_verified_check';
    end if;

    return new;
end;
$$;

revoke all on function public.enforce_performance_flag_basis_term_snapshot()
    from public, anon, authenticated, service_role;

create function public.prevent_extracted_term_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    raise exception 'ExtractedTerm rows are append-only and cannot be updated'
        using errcode = '55000',
              constraint = 'extracted_terms_append_only';
end;
$$;

revoke all on function public.prevent_extracted_term_update()
    from public, anon, authenticated, service_role;

create trigger extracted_terms_append_only_guard
    before update
    on public.extracted_terms
    for each row
    execute function public.prevent_extracted_term_update();

-- Analysis results are append-only. The completion RPC already performs the
-- only production INSERT. The existing basis foreign key with ON DELETE
-- RESTRICT prevents deletion of a referenced term; service-role direct DELETE
-- and TRUNCATE are also unnecessary.
revoke update, delete, truncate on table public.extracted_terms from service_role;

-- A deliverable shortfall requires exactly one verified quantity term and one
-- verified monthly-frequency term. Other flag types must not carry contract
-- basis rows. A deferred assertion permits the atomic RPC to insert the flag
-- before its two child rows while still enforcing the invariant at commit.
create function public.assert_performance_flag_basis_complete(p_flag_id uuid)
returns void
language plpgsql
set search_path = ''
as $$
declare
    v_flag_type text;
    v_basis_count integer;
    v_quantity_count integer;
    v_frequency_count integer;
begin
    select flag.flag_type into v_flag_type
    from public.performance_flags as flag
    where flag.id = p_flag_id;

    if not found then
        return;
    end if;

    select
        count(*)::integer,
        count(*) filter (where basis.field = 'content_quantity')::integer,
        count(*) filter (where basis.field = 'posting_frequency')::integer
    into v_basis_count, v_quantity_count, v_frequency_count
    from public.performance_flag_basis_terms as basis
    where basis.flag_id = p_flag_id;

    if v_flag_type = 'DELIVERABLE_COUNT_SHORTFALL' then
        if v_basis_count <> 2
           or v_quantity_count <> 1
           or v_frequency_count <> 1 then
            raise exception 'deliverable shortfall requires quantity and monthly-frequency basis terms'
                using errcode = '23514',
                      constraint = 'performance_flags_basis_completeness_check';
        end if;
    elsif v_basis_count <> 0 then
        raise exception 'only deliverable shortfall flags may reference contract basis terms'
            using errcode = '23514',
                  constraint = 'performance_flags_basis_completeness_check';
    end if;
end;
$$;

revoke all on function public.assert_performance_flag_basis_complete(uuid)
    from public, anon, authenticated, service_role;

create function public.enforce_performance_flag_basis_completeness()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if tg_table_name = 'performance_flags' then
        if tg_op = 'DELETE' then
            perform public.assert_performance_flag_basis_complete(old.id);
            return old;
        end if;

        perform public.assert_performance_flag_basis_complete(new.id);
        if tg_op = 'UPDATE' and old.id is distinct from new.id then
            perform public.assert_performance_flag_basis_complete(old.id);
        end if;
        return new;
    end if;

    if tg_op = 'DELETE' then
        perform public.assert_performance_flag_basis_complete(old.flag_id);
        return old;
    end if;

    perform public.assert_performance_flag_basis_complete(new.flag_id);
    if tg_op = 'UPDATE' and old.flag_id is distinct from new.flag_id then
        perform public.assert_performance_flag_basis_complete(old.flag_id);
    end if;
    return new;
end;
$$;

revoke all on function public.enforce_performance_flag_basis_completeness()
    from public, anon, authenticated, service_role;

create constraint trigger performance_flags_basis_completeness_guard
    after insert or update or delete
    on public.performance_flags
    deferrable initially deferred
    for each row
    execute function public.enforce_performance_flag_basis_completeness();

create constraint trigger performance_flag_basis_terms_completeness_guard
    after insert or update or delete
    on public.performance_flag_basis_terms
    deferrable initially deferred
    for each row
    execute function public.enforce_performance_flag_basis_completeness();

-- Abort instead of silently repairing any state created in the deployment
-- window between 060000 and this migration.
do $$
declare
    v_flag record;
begin
    for v_flag in select id from public.performance_flags loop
        perform public.assert_performance_flag_basis_complete(v_flag.id);
    end loop;

    if exists (
        select 1
        from public.performance_flag_basis_terms as basis
        where not exists (
            select 1
            from public.performance_flags as flag
            join public.performance_report_revisions as revision
              on revision.id = flag.report_revision_id
            join public.performance_reports as report
              on report.id = revision.report_id
            join public.extracted_terms as term
              on term.id = basis.extracted_term_id
             and term.contract_id = report.contract_id
            join public.analysis_tasks as task
              on task.id = term.analysis_task_id
             and task.contract_id = report.contract_id
            join public.documents as document
              on document.id = term.document_id
             and document.contract_id = report.contract_id
            where flag.id = basis.flag_id
              and term.document_id is not distinct from basis.document_id
              and term.field is not distinct from basis.field
              and term.source_type is not distinct from basis.source_type
              and term.source_type = 'CONTRACT_DOCUMENT'
              and term.source_page is not distinct from basis.source_page
              and term.source_text is not distinct from basis.source_text
              and term.confidence is not distinct from basis.confidence
              and term.verification_status is not distinct from basis.verification_status
              and term.verification_status = 'VERIFIED'
        )
    ) then
        raise exception 'existing performance flag basis violates immutable snapshot rules'
            using errcode = '23514',
                  constraint = 'performance_flag_basis_terms_same_contract_verified_check';
    end if;
end;
$$;
