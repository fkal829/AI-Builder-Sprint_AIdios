from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = REPOSITORY_ROOT / "supabase" / "migrations"
REPRESENTATIVE_OBLIGATION_GUARD = (
    MIGRATIONS / "20260730330002_enforce_representative_obligation_evidence.sql"
)
REVIEW_ITEM_EVIDENCE_GUARD = MIGRATIONS / "20260730330005_enforce_review_item_evidence_links.sql"


def test_supabase_migration_versions_are_unique() -> None:
    versions = [path.name.split("_", 1)[0] for path in MIGRATIONS.glob("*.sql")]
    duplicates = sorted(
        version for version, occurrence_count in Counter(versions).items() if occurrence_count > 1
    )

    assert not duplicates, f"Duplicate Supabase migration versions: {duplicates}"


def test_sql_requires_four_verified_fields_from_identical_evidence() -> None:
    sql = REPRESENTATIVE_OBLIGATION_GUARD.read_text(encoding="utf-8")

    assert "before insert on public.obligations" in sql.lower()
    assert "term.document_id = new.source_document_id" in sql
    assert "term.source_page = new.source_page" in sql
    assert "term.source_text = new.source_text" in sql
    assert "term.source_type = 'CONTRACT_DOCUMENT'" in sql
    assert "term.verification_status = 'VERIFIED'" in sql
    assert "having count(*) = 4" in sql
    for field in (
        "advertising_channel",
        "content_type",
        "content_quantity",
        "deliverable_due_date",
    ):
        assert f"where term.field = '{field}'" in sql
    assert "return null" in sql.lower()


def test_sql_enforces_review_item_links_against_same_analysis_result() -> None:
    sql = REVIEW_ITEM_EVIDENCE_GUARD.read_text(encoding="utf-8")

    assert "before insert or update on public.review_items" in sql.lower()
    assert "term.analysis_task_id = new.analysis_task_id" in sql
    assert "term.contract_id = new.contract_id" in sql
    assert "new.verification_status in ('VERIFIED', 'NEEDS_CHECK')" in sql
    assert "new.verification_status in ('NOT_FOUND', 'MISSING_EVIDENCE')" in sql
    assert "term.id = any(new.related_extracted_term_ids)" in sql
    assert "term.source_type = 'CONTRACT_DOCUMENT'" in sql
    assert "term.document_id = new.source_document_id" in sql
    assert "term.source_page = new.source_page" in sql
    assert "term.source_text = new.source_text" in sql
    assert "term.confidence = new.source_confidence" in sql
    assert "set updated_at = updated_at" in sql
