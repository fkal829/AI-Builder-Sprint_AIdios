from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "supabase"
    / "migrations"
    / "20260730260000_add_renewal_decisions.sql"
)


def test_renewal_decision_migration_is_owner_scoped_and_atomic() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8").lower()

    assert "contract_id uuid primary key" in sql
    assert "alter table public.renewal_decisions enable row level security" in sql
    assert "contract.owner_id = auth.uid()" in sql
    assert "contract.owner_id = p_owner_id" in sql
    assert "for update;" in sql
    assert "save_renewal_decision_with_audit" in sql
    assert "insert into public.renewal_decisions" in sql
    assert "insert into public.audit_events" in sql
    assert "'renewal_decision_saved'" in sql
    assert "to service_role;" in sql


def test_renewal_decision_migration_enforces_windows_and_idempotency() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8").lower()

    assert "v_expiry_d_day between 0 and 30" in sql
    assert "v_termination_notice_d_day between 0 and 14" in sql
    assert "v_auto_renewal_d_day between 0 and 7" in sql
    assert "'outcome', 'outside_review_window'" in sql
    assert "v_existing.decision = p_decision" in sql
    assert "'outcome', 'unchanged'" in sql
    unchanged_position = sql.index("'outcome', 'unchanged'")
    audit_position = sql.index("insert into public.audit_events")
    assert unchanged_position < audit_position


def test_renewal_decision_migration_collects_only_revisit_candidates() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8").lower()

    assert "p_decision = 'renew_with_changes'" in sql
    assert "item.status = 'kept_original'" in sql
    assert "response.decision = 'reject'" in sql
    assert "array_agg(distinct item.id order by item.id)" in sql
    assert "or cardinality(revisit_review_item_ids) = 0" in sql
    assert "update public.contracts" not in sql
