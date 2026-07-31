from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260730290000_add_rendered_agreement_pdf.sql"
)


def test_rendered_agreement_pdf_is_private_and_created_with_the_agreement() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "create table public.agreement_files" in sql
    assert "alter table public.agreement_files enable row level security" in sql
    assert "content_sha256" in sql
    assert "function public.create_rendered_agreement_with_audit" in sql
    assert "insert into public.agreements" in sql
    assert "insert into public.agreement_files" in sql
    assert "AGREEMENT_CREATED" in sql
