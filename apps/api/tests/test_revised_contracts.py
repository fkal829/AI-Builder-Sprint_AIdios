from pathlib import Path

from app.adapters.base import ParsedDocument, ParsedPage
from app.services.revised_contracts import _find_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260731010000_add_revised_contract_verification.sql"
)


def test_exact_revision_evidence_is_deterministic_and_page_backed() -> None:
    parsed = ParsedDocument(
        pages=(
            ParsedPage(number=1, text="기존 조건"),
            ParsedPage(number=2, text="계약 기간은 1년으로 조정한다."),
        ),
        model="test-parser",
    )

    assert _find_evidence(parsed, "계약기간은 1년으로 조정한다.") == (
        2,
        "계약 기간은 1년으로 조정한다.",
    )
    assert _find_evidence(parsed, "계약 기간은 6개월로 조정한다.") is None


def test_revision_migration_is_additive_and_binds_signatures_to_document_hash() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "create table public.revised_contract_reviews" in sql
    assert "'REVISED_CONTRACT'" in sql
    assert "add column revised_contract_review_id" in sql
    assert "add column document_sha256" in sql
    assert "alter table public.agreements" not in sql
    assert "drop table" not in sql.lower()
