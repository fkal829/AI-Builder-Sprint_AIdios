import re
from pathlib import Path

from app.core.enums import AuditEventType, PerformanceReportStatus
from app.schemas.documents import DocumentType

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260801010000_add_performance_report_foundation.sql"
)


def _constraint_values(sql: str, constraint_name: str, column_name: str) -> set[str]:
    constraint = re.search(
        rf"(?:add )?constraint {constraint_name}\s+check "
        rf"\(\s*{column_name} in \((?P<values>.*?)\)\s*\)",
        sql,
        flags=re.DOTALL,
    )
    assert constraint is not None
    return set(re.findall(r"'([A-Z][A-Z_]+)'", constraint["values"]))


def test_performance_report_migration_extends_the_persisted_document_contract() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    persisted_document_types = _constraint_values(
        sql,
        "documents_type_check",
        "type",
    )

    assert persisted_document_types == {document_type.value for document_type in DocumentType}
    assert "drop constraint if exists documents_type_check" in sql
    assert "documents_contract_id_id_key unique (contract_id, id)" in sql
    assert "documents_performance_report_content_type_check" in sql
    assert "content_type in ('application/pdf', 'image/png', 'image/jpeg')" in sql


def test_performance_report_migration_blocks_the_generic_document_rpc() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "rename to create_contract_document_with_audit_legacy" in sql
    assert "p_document_type = 'PERFORMANCE_REPORT'" in sql
    assert "documents_performance_report_dedicated_upload_check" in sql
    assert "from public, anon, authenticated, service_role" in sql
    assert "grant execute on function public.create_document_with_audit" in sql


def test_performance_report_migration_persists_the_public_audit_events() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    persisted_event_types = _constraint_values(
        sql,
        "audit_events_event_type_check",
        "event_type",
    )

    assert persisted_event_types == {event.value for event in AuditEventType}


def test_performance_report_migration_creates_only_the_base_report_identity() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "create table public.performance_reports" in sql
    for column in (
        "id uuid primary key",
        "contract_id uuid not null references public.contracts(id) on delete cascade",
        "period text not null",
        "source_document_id uuid not null",
        "status text not null default 'UPLOADED'",
        "extracted_payload jsonb",
        "current_revision_id uuid",
        "revision_count integer not null default 0",
        "extraction_attempt_id uuid",
        "extraction_started_at timestamptz",
        "created_at timestamptz not null default now()",
        "updated_at timestamptz not null default now()",
    ):
        assert column in sql

    for deferred_table in (
        "performance_report_revisions",
        "performance_flags",
        "performance_flag_basis_terms",
        "performance_inquiry_drafts",
    ):
        assert f"create table public.{deferred_table}" not in sql


def test_performance_report_migration_enforces_period_status_and_attempt_invariants() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    persisted_statuses = _constraint_values(
        sql,
        "performance_reports_status_check",
        "status",
    )

    assert persisted_statuses == {status.value for status in PerformanceReportStatus}
    assert "check (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$')" in sql
    assert "performance_reports_contract_period_key unique (contract_id, period)" in sql
    assert "performance_reports_source_document_id_key unique (source_document_id)" in sql
    assert "(extraction_attempt_id is null) = (extraction_started_at is null)" in sql
    assert "status = 'UPLOADED' and extracted_payload is null" in sql
    assert "and extracted_payload is not null" in sql
    assert "jsonb_typeof(extracted_payload) = 'object'" in sql
    assert "performance_reports_revision_projection_check" in sql
    assert "current_revision_id is null" in sql
    assert "revision_count = 0" in sql
    assert "current_revision_id is not null" in sql
    assert "revision_count >= 1" in sql


def test_performance_report_migration_enforces_same_contract_and_document_type() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "foreign key (contract_id, source_document_id)" in sql
    assert "references public.documents (contract_id, id)" in sql
    assert "on delete restrict" in sql
    assert "function public.enforce_performance_report_source_document()" in sql
    assert "type = 'PERFORMANCE_REPORT'" in sql
    assert "for key share" in sql
    assert "before insert or update of contract_id, source_document_id" in sql
    assert "function public.protect_performance_report_source_document()" in sql
    assert "before update of contract_id, type on public.documents" in sql


def test_performance_report_migration_limits_writes_to_allowed_contract_states() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "function public.enforce_performance_report_contract_status()" in sql
    assert "status in ('SIGNED', 'IN_PROGRESS', 'RENEWAL_DUE', 'COMPLETED')" in sql
    assert "before insert or update on public.performance_reports" in sql
    assert "performance_reports_contract_status_check" in sql


def test_performance_report_migration_keeps_direct_table_access_private() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "alter table public.performance_reports enable row level security" in sql
    assert "create policy performance_reports_owner_select" in sql
    assert "contracts.owner_id = auth.uid()" in sql
    assert "revoke all on table public.performance_reports from anon, authenticated" in sql
    assert (
        "grant select, insert, update on table public.performance_reports to service_role"
    ) in sql
    assert "grant select, insert, update, delete" not in sql
    for function_name in (
        "enforce_performance_report_contract_status",
        "enforce_performance_report_source_document",
        "protect_performance_report_source_document",
    ):
        assert f"revoke all on function public.{function_name}()" in sql
