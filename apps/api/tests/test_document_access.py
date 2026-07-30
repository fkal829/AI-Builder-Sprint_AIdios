from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import (
    get_document_access_service,
    get_document_upload_service,
    get_supabase_adapter,
)
from app.main import app
from app.services.documents import (
    DOCUMENT_ACCESS_TTL_SECONDS,
    DocumentAccessService,
    DocumentUploadService,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"
FIXED_NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def make_pdf(*, pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def authorization_header(token: str = BEARER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def access_context(monkeypatch):
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
        mock_storage_access_base_url="http://testserver/api/v1/_mock/storage",
        clock=lambda: FIXED_NOW,
    )
    upload_service = DocumentUploadService(
        contracts=adapter,
        documents=adapter,
        storage=adapter,
        max_size_bytes=1024 * 1024,
        max_pdf_pages=3,
    )
    access_service = DocumentAccessService(
        documents=adapter,
        storage=adapter,
        clock=lambda: FIXED_NOW,
    )

    async def override_adapter():
        return adapter

    async def override_upload_service():
        return upload_service

    async def override_access_service():
        return access_service

    app.dependency_overrides[get_supabase_adapter] = override_adapter
    app.dependency_overrides[get_document_upload_service] = override_upload_service
    app.dependency_overrides[get_document_access_service] = override_access_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            upload_response = await client.post(
                f"/api/v1/contracts/{CONTRACT_ID}/documents",
                headers=authorization_header(),
                data={"type": "CONTRACT"},
                files={"file": ("contract.pdf", make_pdf(pages=2), "application/pdf")},
            )
            assert upload_response.status_code == 201
            document_id = UUID(upload_response.json()["data"]["id"])
            yield client, adapter, document_id
    finally:
        app.dependency_overrides.clear()


async def test_returns_short_lived_private_document_access(access_context) -> None:
    client, adapter, document_id = access_context

    response = await client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/documents/{document_id}/access",
        headers=authorization_header(),
        params={"source_page": 2},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["error"] is None
    assert body["requestId"].startswith("req_")
    assert body["data"]["document_id"] == str(document_id)
    assert body["data"]["source_page"] == 2
    assert datetime.fromisoformat(
        body["data"]["expires_at"].replace("Z", "+00:00")
    ) == FIXED_NOW + timedelta(seconds=DOCUMENT_ACCESS_TTL_SECONDS)
    assert set(body["data"]) == {
        "document_id",
        "access_url",
        "expires_at",
        "source_page",
    }

    stored = adapter.mock_documents[document_id]
    issued = adapter.mock_signed_accesses
    assert len(issued) == 1
    assert issued[0].path == stored.storage_path
    assert issued[0].expires_in_seconds == 300
    assert issued[0].access_url == body["data"]["access_url"]
    assert stored.storage_path not in response.text
    assert str(OWNER_ID) not in body["data"]["access_url"]
    assert str(CONTRACT_ID) not in body["data"]["access_url"]
    assert str(document_id) not in body["data"]["access_url"]

    original_response = await client.get(body["data"]["access_url"])
    assert original_response.status_code == 200
    assert original_response.headers["Cache-Control"] == "no-store"
    assert original_response.headers["X-Content-Type-Options"] == "nosniff"
    assert original_response.headers["Content-Type"] == "application/pdf"
    assert original_response.content == adapter.mock_objects[stored.storage_path]


async def test_returns_null_when_source_page_is_omitted(access_context) -> None:
    client, _adapter, document_id = access_context

    response = await client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/documents/{document_id}/access",
        headers=authorization_header(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["source_page"] is None


async def test_rejects_source_page_outside_document(access_context) -> None:
    client, adapter, document_id = access_context

    response = await client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/documents/{document_id}/access",
        headers=authorization_header(),
        params={"source_page": 3},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "페이지 범위" in response.json()["error"]["message"]
    assert adapter.mock_signed_accesses == ()


@pytest.mark.parametrize(
    "source_page",
    ["0", "-1", "not-an-integer"],
)
async def test_rejects_invalid_source_page_query(
    access_context,
    source_page,
) -> None:
    client, adapter, document_id = access_context

    response = await client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/documents/{document_id}/access",
        headers=authorization_header(),
        params={"source_page": source_page},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert adapter.mock_signed_accesses == ()


async def test_requires_owner_authentication_before_access(access_context) -> None:
    client, adapter, document_id = access_context

    missing_response = await client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/documents/{document_id}/access",
    )
    invalid_response = await client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/documents/{document_id}/access",
        headers=authorization_header("not-the-demo-token"),
    )

    assert missing_response.status_code == 401
    assert invalid_response.status_code == 401
    assert missing_response.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"
    assert invalid_response.json()["error"]["code"] == "UNAUTHORIZED_ACCESS"
    assert adapter.mock_signed_accesses == ()


@pytest.mark.parametrize(
    ("contract_id", "document_id"),
    [
        (uuid4(), uuid4()),
        (CONTRACT_ID, uuid4()),
    ],
)
async def test_hides_unknown_contract_or_document(
    access_context,
    contract_id,
    document_id,
) -> None:
    client, adapter, _uploaded_document_id = access_context

    response = await client.get(
        f"/api/v1/contracts/{contract_id}/documents/{document_id}/access",
        headers=authorization_header(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert adapter.mock_signed_accesses == ()


async def test_live_adapter_uses_supabase_signed_url(monkeypatch) -> None:
    class FakeBucket:
        def __init__(self) -> None:
            self.calls = []

        def create_signed_url(self, path, expires_in_seconds):
            self.calls.append((path, expires_in_seconds))
            return {"signedUrl": "https://storage.example.test/signed?token=opaque"}

    class FakeStorage:
        def __init__(self, bucket) -> None:
            self.bucket = bucket
            self.names = []

        def from_(self, name):
            self.names.append(name)
            return self.bucket

    class FakeClient:
        def __init__(self, storage) -> None:
            self.storage = storage

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    bucket = FakeBucket()
    storage = FakeStorage(bucket)
    fake_client = FakeClient(storage)
    monkeypatch.setattr("app.adapters.supabase.create_client", lambda *_args: fake_client)
    monkeypatch.setattr("app.adapters.supabase.asyncio.to_thread", run_inline)
    adapter = SupabaseAdapter(
        mode="live",
        url="https://project.supabase.co",
        service_role_key="test-service-role-key",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )

    access_url = await adapter.create_signed_access_url(
        path="owner/contract/document/source.pdf",
        expires_in_seconds=300,
    )

    assert access_url == "https://storage.example.test/signed?token=opaque"
    assert storage.names == ["contracts"]
    assert bucket.calls == [("owner/contract/document/source.pdf", 300)]


async def test_expired_mock_access_url_is_not_readable() -> None:
    current_time = FIXED_NOW

    def clock():
        return current_time

    adapter = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
        clock=clock,
    )
    path = "owner/contract/document/source.pdf"
    await adapter.upload_private_object(
        path=path,
        content=b"%PDF-mock",
        content_type="application/pdf",
    )
    access_url = await adapter.create_signed_access_url(
        path=path,
        expires_in_seconds=300,
    )
    token = access_url.rsplit("/", 1)[-1]

    current_time = FIXED_NOW + timedelta(seconds=301)

    assert await adapter.get_mock_signed_object(token=token) is None
    assert adapter.mock_signed_accesses == ()


async def test_unknown_mock_access_url_returns_non_cacheable_404(
    access_context,
) -> None:
    client, _adapter, _document_id = access_context

    response = await client.get("/api/v1/_mock/storage/not-a-valid-token")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


def test_openapi_exposes_document_access_contract() -> None:
    paths = app.openapi()["paths"]
    operation = paths["/api/v1/contracts/{contract_id}/documents/{document_id}/access"]["get"]

    assert (
        operation["responses"]["200"]["headers"]["Cache-Control"]["schema"]["example"] == "no-store"
    )
    source_page = next(
        parameter for parameter in operation["parameters"] if parameter["name"] == "source_page"
    )
    assert {"type": "integer", "minimum": 1} in source_page["schema"]["anyOf"]
    assert "/api/v1/_mock/storage/{token}" not in paths
