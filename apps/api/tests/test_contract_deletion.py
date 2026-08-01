from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260802020000_delete_discardable_contracts.sql"
)
OPENAPI = REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml"


def test_contract_deletion_migration_guards_external_lifecycle_boundaries() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "function public.delete_discardable_contract" in sql
    assert "for update" in sql
    assert "request.status <> 'DRAFT'" in sql
    assert "from public.signatures" in sql
    assert "v_status not in ('DRAFT', 'ANALYZING', 'REVIEW_REQUIRED', 'NEGOTIATING')" in sql
    assert "'outcome', 'PROTECTED'" in sql
    assert "delete from public.contracts" in sql
    assert sql.index("insert into public.contract_deletion_records") < sql.index(
        "delete from public.contracts"
    )


def test_contract_deletion_migration_removes_document_references_before_documents() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    document_delete = sql.index("delete from public.documents")
    for dependent_delete in (
        "delete from public.obligations",
        "delete from public.review_items",
        "delete from public.extracted_terms",
        "delete from public.analysis_tasks",
    ):
        assert sql.index(dependent_delete) < document_delete
    assert "storage_paths" in sql
    assert "function public.mark_contract_storage_cleaned" in sql


def test_openapi_documents_guarded_contract_deletion() -> None:
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    operation = spec["paths"]["/contracts/{contract_id}"]["delete"]

    assert operation["operationId"] == "deleteContract"
    assert set(operation["responses"]) == {"200", "401", "404", "409", "422"}
    schema = spec["components"]["schemas"]["ContractDeletion"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["deleted"]["const"] is True
