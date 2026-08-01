from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.solar import SolarReviewAdapter, SolarTonePolishError
from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_supabase_adapter, get_tone_polish_service
from app.main import app
from app.services.tone_polish import TonePolishService

OWNER_ID = UUID("00000000-0000-4000-8000-000000000013")
DEMO_CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000041")
BEARER_TOKEN = "local-demo-owner-token"


class FailingTonePolisher(SolarReviewAdapter):
    async def polish_adjustment_copy(self, *, text: str):
        raise SolarTonePolishError("failed")


@pytest.fixture
async def tone_context():
    repository = SupabaseAdapter(
        mode="mock",
        url="",
        service_role_key="",
        bucket="contracts",
        demo_owner_id=OWNER_ID,
        demo_contract_id=DEMO_CONTRACT_ID,
        demo_bearer_token=BEARER_TOKEN,
    )
    polisher = SolarReviewAdapter(
        mode="mock",
        api_key="",
        base_url="https://api.upstage.ai",
    )

    async def override_repository():
        return repository

    async def override_service():
        return TonePolishService(repository=repository, polisher=polisher)

    app.dependency_overrides[get_supabase_adapter] = override_repository
    app.dependency_overrides[get_tone_polish_service] = override_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            created = await client.post(
                "/api/v1/contracts",
                headers={"Authorization": f"Bearer {BEARER_TOKEN}"},
                json={"title": "문구 다듬기 계약", "counterparty_name": "부산 대행사"},
            )
            assert created.status_code == 201
            contract_id = UUID(created.json()["data"]["id"])
            yield client, repository, contract_id
    finally:
        app.dependency_overrides.clear()


def authorization_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {BEARER_TOKEN}"}


async def test_polishes_copy_without_persisting_or_sending(tone_context) -> None:
    client, repository, contract_id = tone_context
    before_events = repository.mock_audit_events
    before_contract = repository.mock_contracts[contract_id]

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-copy/polish",
        headers=authorization_header(),
        json={"text": "계약 기간 5년은 너무 길어요 ㅠㅠ"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "5년" in response.json()["data"]["polished_text"]
    assert repository.mock_audit_events == before_events
    assert repository.mock_contracts[contract_id] == before_contract


async def test_tone_polish_requires_authentication_and_owned_contract(tone_context) -> None:
    client, _repository, contract_id = tone_context
    unauthenticated = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-copy/polish",
        json={"text": "정중하게 바꿔 주세요"},
    )
    missing = await client.post(
        f"/api/v1/contracts/{uuid4()}/adjustment-copy/polish",
        headers=authorization_header(),
        json={"text": "정중하게 바꿔 주세요"},
    )

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["Cache-Control"] == "no-store"
    assert missing.status_code == 404


@pytest.mark.parametrize("text", ["   ", "a" * 1201])
async def test_tone_polish_rejects_invalid_text(tone_context, text: str) -> None:
    client, _repository, contract_id = tone_context

    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-copy/polish",
        headers=authorization_header(),
        json={"text": text},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_tone_polish_maps_solar_failure_to_safe_502(tone_context) -> None:
    client, repository, contract_id = tone_context
    failing = FailingTonePolisher(
        mode="mock",
        api_key="",
        base_url="https://api.upstage.ai",
    )

    async def override_service():
        return TonePolishService(repository=repository, polisher=failing)

    app.dependency_overrides[get_tone_polish_service] = override_service
    response = await client.post(
        f"/api/v1/contracts/{contract_id}/adjustment-copy/polish",
        headers=authorization_header(),
        json={"text": "계약 기간 5년을 조정해 주세요"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ANALYSIS_SCHEMA_INVALID"
    assert "failed" not in response.text
