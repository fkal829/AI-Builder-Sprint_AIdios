from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260730280000_add_signature_requests.sql"
)


def test_signature_migration_has_private_attempts_and_atomic_rpcs() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "create table public.signatures" in sql
    assert "alter table public.signatures enable row level security" in sql
    assert "signatures_one_active_attempt_per_contract_idx" in sql
    for rpc in (
        "prepare_embedded_signature_draft",
        "complete_embedded_signature_draft",
        "fail_embedded_signature_draft",
        "get_latest_owned_signature",
    ):
        assert f"function public.{rpc}" in sql
    assert "SIGNATURE_DRAFT_CREATED" in sql
    assert "SIGNATURE_FAILED" in sql
    assert "modusign_document_id text unique" in sql
    assert "modusign_draft_id text unique" in sql


def test_webhook_migration_has_deduplication_and_atomic_reconciliation() -> None:
    migration = MIGRATION.with_name("20260730300000_add_modusign_webhook_reconciliation.sql")
    sql = migration.read_text(encoding="utf-8")

    assert "create table public.modusign_webhook_events" in sql
    assert "deduplication_key text not null unique" in sql
    assert "record_modusign_webhook_event" in sql
    assert "apply_modusign_document_status" in sql
    assert "SIGNATURE_COMPLETED" in sql
