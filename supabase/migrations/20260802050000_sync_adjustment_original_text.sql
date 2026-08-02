-- Preserve the review evidence excerpt as the immutable before-text used by
-- public adjustment requests and final agreement comparisons.

update public.review_items
set original_text = source_text
where source_text is not null
  and btrim(source_text) <> ''
  and original_text = '원계약에서 확인되지 않아 추가 확인 필요';

create or replace function public.sync_review_item_original_text()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.source_text is not null
    and btrim(new.source_text) <> ''
    and new.original_text = '원계약에서 확인되지 않아 추가 확인 필요'
  then
    new.original_text := new.source_text;
  end if;
  return new;
end;
$$;

drop trigger if exists review_items_original_text_sync on public.review_items;
create trigger review_items_original_text_sync
before insert on public.review_items
for each row execute function public.sync_review_item_original_text();

revoke all on function public.sync_review_item_original_text() from public, anon, authenticated;
