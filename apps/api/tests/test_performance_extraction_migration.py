from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260801020000_add_performance_report_extraction_workflow.sql"
)


def test_extraction_rpcs_lock_owned_report_and_source_document() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for function_name in (
        "claim_performance_report_extraction",
        "complete_performance_report_extraction",
        "fail_performance_report_extraction",
    ):
        body = sql.split(f"create function public.{function_name}", maxsplit=1)[1]
        body = body.split("$$;", maxsplit=1)[0]
        assert "security definer" in body
        assert "set search_path = ''" in body
        assert "contract.owner_id = p_owner_id" in body
        assert "report.contract_id = p_contract_id" in body
        assert "document.contract_id = p_contract_id" in body
        assert "document.type = 'PERFORMANCE_REPORT'" in body
        assert body.count("for update;") == 3


def test_claim_has_exact_stale_boundary_and_idempotent_response_loss_recovery() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = sql.split(
        "create function public.claim_performance_report_extraction",
        maxsplit=1,
    )[1].split("$$;", maxsplit=1)[0]

    same_attempt = "v_report.extraction_attempt_id = p_attempt_id"
    active_attempt = "v_report.extraction_started_at > p_stale_before"
    assert body.index(same_attempt) < body.index(active_attempt)
    assert "p_attempt_id <> p_idempotency_key" in body
    assert "p_started_at < v_report.created_at" in body
    assert "p_started_at < v_report.updated_at" in body
    assert "'outcome', 'CLAIMED'" in body
    assert "'outcome', 'IN_PROGRESS'" in body
    assert "case when v_recovered then 'RECOVERED' else 'CLAIMED' end" in body
    assert "idempotency_key <> p_idempotency_key" in body
    assert "operation = 'PERFORMANCE_REPORT_EXTRACT'" in body
    assert "response_status is null" in body
    assert "PERFORMANCE_REPORT_EXTRACTION_RECOVERED" in body


def test_completion_applies_only_the_current_attempt_atomically() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = sql.split(
        "create function public.complete_performance_report_extraction",
        maxsplit=1,
    )[1].split("$$;", maxsplit=1)[0]

    assert "v_report.extraction_attempt_id is distinct from p_attempt_id" in body
    assert "return jsonb_build_object('outcome', 'STALE')" in body
    assert "set parse_status = 'COMPLETED'" in body
    assert "set status = 'EXTRACTED'" in body
    assert "extracted_payload = p_extracted_payload" in body
    assert "and extraction_attempt_id = p_attempt_id" in body
    assert "PERFORMANCE_REPORT_EXTRACTED" in body
    assert "'outcome', 'APPLIED'" in body


def test_failure_keeps_uploaded_and_distinguishes_parse_from_mapping() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    body = sql.split(
        "create function public.fail_performance_report_extraction",
        maxsplit=1,
    )[1].split("$$;", maxsplit=1)[0]

    assert "p_document_parse_status not in ('FAILED', 'COMPLETED')" in body
    assert "v_report.extraction_attempt_id is distinct from p_attempt_id" in body
    assert "set parse_status = p_document_parse_status" in body
    assert "set status = 'UPLOADED'" in body
    assert "extracted_payload = null" in body
    assert "current_revision_id = null" in body
    assert "revision_count = 0" in body
    assert "and extraction_attempt_id = p_attempt_id" in body
    assert "PERFORMANCE_REPORT_EXTRACTED" not in body


def test_extraction_rpcs_are_service_role_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "revoke update on table public.performance_reports from service_role" in sql
    for function_name in (
        "claim_performance_report_extraction",
        "complete_performance_report_extraction",
        "fail_performance_report_extraction",
    ):
        assert f"revoke all on function public.{function_name}(" in sql
        grant = sql.split(
            f"grant execute on function public.{function_name}(",
            maxsplit=1,
        )[1].split(";", maxsplit=1)[0]
        assert ") to service_role" in grant
