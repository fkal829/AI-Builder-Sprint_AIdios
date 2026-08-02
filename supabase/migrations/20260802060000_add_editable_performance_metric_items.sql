-- P2 16.3 / 16.4 contract-first guard for editable performance metric items.
-- Legacy revisions without metric_items remain valid. Existing append-only
-- revision rows and confirmation RPCs are intentionally not updated.

create function public.is_valid_performance_metric_items(p_confirmed_payload jsonb)
returns boolean
language plpgsql
immutable
set search_path = ''
as $$
declare
    v_items jsonb;
    v_item jsonb;
    v_key text;
    v_label text;
    v_normalized_label text;
    v_unit text;
    v_value numeric;
    v_expected_unit text;
    v_seen_keys text[] := array[]::text[];
    v_seen_labels text[] := array[]::text[];
begin
    if jsonb_typeof(p_confirmed_payload) is distinct from 'object' then
        return false;
    end if;

    -- Do not rewrite immutable historical revisions merely to add an empty array.
    if not (p_confirmed_payload ? 'metric_items') then
        return true;
    end if;

    v_items := p_confirmed_payload -> 'metric_items';
    if jsonb_typeof(v_items) is distinct from 'array' then
        return false;
    end if;
    if jsonb_array_length(v_items) > 50 then
        return false;
    end if;

    for v_item in
        select item
        from jsonb_array_elements(v_items) as items(item)
    loop
        if jsonb_typeof(v_item) is distinct from 'object'
           or not (v_item ?& array['key', 'label', 'value', 'unit'])
           or (select count(*) from jsonb_object_keys(v_item)) <> 4 then
            return false;
        end if;
        if jsonb_typeof(v_item -> 'key') is distinct from 'string'
           or jsonb_typeof(v_item -> 'label') is distinct from 'string'
           or jsonb_typeof(v_item -> 'unit') is distinct from 'string'
           or jsonb_typeof(v_item -> 'value') not in ('number', 'null') then
            return false;
        end if;

        v_key := v_item ->> 'key';
        v_label := v_item ->> 'label';
        v_normalized_label := lower(v_label);
        v_unit := v_item ->> 'unit';

        if char_length(v_key) not between 1 and 64
           or v_key !~ '^[a-z][a-z0-9]*(_[a-z0-9]+)*$'
           or char_length(v_label) not between 1 and 50
           or v_label is distinct from btrim(v_label)
           or v_label ~ '^[[:space:]]'
           or v_label ~ '[[:space:]]$'
           or v_label ~ '[[:cntrl:]]'
           or v_unit not in ('KRW', 'COUNT', 'PERCENT', 'NUMBER') then
            return false;
        end if;

        if v_key = any(v_seen_keys) or v_normalized_label = any(v_seen_labels) then
            return false;
        end if;
        v_seen_keys := array_append(v_seen_keys, v_key);
        v_seen_labels := array_append(v_seen_labels, v_normalized_label);

        if jsonb_typeof(v_item -> 'value') = 'number' then
            v_value := (v_item ->> 'value')::numeric;
            if v_value < 0
               or scale(v_value) > 6
               or (v_unit in ('KRW', 'COUNT') and v_value <> trunc(v_value)) then
                return false;
            end if;
        end if;

        v_expected_unit := case v_key
            when 'ad_spend' then 'KRW'
            when 'impressions' then 'COUNT'
            when 'clicks' then 'COUNT'
            when 'ctr' then 'PERCENT'
            when 'cpc' then 'KRW'
            when 'published_content_count' then 'COUNT'
            else null
        end;
        if v_expected_unit is not null and v_unit is distinct from v_expected_unit then
            return false;
        end if;
    end loop;

    return true;
end;
$$;

revoke all on function public.is_valid_performance_metric_items(jsonb)
    from public, anon, authenticated;
grant execute on function public.is_valid_performance_metric_items(jsonb)
    to service_role;

alter table public.performance_report_revisions
    add constraint performance_report_revisions_metric_items_check
    check (public.is_valid_performance_metric_items(confirmed_payload))
    not valid;

alter table public.performance_report_revisions
    validate constraint performance_report_revisions_metric_items_check;
