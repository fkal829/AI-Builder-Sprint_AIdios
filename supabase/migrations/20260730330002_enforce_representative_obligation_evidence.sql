-- B 7.2: keep representative obligations only when all four required fields
-- come from one identical VERIFIED contract excerpt.
--
-- The original analysis completion RPC is already an applied migration.  A
-- BEFORE INSERT trigger lets incomplete candidates be skipped without
-- rewriting that history or failing the rest of the analysis transaction.

create or replace function public.keep_verified_representative_obligation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if not exists (
        select 1
        from public.extracted_terms term
        where term.contract_id = new.contract_id
          and term.document_id = new.source_document_id
          and term.source_type = 'CONTRACT_DOCUMENT'
          and term.source_page = new.source_page
          and term.source_text = new.source_text
          and term.verification_status = 'VERIFIED'
          and term.value is not null
          and (
              (term.field = 'advertising_channel' and term.value_type = 'TEXT')
              or (term.field = 'content_type' and term.value_type = 'TEXT')
              or (term.field = 'content_quantity' and term.value_type = 'INTEGER')
              or (term.field = 'deliverable_due_date' and term.value_type = 'DATE')
          )
        group by term.analysis_task_id
        having count(*) = 4
           and count(*) filter (
               where term.field = 'advertising_channel'
           ) = 1
           and count(*) filter (
               where term.field = 'content_type'
           ) = 1
           and count(*) filter (
               where term.field = 'content_quantity'
           ) = 1
           and count(*) filter (
               where term.field = 'deliverable_due_date'
           ) = 1
           and concat_ws(
               ' ',
               max(term.value #>> '{}') filter (
                   where term.field = 'advertising_channel'
               ),
               max(term.value #>> '{}') filter (
                   where term.field = 'content_type'
               ),
               (
                   max(term.value #>> '{}') filter (
                       where term.field = 'content_quantity'
                   )
               ) || '건'
           ) = new.title
           and (
               max(term.value #>> '{}') filter (
                   where term.field = 'deliverable_due_date'
               )
           )::date = new.due_date
           and min(term.confidence) = new.confidence
    ) then
        return null;
    end if;

    return new;
end;
$$;

drop trigger if exists obligations_verified_representative_guard
    on public.obligations;

create trigger obligations_verified_representative_guard
before insert on public.obligations
for each row
execute function public.keep_verified_representative_obligation();

revoke all on function public.keep_verified_representative_obligation()
    from public, anon, authenticated;
