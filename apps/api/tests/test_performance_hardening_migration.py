from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PREVIOUS_MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260801050000_add_performance_report_atomic_snapshots.sql"
)
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260801060000_harden_performance_basis_and_period.sql"
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


def _function_arguments(sql: str, function_name: str) -> str:
    definition = _function_definition(sql, function_name)
    return " ".join(definition.split(")\nreturns", maxsplit=1)[0].split())


def test_hardening_migration_replaces_the_applied_rpc_without_changing_its_signature() -> None:
    previous_sql = PREVIOUS_MIGRATION.read_text(encoding="utf-8")
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "create or replace function public.confirm_performance_report_with_audit(" in sql
    assert _function_arguments(sql, "confirm_performance_report_with_audit") == _function_arguments(
        previous_sql, "confirm_performance_report_with_audit"
    )
    assert "drop function public.confirm_performance_report_with_audit" not in sql


def test_basis_trigger_requires_an_exact_verified_same_contract_source_snapshot() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = _function_definition(sql, "enforce_performance_flag_basis_term_snapshot")

    assert "set search_path = ''" in body
    assert "security definer" not in body
    for table in (
        "public.performance_flags",
        "public.performance_report_revisions",
        "public.performance_reports",
        "public.extracted_terms",
        "public.analysis_tasks",
        "public.documents",
    ):
        assert table in body
    for exact_match in (
        "term.contract_id = report.contract_id",
        "task.contract_id = report.contract_id",
        "document.contract_id = report.contract_id",
        "term.document_id is not distinct from new.document_id",
        "term.field is not distinct from new.field",
        "term.source_type is not distinct from new.source_type",
        "term.source_page is not distinct from new.source_page",
        "term.source_text is not distinct from new.source_text",
        "term.confidence is not distinct from new.confidence",
        "term.verification_status is not distinct from new.verification_status",
        "term.source_type = 'CONTRACT_DOCUMENT'",
        "term.verification_status = 'VERIFIED'",
    ):
        assert exact_match in body
    assert "errcode = '23514'" in body
    assert "performance_flag_basis_terms_same_contract_verified_check" in body


def test_basis_trigger_is_installed_before_existing_rows_are_prevalidated() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    trigger_position = sql.index(
        "create trigger performance_flag_basis_terms_same_contract_verified_guard"
    )
    prevalidation_position = sql.index("do $$", trigger_position)
    prevalidation = sql[prevalidation_position : sql.index("$$;", prevalidation_position)]

    assert trigger_position < prevalidation_position
    assert "before insert or update" in sql[trigger_position:prevalidation_position]
    assert "where not exists (" in prevalidation
    for exact_match in (
        "term.contract_id = report.contract_id",
        "task.contract_id = report.contract_id",
        "document.contract_id = report.contract_id",
        "term.document_id is not distinct from basis.document_id",
        "term.field is not distinct from basis.field",
        "term.source_type is not distinct from basis.source_type",
        "term.source_page is not distinct from basis.source_page",
        "term.source_text is not distinct from basis.source_text",
        "term.confidence is not distinct from basis.confidence",
        "term.verification_status is not distinct from basis.verification_status",
        "term.source_type = 'CONTRACT_DOCUMENT'",
        "term.verification_status = 'VERIFIED'",
    ):
        assert exact_match in prevalidation
    assert "performance_flag_basis_terms_same_contract_verified_check" in prevalidation
    assert "revoke all on function public.enforce_performance_flag_basis_term_snapshot()" in sql
    assert "from public, anon, authenticated, service_role;" in sql


def test_period_constraint_rejects_year_zero_and_validates_existing_rows() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "add constraint performance_reports_period_ad_year_check" in sql
    assert "substring(period from 1 for 4) <> '0000'" in sql
    assert "not valid;" in sql
    assert "validate constraint performance_reports_period_ad_year_check;" in sql


def test_confirmation_rpc_calculates_previous_period_without_date_or_bc_conversion() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = _function_definition(sql, "confirm_performance_report_with_audit")

    assert "v_period_year integer;" in body
    assert "v_period_month integer;" in body
    assert "substring(v_report.period from 1 for 4)::integer" in body
    assert "substring(v_report.period from 6 for 2)::integer" in body
    assert "if v_period_month > 1 then" in body
    assert "elsif v_period_year > 1 then" in body
    assert "v_previous_period := null;" in body
    assert "if v_previous_period is not null then" in body
    assert "to_date(" not in body
    assert "interval '1 month'" not in body


def test_confirmation_rpc_distinguishes_contract_and_report_invalid_status() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = _function_definition(sql, "confirm_performance_report_with_audit")

    assert "'outcome', 'CONTRACT_INVALID_STATUS'" in body
    assert "'outcome', 'REPORT_INVALID_STATUS'" in body
    assert "'outcome', 'INVALID_STATUS'" not in body
    assert body.index("from public.contracts as contract") < body.index(
        "from public.performance_reports as report"
    )
    assert body.count("for update;") == 2
    assert "security definer" in body
    assert "set search_path = ''" in body
    assert "grant execute on function public.confirm_performance_report_with_audit(" in sql
    assert ") to service_role;" in sql
