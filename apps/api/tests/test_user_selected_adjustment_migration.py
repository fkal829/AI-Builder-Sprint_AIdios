from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260802010000_add_user_selected_adjustment_items.sql"
)
ORDINALITY_FIX_MIGRATION = MIGRATION.with_name(
    "20260802030000_fix_adjustment_draft_ordinality.sql"
)
UNLIMITED_ITEMS_MIGRATION = MIGRATION.with_name(
    "20260802040000_remove_adjustment_item_count_limit.sql"
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


def test_adjustment_draft_ordinality_fix_replaces_the_rpc_with_valid_rows_from_syntax() -> None:
    sql = ORDINALITY_FIX_MIGRATION.read_text(encoding="utf-8").lower()

    assert "create or replace function public.create_adjustment_draft_with_audit" in sql
    assert "from rows from (" in sql
    assert ") with ordinality as requested(" in sql
    assert "jsonb_to_recordset(p_items) with ordinality" not in sql
    assert "order by requested.position" in sql
    assert "insert into public.adjustment_requests" in sql
    assert "insert into public.adjustment_request_items" in sql
    assert "insert into public.audit_events" in sql
    assert "to service_role" in sql


def test_adjustment_item_limit_migration_preserves_nonempty_atomic_flow() -> None:
    sql = UNLIMITED_ITEMS_MIGRATION.read_text(encoding="utf-8").lower()

    assert "create or replace function public.create_adjustment_draft_with_audit" in sql
    assert "if v_item_count < 1 or v_manual_count > v_item_count then" in sql
    assert "v_item_count not between 1 and 4" not in sql
    assert "from rows from (" in sql
    assert "order by requested.position" in sql
    assert "insert into public.adjustment_requests" in sql
    assert "insert into public.adjustment_request_items" in sql
    assert "insert into public.audit_events" in sql
    assert "pg_get_constraintdef(con.oid) like '%jsonb_array_length(items)%'" in sql
    assert "jsonb_array_length(items) >= 1" in sql
    assert "jsonb_array_length(items) between 1 and 4" not in sql
    assert "to service_role" in sql
