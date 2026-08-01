from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260802010000_add_user_selected_adjustment_items.sql"
)


def test_user_selected_adjustment_migration_preserves_server_evidence() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "origin in ('analysis', 'user_selected')" in sql
    assert "document_clause_id uuid" in sql
    assert "analysis.result->'document_clauses'" in sql
    assert "create or replace function public.enforce_review_item_evidence_links" in sql
    assert "new.origin = 'user_selected'" in sql
    assert "user-selected review item must match a document clause" in sql
    assert "analysis.document_id = (clause->>'document_id')::uuid" in sql
    assert "manual.source_page" in sql
    assert "manual.source_text" in sql
    assert "manual.source_confidence" in sql
    assert "related_extracted_term_ids" in sql
    assert "'{}'::uuid[]" in sql


def test_user_selected_adjustment_migration_creates_exact_validated_copy_atomically() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "create function public.create_adjustment_draft_with_audit" in sql
    assert "jsonb_to_recordset(p_items)" in sql
    assert "jsonb_to_recordset(p_manual_items)" in sql
    assert "btrim(requested.request_text)" in sql
    assert "insert into public.adjustment_requests" in sql
    assert "insert into public.adjustment_request_items" in sql
    assert "insert into public.audit_events" in sql
    assert "to service_role" in sql
