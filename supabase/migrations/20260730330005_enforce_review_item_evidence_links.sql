-- B analysis evidence integrity: every review item must point to extracted
-- terms from the same analysis task, and its primary source fields must match
-- one of the linked contract-document terms exactly.

create or replace function public.enforce_review_item_evidence_links()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if cardinality(new.related_extracted_term_ids) <> (
        select count(distinct related_id)
        from unnest(new.related_extracted_term_ids) as related(related_id)
    ) then
        raise exception 'review item related extracted terms must be unique'
            using errcode = '23514';
    end if;

    if exists (
        select 1
        from unnest(new.related_extracted_term_ids) as related(related_id)
        left join public.extracted_terms term
          on term.id = related_id
         and term.analysis_task_id = new.analysis_task_id
         and term.contract_id = new.contract_id
        where term.id is null
    ) then
        raise exception 'review item evidence must belong to the same analysis result'
            using errcode = '23514';
    end if;

    if (
        new.verification_status in ('VERIFIED', 'NEEDS_CHECK')
        and new.source_document_id is null
    ) or (
        new.verification_status in ('NOT_FOUND', 'MISSING_EVIDENCE')
        and new.source_document_id is not null
    ) then
        raise exception 'review item evidence fields do not match verification status'
            using errcode = '23514';
    end if;

    if new.source_document_id is not null and not exists (
        select 1
        from public.extracted_terms term
        where term.id = any(new.related_extracted_term_ids)
          and term.analysis_task_id = new.analysis_task_id
          and term.contract_id = new.contract_id
          and term.source_type = 'CONTRACT_DOCUMENT'
          and term.verification_status in ('VERIFIED', 'NEEDS_CHECK')
          and term.document_id = new.source_document_id
          and term.source_page = new.source_page
          and term.source_text = new.source_text
          and term.confidence = new.source_confidence
    ) then
        raise exception 'review item source fields must match a related contract term'
            using errcode = '23514';
    end if;

    return new;
end;
$$;

drop trigger if exists review_items_evidence_link_guard
    on public.review_items;

create trigger review_items_evidence_link_guard
before insert or update on public.review_items
for each row
execute function public.enforce_review_item_evidence_links();

-- Fire the guard for pre-existing rows without changing their values.  The
-- migration stops instead of silently preserving an invalid evidence link.
update public.review_items
set updated_at = updated_at;

revoke all on function public.enforce_review_item_evidence_links()
    from public, anon, authenticated;
