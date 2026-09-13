from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_reports_running_mode() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mode"] in {"demo", "llm"}