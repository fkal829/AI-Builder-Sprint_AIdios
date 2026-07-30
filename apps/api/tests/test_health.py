from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_check() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ok"}
    assert response.json()["error"] is None
    assert response.json()["requestId"].startswith("req_")
