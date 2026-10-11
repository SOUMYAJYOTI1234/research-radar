from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_serves_html_page():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Research Radar" in response.text
