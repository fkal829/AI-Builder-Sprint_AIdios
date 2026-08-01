from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260801050000_add_performance_report_atomic_snapshots.sql"
)


def _function_body(sql: str, function_name: str) -> str:
    return sql.split(f"create function public.{function_name}", maxsplit=1)[1].split(
        "$$;", maxsplit=1
    )[0]


def test_confirmation_rpc_serializes_contract_and_validates_comparison_revision() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = _function_body(sql, "confirm_performance_report_with_audit")

    assert "p_expected_comparison_revision_id uuid" in body
    contract_lock = "from public.contracts as contract"
    report_lock = "from public.performance_reports as report"
    assert body.index(contract_lock) < body.index(report_lock)
    assert body.count("for update;") == 2
    assert "v_current_comparison_revision_id is distinct from" in body
    assert "p_expected_comparison_revision_id" in body
    assert "'outcome', 'COMPARISON_REVISION_CONFLICT'" in body
    assert "'outcome', 'PERIOD_ORDER_CONFLICT'" in body
    assert "'outcome', 'CORRECTION_DEPENDENCY_EXISTS'" in body


def test_confirmation_rpc_returns_the_complete_snapshot_before_unlock() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = _function_body(sql, "confirm_performance_report_with_audit")

    audit_insert = body.index("insert into public.audit_events")
    snapshot_select = body.index("select jsonb_build_object(", audit_insert)
    returned_snapshot = body.index("'report_snapshot', v_snapshot")
    assert audit_insert < snapshot_select < returned_snapshot
    for key in (
        "'report', to_jsonb(report)",
        "'revisions'",
        "'flags'",
        "'basis_terms'",
        "'inquiry_drafts'",
    ):
        assert key in body[snapshot_select:returned_snapshot]
    assert "return jsonb_build_object(\n        'outcome', 'CONFIRMED'" in body


def test_owner_snapshot_rpc_is_one_security_definer_sql_statement() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = _function_body(sql, "get_owned_contract_performance_snapshot")

    assert "language sql" in body
    assert "stable" in body
    assert "security definer" in body
    assert "contract.owner_id = p_owner_id" in body
    assert "report.contract_id = contract.id" in body
    assert "'outcome', 'FOUND'" in body
    assert "'outcome', 'NOT_FOUND'" in body
    assert "'report_snapshots'" in body
    for table in (
        "performance_report_revisions",
        "performance_flags",
        "performance_flag_basis_terms",
        "performance_inquiry_drafts",
    ):
        assert f"public.{table}" in body


def test_snapshot_migration_removes_direct_child_writes_and_old_rpc_signature() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "revoke insert on table public.performance_report_revisions" in sql
    assert "public.performance_inquiry_drafts\n    from service_role" in sql
    assert "drop function public.confirm_performance_report_with_audit(" in sql
    assert "grant execute on function public.confirm_performance_report_with_audit(" in sql
    assert "grant execute on function public.get_owned_contract_performance_snapshot" in sql
    assert "to service_role;" in sql


def test_snapshot_migration_uses_bigint_counts_and_sufficient_rate_precision() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "alter column expected_content_count type bigint" in sql
    assert "alter column actual_content_count type bigint" in sql
    assert sql.count("type numeric(26, 6)") == 3
    assert "nullif(item ->> 'expected_content_count', '')::bigint" in sql
    assert "nullif(item ->> 'actual_content_count', '')::bigint" in sql
