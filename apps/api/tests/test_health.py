from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ok"}
    assert response.json()["error"] is None
    assert response.json()["request_id"].startswith("req_")
