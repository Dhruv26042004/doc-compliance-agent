from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_responds():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"ok", "degraded"}
    assert "connected" in body["database"]
