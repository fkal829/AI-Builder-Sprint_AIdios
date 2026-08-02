from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260802060000_add_editable_performance_metric_items.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_metric_item_guard_is_immutable_and_legacy_compatible() -> None:
    sql = migration_sql()

    assert "create function public.is_valid_performance_metric_items" in sql
    assert "returns boolean\nlanguage plpgsql\nimmutable" in sql
    assert "set search_path = ''" in sql
    assert "if not (p_confirmed_payload ? 'metric_items') then\n        return true;" in sql
    assert "jsonb_array_length(v_items) > 50" in sql
    assert "not valid;" in sql
    assert "validate constraint performance_report_revisions_metric_items_check" in sql


def test_metric_item_guard_enforces_shape_identity_units_and_numbers() -> None:
    sql = migration_sql()

    assert "v_item ?& array['key', 'label', 'value', 'unit']" in sql
    assert "jsonb_object_keys(v_item)) <> 4" in sql
    assert "^[a-z][a-z0-9]*(_[a-z0-9]+)*$" in sql
    assert "char_length(v_label) not between 1 and 50" in sql
    assert "v_label is distinct from btrim(v_label)" in sql
    assert "v_label ~ '^[[:space:]]'" in sql
    assert "v_label ~ '[[:space:]]$'" in sql
    assert "v_label ~ '[[:cntrl:]]'" in sql
    assert "v_key = any(v_seen_keys)" in sql
    assert "v_normalized_label = any(v_seen_labels)" in sql
    assert "lower(v_label)" in sql
    assert "scale(v_value) > 6" in sql
    assert "v_unit in ('KRW', 'COUNT') and v_value <> trunc(v_value)" in sql
    for key, unit in (
        ("ad_spend", "KRW"),
        ("impressions", "COUNT"),
        ("clicks", "COUNT"),
        ("ctr", "PERCENT"),
        ("cpc", "KRW"),
        ("published_content_count", "COUNT"),
    ):
        assert f"when '{key}' then '{unit}'" in sql


def test_metric_item_guard_is_callable_by_the_only_dml_role_without_rpc_replacement() -> None:
    sql = migration_sql()

    assert "from public, anon, authenticated;" in sql
    assert "grant execute on function public.is_valid_performance_metric_items(jsonb)" in sql
    assert "to service_role;" in sql
    assert "update public.performance_report_revisions" not in sql.lower()
    assert "create or replace function public.confirm_performance_report_with_audit" not in sql
    assert "drop function public.confirm_performance_report_with_audit" not in sql
