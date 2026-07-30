from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "supabase"
    / "migrations"
    / "20260730240000_add_review_item_selection.sql"
)


def test_review_item_selection_migration_is_atomic_and_owner_scoped() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8").lower()

    assert "update_review_item_selection_with_audit" in sql
    assert "contract.owner_id = p_owner_id" in sql
    assert "for update of item" in sql
    assert "v_item.status not in ('unreviewed', 'selected')" in sql
    assert "'accept' then 'resolved'" in sql
    assert "else 'selected'" in sql
    assert "review_item_selection_updated" in sql
    assert "insert into public.audit_events" in sql


def test_review_item_selection_migration_preserves_idempotency_and_result_mirror() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8").lower()

    assert "outcome', 'unchanged'" in sql
    assert "user_choice is not distinct from p_user_choice" in sql
    assert "update public.analysis_tasks" in sql
    assert "task.result -> 'review_items'" in sql
    assert "grant execute on function public.update_review_item_selection_with_audit" in sql
