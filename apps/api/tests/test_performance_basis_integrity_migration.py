from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260801070000_enforce_performance_basis_integrity.sql"
)
EXECUTION_FIX_MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260801080000_fix_deferred_basis_trigger_execution.sql"
)


def _function_definition(sql: str, function_name: str) -> str:
    markers = (
        f"create or replace function public.{function_name}",
        f"create function public.{function_name}",
    )
    for marker in markers:
        if marker in sql:
            return sql.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]
    raise AssertionError(f"missing function: {function_name}")


def test_snapshot_validation_locks_the_source_and_terms_are_append_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    snapshot = _function_definition(sql, "enforce_performance_flag_basis_term_snapshot")
    mutation = _function_definition(sql, "prevent_extracted_term_update")

    assert "for share of term;" in snapshot
    assert "set search_path = ''" in snapshot
    assert "append-only and cannot be updated" in mutation
    assert "extracted_terms_append_only" in mutation
    assert "extracted_terms_append_only_guard" in sql
    assert "before update" in sql
    assert "before update or delete" not in sql
    assert (
        "revoke update, delete, truncate on table public.extracted_terms from service_role;"
    ) in sql


def test_deferred_constraint_requires_exact_shortfall_basis_shape() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assertion = _function_definition(sql, "assert_performance_flag_basis_complete")

    assert "v_flag_type = 'DELIVERABLE_COUNT_SHORTFALL'" in assertion
    assert "v_basis_count <> 2" in assertion
    assert "v_quantity_count <> 1" in assertion
    assert "v_frequency_count <> 1" in assertion
    assert "elsif v_basis_count <> 0" in assertion
    assert "performance_flags_basis_completeness_check" in assertion
    for trigger in (
        "performance_flags_basis_completeness_guard",
        "performance_flag_basis_terms_completeness_guard",
    ):
        trigger_position = sql.index(f"create constraint trigger {trigger}")
        trigger_sql = sql[trigger_position : trigger_position + 360]
        assert "deferrable initially deferred" in trigger_sql
        assert "for each row" in trigger_sql


def test_existing_flags_and_snapshots_are_revalidated_without_repair() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    audit_position = sql.index("-- Abort instead of silently repairing")
    audit = sql[audit_position:]

    assert "for v_flag in select id from public.performance_flags loop" in audit
    assert "assert_performance_flag_basis_complete(v_flag.id)" in audit
    assert "where not exists (" in audit
    assert "term.contract_id = report.contract_id" in audit
    assert "term.source_text is not distinct from basis.source_text" in audit
    assert "term.verification_status = 'VERIFIED'" in audit
    assert "update public." not in audit
    assert "delete from public." not in audit


def test_internal_trigger_functions_are_not_directly_executable() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    for signature in (
        "public.enforce_performance_flag_basis_term_snapshot()",
        "public.prevent_extracted_term_update()",
        "public.assert_performance_flag_basis_complete(uuid)",
        "public.enforce_performance_flag_basis_completeness()",
    ):
        revoke = f"revoke all on function {signature}"
        position = sql.index(revoke)
        assert "from public, anon, authenticated, service_role;" in sql[position : position + 220]


def test_deferred_trigger_wrapper_runs_as_owner_without_becoming_public() -> None:
    sql = EXECUTION_FIX_MIGRATION.read_text(encoding="utf-8")

    assert (
        "alter function public.enforce_performance_flag_basis_completeness()\n    security definer;"
    ) in sql
    assert "revoke all on function public.enforce_performance_flag_basis_completeness()" in sql
    assert "from public, anon, authenticated, service_role;" in sql
    assert "grant execute" not in sql
