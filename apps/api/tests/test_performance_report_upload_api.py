import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import (
    get_performance_report_upload_service,
    get_supabase_adapter,
)
from app.core.enums import ContractStatus
from app.core.exceptions import ExternalStorageFailure
from app.main import app
from app.repositories.contracts import ContractRecord
from app.services.idempotency import IdempotencyService
from app.services.performance_upload import PerformanceReportUploadService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def make_pdf(*, pages: int = 1, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("performance-report-password")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def make_adapter(*, status: ContractStatus = ContractStatus.SIGNED) -> SupabaseAdapter:
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
        clock=lambda: NOW,
    )
    adapter._mock_contracts[CONTRACT_ID] = ContractRecord(
        id=CONTRACT_ID,
        owner_id=OWNER_ID,
        title="광고효과 리포트 업로드 계약",
        counterparty_name="부산홍보대행",
        status=status,
        signed_date=None,
        start_date=None,
        end_date=None,
        termination_notice_date=None,
        renewal_type=None,
        total_amount=None,
        understood_term=None,
        renewal_decision=None,
        modusign_document_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    return adapter


@pytest.fixture
async def upload_context(monkeypatch: pytest.MonkeyPatch):
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.services.documents.asyncio.to_thread", run_inline)
    adapter = make_adapter()
    service = PerformanceReportUploadService(
        access_repository=adapter,
        upload_repository=adapter,
        storage=adapter,
        idempotency=IdempotencyService(
            adapter,
            now=lambda: NOW,
            completion_retry_delay_seconds=0,
            pending_replay_delay_seconds=0,
        ),
        max_size_bytes=4096,
        max_pdf_pages=2,
        now=lambda: NOW,
    )

    async def override_adapter():
        return adapter

    async def override_service():
        return service

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_performance_report_upload_service] = override_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, adapter, service
    finally:
        app.dependency_overrides.clear()


def auth_headers(
    *,
    idempotency_key: UUID | str | None = None,
    token: str = BEARER_TOKEN,
) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)
    return headers


async def post_report(
    client: AsyncClient,
    *,
    key: UUID | str | None = None,
    contract_id: UUID = CONTRACT_ID,
    period: str = "2026-08",
    filename: str = "customer-secret-report.pdf",
    content: bytes | None = None,
    content_type: str = "application/pdf",
):
    return await client.post(
        f"/api/v1/contracts/{contract_id}/performance-reports",
        headers=auth_headers(idempotency_key=key or uuid4()),
        data={"period": period},
        files={
            "file": (
                filename,
                make_pdf() if content is None else content,
                content_type,
            )
        },
    )


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "extension"),
    [
        ("report.pdf", make_pdf(), "application/pdf", "pdf"),
        ("report.png", b"\x89PNG\r\n\x1a\nperformance", "image/png", "png"),
        ("report.jpeg", b"\xff\xd8\xffperformance", "image/jpeg", "jpg"),
    ],
)
async def test_uploads_each_supported_report_type_as_one_private_atomic_unit(
    upload_context,
    filename: str,
    content: bytes,
    content_type: str,
    extension: str,
) -> None:
    client, adapter, _service = upload_context
    original_status = adapter.mock_contracts[CONTRACT_ID].status

    response = await post_report(
        client,
        filename=filename,
        content=content,
        content_type=content_type,
    )

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["requestId"] == response.headers["X-Request-ID"]
    body = response.json()["data"]
    assert set(body) == {
        "id",
        "contract_id",
        "period",
        "source_document_id",
        "status",
        "extracted_payload",
        "current_revision",
        "revision_count",
        "revisions",
        "created_at",
        "updated_at",
    }
    assert body["contract_id"] == str(CONTRACT_ID)
    assert body["period"] == "2026-08"
    assert body["status"] == "UPLOADED"
    assert body["extracted_payload"] is None
    assert body["current_revision"] is None
    assert body["revision_count"] == 0
    assert body["revisions"] == []
    assert body["created_at"] == body["updated_at"]

    document_id = UUID(body["source_document_id"])
    report_id = UUID(body["id"])
    document = adapter.mock_documents[document_id]
    assert adapter.mock_performance_reports[report_id].source_document_id == document_id
    assert document.content_type == content_type
    assert document.storage_path.endswith(f"/source.{extension}")
    assert filename not in document.storage_path
    assert adapter.mock_objects == {document.storage_path: content}
    assert [event.event_type for event in adapter.mock_audit_events] == [
        "PERFORMANCE_REPORT_UPLOADED"
    ]
    assert adapter.mock_audit_events[0].payload == {}
    assert adapter.mock_contracts[CONTRACT_ID].status is original_status
    response_text = response.text
    assert filename not in response_text
    assert document.storage_path not in response_text


async def test_same_key_and_file_replays_without_duplicate_side_effects(upload_context) -> None:
    client, adapter, _service = upload_context
    key = uuid4()
    content = make_pdf()

    first = await post_report(client, key=key, content=content)
    replay = await post_report(client, key=key, content=content)

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert first.headers["X-Request-ID"] == replay.headers["X-Request-ID"]
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1
    assert len(adapter.mock_idempotency_records) == 1
    replay_text = repr(adapter.mock_idempotency_records[0].response_payload)
    assert "storage_path" not in replay_text
    assert "file_sha256" not in replay_text
    assert "customer-secret-report" not in replay_text


async def test_slow_concurrent_same_key_returns_the_single_winning_response(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context
    original = adapter.upload_private_object
    first_upload_started = asyncio.Event()
    release_first_upload = asyncio.Event()
    calls = 0

    async def delay_first_upload(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_upload_started.set()
            await release_first_upload.wait()
        await original(**kwargs)

    monkeypatch.setattr(adapter, "upload_private_object", delay_first_upload)
    key = uuid4()
    first_task = asyncio.create_task(post_report(client, key=key))
    await first_upload_started.wait()

    second = await post_report(client, key=key)
    release_first_upload.set()
    first = await first_task

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert first.headers["X-Request-ID"] == second.headers["X-Request-ID"]
    assert calls == 2
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


@pytest.mark.parametrize(
    ("changed_period", "changed_content"),
    [
        ("2026-09", None),
        ("2026-08", make_pdf(pages=2)),
    ],
)
async def test_same_key_with_changed_fingerprint_is_conflict_before_storage(
    upload_context,
    changed_period: str,
    changed_content: bytes | None,
) -> None:
    client, adapter, _service = upload_context
    key = uuid4()
    original_content = make_pdf()
    await post_report(client, key=key, content=original_content)

    conflict = await post_report(
        client,
        key=key,
        period=changed_period,
        content=changed_content or original_content,
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert conflict.headers["Cache-Control"] == "no-store"
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


async def test_different_key_for_existing_month_is_period_conflict_without_orphan(
    upload_context,
) -> None:
    client, adapter, _service = upload_context
    await post_report(client, key=uuid4())
    conflict_key = uuid4()

    conflict = await post_report(client, key=conflict_key)
    replay = await post_report(client, key=conflict_key)

    assert conflict.status_code == replay.status_code == 409
    assert replay.json() == conflict.json()
    assert replay.headers["X-Request-ID"] == conflict.headers["X-Request-ID"]
    assert conflict.json()["error"]["code"] == "REPORT_PERIOD_ALREADY_EXISTS"
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


async def test_concurrent_different_keys_create_exactly_one_monthly_report(
    upload_context,
) -> None:
    client, adapter, _service = upload_context

    first, second = await asyncio.gather(
        post_report(client, key=uuid4()),
        post_report(client, key=uuid4()),
    )

    assert sorted((first.status_code, second.status_code)) == [201, 409]
    conflict = first if first.status_code == 409 else second
    assert conflict.json()["error"]["code"] == "REPORT_PERIOD_ALREADY_EXISTS"
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


@pytest.mark.parametrize(
    "status",
    [
        ContractStatus.SIGNED,
        ContractStatus.IN_PROGRESS,
        ContractStatus.RENEWAL_DUE,
        ContractStatus.COMPLETED,
    ],
)
async def test_all_write_contract_statuses_are_accepted(upload_context, status) -> None:
    client, adapter, _service = upload_context
    adapter._mock_contracts[CONTRACT_ID] = replace(
        adapter.mock_contracts[CONTRACT_ID],
        status=status,
    )

    response = await post_report(client)

    assert response.status_code == 201
    assert adapter.mock_contracts[CONTRACT_ID].status is status


async def test_invalid_contract_status_is_409_without_storage(upload_context) -> None:
    client, adapter, _service = upload_context
    adapter._mock_contracts[CONTRACT_ID] = replace(
        adapter.mock_contracts[CONTRACT_ID],
        status=ContractStatus.DRAFT,
    )

    response = await post_report(client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert adapter.mock_objects == {}
    assert adapter.mock_performance_reports == {}


async def test_authentication_and_unknown_contract_are_hidden_without_side_effects(
    upload_context,
) -> None:
    client, adapter, _service = upload_context
    missing_auth = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/performance-reports",
        data={"period": "2026-08"},
        files={"file": ("report.pdf", make_pdf(), "application/pdf")},
    )
    wrong_auth = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/performance-reports",
        headers=auth_headers(idempotency_key=uuid4(), token="invalid-demo-token"),
        data={"period": "2026-08"},
        files={"file": ("report.pdf", make_pdf(), "application/pdf")},
    )
    unknown = await post_report(client, contract_id=uuid4())

    assert missing_auth.status_code == wrong_auth.status_code == 401
    assert unknown.status_code == 404
    for response in (missing_auth, wrong_auth, unknown):
        assert response.headers["Cache-Control"] == "no-store"
    assert adapter.mock_objects == {}
    assert adapter.mock_performance_reports == {}
    assert adapter.mock_idempotency_records == ()


@pytest.mark.parametrize(
    ("period", "content", "content_type"),
    [
        ("2026-13", make_pdf(), "application/pdf"),
        ("2026-8", make_pdf(), "application/pdf"),
        ("2026-08", b"plain report", "text/plain"),
        ("2026-08", b"not-a-pdf", "application/pdf"),
        ("2026-08", b"GIF89a", "image/gif"),
        ("2026-08", make_pdf(encrypted=True), "application/pdf"),
        ("2026-08", make_pdf(pages=3), "application/pdf"),
    ],
)
async def test_invalid_period_or_file_is_422_without_side_effects(
    upload_context,
    period: str,
    content: bytes,
    content_type: str,
) -> None:
    client, adapter, _service = upload_context

    response = await post_report(
        client,
        period=period,
        content=content,
        content_type=content_type,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["Cache-Control"] == "no-store"
    assert adapter.mock_objects == {}
    assert adapter.mock_documents == {}
    assert adapter.mock_idempotency_records == ()


async def test_empty_oversized_missing_and_duplicate_fields_are_rejected(upload_context) -> None:
    client, adapter, _service = upload_context
    path = f"/api/v1/contracts/{CONTRACT_ID}/performance-reports"
    headers = auth_headers(idempotency_key=uuid4())
    empty = await client.post(
        path,
        headers=headers,
        data={"period": "2026-08"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    oversized = await client.post(
        path,
        headers=auth_headers(idempotency_key=uuid4()),
        data={"period": "2026-08"},
        files={
            "file": (
                "large.pdf",
                b"%PDF-" + b"x" * 4096,
                "application/pdf",
            )
        },
    )
    missing_period = await client.post(
        path,
        headers=auth_headers(idempotency_key=uuid4()),
        files={"file": ("report.pdf", make_pdf(), "application/pdf")},
    )
    duplicate_period = await client.post(
        path,
        headers=auth_headers(idempotency_key=uuid4()),
        files=[
            ("period", (None, "2026-08")),
            ("period", (None, "2026-09")),
            ("file", ("report.pdf", make_pdf(), "application/pdf")),
        ],
    )
    duplicate_file = await client.post(
        path,
        headers=auth_headers(idempotency_key=uuid4()),
        files=[
            ("period", (None, "2026-08")),
            ("file", ("first.pdf", make_pdf(), "application/pdf")),
            ("file", ("second.pdf", make_pdf(), "application/pdf")),
        ],
    )
    unexpected = await client.post(
        path,
        headers=auth_headers(idempotency_key=uuid4()),
        data={"period": "2026-08", "unexpected": "blocked"},
        files={"file": ("report.pdf", make_pdf(), "application/pdf")},
    )
    missing_key = await client.post(
        path,
        headers=auth_headers(),
        data={"period": "2026-08"},
        files={"file": ("report.pdf", make_pdf(), "application/pdf")},
    )
    invalid_key = await client.post(
        path,
        headers=auth_headers(idempotency_key="not-a-uuid"),
        data={"period": "2026-08"},
        files={"file": ("report.pdf", make_pdf(), "application/pdf")},
    )

    for response in (
        empty,
        oversized,
        missing_period,
        duplicate_period,
        duplicate_file,
        unexpected,
        missing_key,
        invalid_key,
    ):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert response.headers["Cache-Control"] == "no-store"
    assert adapter.mock_objects == {}
    assert adapter.mock_documents == {}
    assert adapter.mock_idempotency_records == ()


async def test_transient_storage_failure_is_recovered_with_the_same_key(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context
    key = uuid4()
    calls = 0
    original = adapter.upload_private_object

    async def fail_first_upload(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ExternalStorageFailure("private storage credential must not leak")
        await original(**kwargs)

    monkeypatch.setattr(adapter, "upload_private_object", fail_first_upload)

    first = await post_report(client, key=key)

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "credential" not in first.text
    assert calls == 1
    assert adapter.mock_objects == {}
    assert adapter.mock_documents == {}
    assert len(adapter.mock_idempotency_records) == 1
    assert adapter.mock_idempotency_records[0].response_status is None

    recovered = await post_report(client, key=key)

    assert recovered.status_code == 201
    assert calls == 2
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


async def test_lost_storage_upload_response_recovers_equal_private_content(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context
    original = adapter.upload_private_object
    calls = 0

    async def upload_then_lose_response(**kwargs):
        nonlocal calls
        calls += 1
        await original(**kwargs)
        raise ExternalStorageFailure("storage response lost")

    monkeypatch.setattr(adapter, "upload_private_object", upload_then_lose_response)

    response = await post_report(client)

    assert response.status_code == 201
    assert calls == 1
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


async def test_mismatched_storage_recovery_content_stays_pending_and_safe(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context

    async def lose_upload_response(**_kwargs):
        raise ExternalStorageFailure("storage response lost")

    async def return_mismatched_content(**_kwargs):
        return b"different private content"

    monkeypatch.setattr(adapter, "upload_private_object", lose_upload_response)
    monkeypatch.setattr(adapter, "download_private_object", return_mismatched_content)

    response = await post_report(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "different private content" not in response.text
    assert adapter.mock_documents == {}
    assert adapter.mock_performance_reports == {}
    assert adapter.mock_audit_events == ()
    assert adapter.mock_idempotency_records[0].response_status is None


async def test_contract_access_failure_is_safe_503_without_reservation(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context

    async def fail_contract_lookup(**_kwargs):
        raise ExternalStorageFailure("owner lookup credential must not leak")

    monkeypatch.setattr(
        adapter,
        "get_owned_performance_contract",
        fail_contract_lookup,
    )

    response = await post_report(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "credential" not in response.text
    assert adapter.mock_objects == {}
    assert adapter.mock_idempotency_records == ()


async def test_uncertain_metadata_failure_is_recovered_with_the_same_key(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context
    calls = 0
    original = adapter.create_performance_report_upload_with_audit

    async def fail_before_commit(**kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise ExternalStorageFailure("database unavailable")
        return await original(**kwargs)

    monkeypatch.setattr(
        adapter,
        "create_performance_report_upload_with_audit",
        fail_before_commit,
    )

    key = uuid4()
    response = await post_report(client, key=key)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert calls == 2
    assert len(adapter.mock_objects) == 1
    assert adapter.mock_documents == {}
    assert adapter.mock_performance_reports == {}
    assert adapter.mock_audit_events == ()
    assert adapter.mock_idempotency_records[0].response_status is None

    recovered = await post_report(client, key=key)

    assert recovered.status_code == 201
    assert calls == 3
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


async def test_failed_orphan_cleanup_is_retried_without_duplicate_metadata(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context
    await post_report(client, key=uuid4())
    original = adapter.delete_private_object
    calls = 0

    async def fail_first_delete(*, path: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ExternalStorageFailure("storage cleanup unavailable")
        await original(path=path)

    monkeypatch.setattr(adapter, "delete_private_object", fail_first_delete)
    key = uuid4()

    first = await post_report(client, key=key)

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert len(adapter.mock_objects) == 2
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    pending = next(record for record in adapter.mock_idempotency_records if record.key == key)
    assert pending.response_status is None

    recovered = await post_report(client, key=key)

    assert recovered.status_code == 409
    assert recovered.json()["error"]["code"] == "REPORT_PERIOD_ALREADY_EXISTS"
    assert calls == 2
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


async def test_pending_idempotency_completion_recovers_committed_upload(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context
    original = adapter.complete_idempotency
    calls = 0

    async def fail_first_completion(**kwargs):
        nonlocal calls
        calls += 1
        if calls <= 3:
            raise ExternalStorageFailure("idempotency persistence unavailable")
        return await original(**kwargs)

    monkeypatch.setattr(adapter, "complete_idempotency", fail_first_completion)
    key = uuid4()

    first = await post_report(client, key=key)

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert calls == 3
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1
    assert adapter.mock_idempotency_records[0].response_status is None

    recovered = await post_report(client, key=key)

    assert recovered.status_code == 201
    assert calls == 4
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1
    assert adapter.mock_idempotency_records[0].response_status == 201


async def test_committed_metadata_is_recovered_after_both_rpc_responses_are_lost(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context
    original = adapter.create_performance_report_upload_with_audit
    calls = 0

    async def commit_then_lose_response(**kwargs):
        nonlocal calls
        calls += 1
        await original(**kwargs)
        raise ExternalStorageFailure("rpc response lost")

    monkeypatch.setattr(
        adapter,
        "create_performance_report_upload_with_audit",
        commit_then_lose_response,
    )

    response = await post_report(client)

    assert response.status_code == 201
    assert calls == 2
    assert len(adapter.mock_objects) == 1
    assert len(adapter.mock_documents) == 1
    assert len(adapter.mock_performance_reports) == 1
    assert len(adapter.mock_audit_events) == 1


async def test_ambiguous_commit_preserves_private_object_and_returns_safe_503(
    upload_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, adapter, _service = upload_context

    async def lose_rpc_response(**_kwargs):
        raise ExternalStorageFailure("rpc response lost")

    async def fail_recovery_lookup(**_kwargs):
        raise ExternalStorageFailure("recovery database unavailable")

    monkeypatch.setattr(
        adapter,
        "create_performance_report_upload_with_audit",
        lose_rpc_response,
    )
    monkeypatch.setattr(
        adapter,
        "get_owned_performance_report",
        fail_recovery_lookup,
    )

    response = await post_report(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "database" not in response.text
    assert len(adapter.mock_objects) == 1
    assert adapter.mock_documents == {}
    assert adapter.mock_performance_reports == {}
    assert adapter.mock_audit_events == ()
