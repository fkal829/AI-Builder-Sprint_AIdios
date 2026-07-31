from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260730200000_add_analysis_pipeline.sql"
)


def test_analysis_migration_contains_atomic_pipeline_foundation() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for table in ("analysis_tasks", "extracted_terms", "review_items", "obligations"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql

    for rpc in (
        "start_analysis_with_audit",
        "mark_analysis_processing",
        "complete_analysis_result_with_audit",
        "fail_analysis_with_audit",
    ):
        assert f"function public.{rpc}" in sql

    assert "ANALYSIS_STARTED" in sql
    assert "ANALYSIS_RESTARTED" in sql
    assert "ANALYSIS_COMPLETED" in sql
    assert "ANALYSIS_FAILED" in sql
    assert "OBLIGATION_CREATED" in sql


def test_analysis_migration_preserves_json_null_and_canonical_guards() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "nullif(item -> 'value', 'null'::jsonb)" in sql
    assert "source_type = 'CONTRACT_DOCUMENT'" in sql
    assert "verification_status = 'VERIFIED'" in sql
    assert "signed_date = coalesce(" in sql
    assert "total_amount = coalesce(" in sql
    assert "on conflict (contract_id) do nothing" in sql


def test_analysis_migration_creates_one_evidence_backed_obligation_atomically() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "contract_id uuid not null unique" in sql
    assert "field = 'deliverable_due_date'" in sql
    assert "value_type = 'DATE'" in sql
    assert "source_type = 'CONTRACT_DOCUMENT'" in sql
    assert "document_id = due.document_id" in sql
    assert "source_page = due.source_page" in sql
    assert "source_text = due.source_text" in sql
    assert "field in ('advertising_channel', 'content_type', 'content_quantity')" in sql
    assert "least(" in sql
    assert "get diagnostics v_obligation_created = row_count" in sql
    assert "if v_obligation_created = 1 then" in sql
