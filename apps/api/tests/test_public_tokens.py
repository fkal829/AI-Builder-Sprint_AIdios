from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from app.adapters.supabase import SupabaseAdapter
from app.core.enums import PublicTokenScope
from app.core.exceptions import PublicTokenExpired, ResourceNotFound
from app.core.http import set_no_store
from app.main import app
from app.services.public_tokens import PublicTokenService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
TOKEN_SECRET = "test-public-token-signing-secret-at-least-32-characters"


@pytest.fixture
def token_adapter() -> SupabaseAdapter:
    return SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=CONTRACT_ID,
        demo_bearer_token="local-demo-owner-token",
    )


async def test_issues_hashed_adjustment_token_and_resolves_it(token_adapter) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    adjustment_id = uuid4()
    service = PublicTokenService(token_adapter, signing_secret=TOKEN_SECRET, now=lambda: now)

    issued = await service.issue_adjustment_response(
        adjustment_request_id=adjustment_id,
        expires_at=now + timedelta(hours=24),
    )
    resolved = await service.resolve(
        token=issued.token,
        expected_scope=PublicTokenScope.ADJUSTMENT_RESPONSE,
        expected_resource_id=adjustment_id,
    )

    assert resolved.scope == PublicTokenScope.ADJUSTMENT_RESPONSE
    assert resolved.resource_id == adjustment_id
    assert issued.token not in token_adapter.mock_public_tokens
    assert all(
        issued.token not in repr(record)
        for record in token_adapter.mock_public_tokens.values()
    )


@pytest.mark.parametrize(
    "token",
    ["too-short", "x" * 80, "00000000-0000-4000-8000-000000000001.invalid"],
)
async def test_hides_malformed_public_tokens_as_not_found(token_adapter, token: str) -> None:
    service = PublicTokenService(
        token_adapter,
        signing_secret=TOKEN_SECRET,
        now=lambda: datetime(2026, 7, 30, tzinfo=UTC),
    )

    with pytest.raises(ResourceNotFound):
        await service.resolve(token=token, expected_scope=PublicTokenScope.ADJUSTMENT_RESPONSE)


async def test_hides_scope_and_resource_mismatches_as_not_found(token_adapter) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    service = PublicTokenService(token_adapter, signing_secret=TOKEN_SECRET, now=lambda: now)
    issued = await service.issue_adjustment_response(
        adjustment_request_id=uuid4(),
        expires_at=now + timedelta(hours=1),
    )

    with pytest.raises(ResourceNotFound):
        await service.resolve(
            token=issued.token,
            expected_scope=PublicTokenScope.OBLIGATION_EVIDENCE,
        )
    with pytest.raises(ResourceNotFound):
        await service.resolve(
            token=issued.token,
            expected_scope=PublicTokenScope.ADJUSTMENT_RESPONSE,
            expected_resource_id=uuid4(),
        )


async def test_returns_gone_only_for_valid_expired_token(token_adapter) -> None:
    clock = [datetime(2026, 7, 30, tzinfo=UTC)]
    service = PublicTokenService(token_adapter, signing_secret=TOKEN_SECRET, now=lambda: clock[0])
    issued = await service.issue_adjustment_response(
        adjustment_request_id=uuid4(),
        expires_at=clock[0] + timedelta(minutes=1),
    )
    clock[0] = clock[0] + timedelta(minutes=1)

    with pytest.raises(PublicTokenExpired) as raised:
        await service.resolve(
            token=issued.token,
            expected_scope=PublicTokenScope.ADJUSTMENT_RESPONSE,
        )

    assert raised.value.status_code == 410
    assert raised.value.code.value == "ADJUSTMENT_LINK_EXPIRED"


def test_no_store_response_helper() -> None:
    response = set_no_store(Response())

    assert response.headers["Cache-Control"] == "no-store"


async def test_public_path_responses_are_always_no_store() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/public/not-a-real-resource")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"
