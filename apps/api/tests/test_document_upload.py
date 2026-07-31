from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_document_upload_service, get_supabase_adapter
from app.core.config import Settings
from app.core.exceptions import ExternalStorageFailure, InvalidDocument
from app.main import app
from app.schemas.documents import DocumentType
from app.services.documents import DocumentUploadService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"


def make_pdf(*, pages: int = 1, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("demo-password")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
async def upload_context(monkeypatch):
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("app.services.documents.asyncio.to_thread", run_inline)
    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    service = DocumentUploadService(
        contracts=adapter,
        documents=adapter,
        storage=adapter,
        max_size_bytes=1024 * 1024,
        max_pdf_pages=2,
    )

    async def override_adapter():
        return adapter

    async def override_service():
        return service

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_document_upload_service] = override_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, adapter, service
    finally:
        app.dependency_overrides.clear()


def authorization_header(token: str = BEARER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_uploads_contract_pdf_to_private_mock_storage(upload_context) -> None:
    client, adapter, _service = upload_context
    pdf = make_pdf()

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": "CONTRACT"},
        files={"file": ("customer-provided-name.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["error"] is None
    assert body["requestId"].startswith("req_")
    assert body["data"]["contract_id"] == str(CONTRACT_ID)
    assert body["data"]["type"] == "CONTRACT"
    assert body["data"]["parse_status"] == "PENDING"
    assert set(body["data"]) == {
        "id",
        "contract_id",
        "type",
        "parse_status",
        "created_at",
    }

    document_id = UUID(body["data"]["id"])
    stored = adapter.mock_documents[document_id]
    assert stored.page_count == 1
    assert stored.content_type == "application/pdf"
    assert stored.storage_path.endswith(f"/{document_id}/source.pdf")
    assert "customer-provided-name" not in stored.storage_path
    assert adapter.mock_objects[stored.storage_path] == pdf
    assert [event.event_type for event in adapter.mock_audit_events] == ["DOCUMENT_UPLOADED"]


async def test_accepts_utf8_message_as_single_virtual_page(upload_context) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": "MESSAGE"},
        files={"file": ("message.txt", "담당자 안내 내용".encode(), "text/plain")},
    )

    assert response.status_code == 201
    stored = adapter.mock_documents[UUID(response.json()["data"]["id"])]
    assert stored.page_count == 1
    assert stored.content_type == "text/plain"


async def test_rejects_unexpected_multipart_fields(upload_context) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": "CONTRACT", "unexpected": "must-not-be-accepted"},
        files={"file": ("contract.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert adapter.mock_objects == {}
    assert adapter.mock_documents == {}


async def test_rejects_performance_report_through_general_document_upload(
    upload_context,
) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": "PERFORMANCE_REPORT"},
        files={"file": ("performance.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert adapter.mock_objects == {}
    assert adapter.mock_documents == {}


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("message.png", b"\x89PNG\r\n\x1a\nmock", "image/png"),
        ("message.jpg", b"\xff\xd8\xffmock", "image/jpeg"),
    ],
)
async def test_accepts_message_images_as_single_virtual_page(
    upload_context,
    filename,
    content,
    content_type,
) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": "MESSAGE"},
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 201
    stored = adapter.mock_documents[UUID(response.json()["data"]["id"])]
    assert stored.page_count == 1
    assert stored.content_type == content_type


async def test_requires_bearer_authentication(upload_context) -> None:
    client, _adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        data={"type": "CONTRACT"},
        files={"file": ("contract.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"
    assert response.json()["requestId"].startswith("req_")


async def test_rejects_invalid_bearer_token(upload_context) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header("not-the-demo-token"),
        data={"type": "CONTRACT"},
        files={"file": ("contract.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"
    assert adapter.mock_objects == {}


async def test_hides_unknown_or_unowned_contract(upload_context) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{uuid4()}/documents",
        headers=authorization_header(),
        data={"type": "CONTRACT"},
        files={"file": ("contract.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert adapter.mock_objects == {}


@pytest.mark.parametrize(
    ("document_type", "filename", "content", "content_type"),
    [
        ("CONTRACT", "contract.txt", b"not a pdf", "text/plain"),
        ("CONTRACT", "contract.pdf", b"not a pdf", "application/pdf"),
        ("MESSAGE", "message.png", b"not a png", "image/png"),
        ("MESSAGE", "message.txt", b"\xff\xfe", "text/plain"),
    ],
)
async def test_rejects_disallowed_or_mismatched_file_content(
    upload_context,
    document_type,
    filename,
    content,
    content_type,
) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": document_type},
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert adapter.mock_objects == {}
    assert adapter.mock_documents == {}


async def test_rejects_encrypted_pdf(upload_context) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": "CONTRACT"},
        files={"file": ("encrypted.pdf", make_pdf(encrypted=True), "application/pdf")},
    )

    assert response.status_code == 422
    assert "암호화" in response.json()["error"]["message"]
    assert adapter.mock_objects == {}


async def test_rejects_pdf_over_page_limit(upload_context) -> None:
    client, adapter, _service = upload_context

    response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": "CONTRACT"},
        files={"file": ("too-many-pages.pdf", make_pdf(pages=3), "application/pdf")},
    )

    assert response.status_code == 422
    assert "페이지" in response.json()["error"]["message"]
    assert adapter.mock_objects == {}


async def test_rejects_empty_file_and_missing_type_with_error_envelope(
    upload_context,
) -> None:
    client, adapter, _service = upload_context

    empty_response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        data={"type": "CONTRACT"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    missing_type_response = await client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/documents",
        headers=authorization_header(),
        files={"file": ("contract.pdf", make_pdf(), "application/pdf")},
    )

    assert empty_response.status_code == 422
    assert empty_response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert missing_type_response.status_code == 422
    assert missing_type_response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert missing_type_response.json()["requestId"].startswith("req_")
    assert adapter.mock_objects == {}


async def test_rejects_content_over_configured_size(upload_context) -> None:
    _client, adapter, service = upload_context

    with pytest.raises(InvalidDocument, match="최대 크기"):
        await service.upload(
            owner_id=OWNER_ID,
            contract_id=CONTRACT_ID,
            document_type=DocumentType.CONTRACT,
            declared_content_type="application/pdf",
            content=b"%PDF-" + b"x" * (1024 * 1024),
        )

    assert adapter.mock_objects == {}
    assert adapter.mock_documents == {}


async def test_rolls_back_private_object_when_metadata_transaction_fails(
    upload_context,
    monkeypatch,
) -> None:
    _client, adapter, service = upload_context

    async def fail_metadata_transaction(**_kwargs):
        raise ExternalStorageFailure("테스트용 저장 실패")

    monkeypatch.setattr(
        adapter,
        "create_document_with_audit",
        fail_metadata_transaction,
    )

    with pytest.raises(ExternalStorageFailure, match="테스트용 저장 실패"):
        await service.upload(
            owner_id=OWNER_ID,
            contract_id=CONTRACT_ID,
            document_type=DocumentType.CONTRACT,
            declared_content_type="application/pdf",
            content=make_pdf(),
        )

    assert adapter.mock_objects == {}
    assert adapter.mock_documents == {}
    assert adapter.mock_audit_events == ()


async def test_recovers_when_metadata_rpc_commits_before_response_is_lost(
    upload_context,
    monkeypatch,
) -> None:
    _client, adapter, service = upload_context
    create_document_with_audit = adapter.create_document_with_audit

    async def commit_then_lose_response(**kwargs):
        await create_document_with_audit(**kwargs)
        raise ExternalStorageFailure("저장 후 응답이 유실됨")

    monkeypatch.setattr(
        adapter,
        "create_document_with_audit",
        commit_then_lose_response,
    )
    content = make_pdf()

    document = await service.upload(
        owner_id=OWNER_ID,
        contract_id=CONTRACT_ID,
        document_type=DocumentType.CONTRACT,
        declared_content_type="application/pdf",
        content=content,
    )

    stored = adapter.mock_documents[document.id]
    assert adapter.mock_objects[stored.storage_path] == content
    assert [event.event_type for event in adapter.mock_audit_events] == ["DOCUMENT_UPLOADED"]


async def test_preserves_private_object_when_metadata_commit_state_is_ambiguous(
    upload_context,
    monkeypatch,
) -> None:
    _client, adapter, service = upload_context

    async def lose_metadata_response(**_kwargs):
        raise ExternalStorageFailure("저장 응답이 유실됨")

    async def fail_commit_recovery_lookup(**_kwargs):
        raise ExternalStorageFailure("저장 여부를 확인할 수 없음")

    monkeypatch.setattr(
        adapter,
        "create_document_with_audit",
        lose_metadata_response,
    )
    monkeypatch.setattr(
        adapter,
        "get_owned_document",
        fail_commit_recovery_lookup,
    )

    with pytest.raises(
        ExternalStorageFailure,
        match="저장 응답이 유실됨",
    ):
        await service.upload(
            owner_id=OWNER_ID,
            contract_id=CONTRACT_ID,
            document_type=DocumentType.CONTRACT,
            declared_content_type="application/pdf",
            content=make_pdf(),
        )

    assert len(adapter.mock_objects) == 1
    assert adapter.mock_documents == {}
    assert adapter.mock_audit_events == ()


def test_rejects_mock_supabase_mode_in_production() -> None:
    with pytest.raises(ValueError, match="production"):
        Settings(app_env="production", supabase_mode="mock")


def test_requires_supabase_credentials_in_live_mode() -> None:
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        Settings(
            supabase_mode="live",
            supabase_url="",
            supabase_service_role_key="",
        )
