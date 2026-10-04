from fastapi.testclient import TestClient

import pytest

from app.config import get_settings
from app.main import create_app
from tests.fakes import FakeDB


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_homepage_renders_without_secrets(client):
    html = client.get("/").text
    assert "English Practice Assistant" in html
    assert "GEMMA_API_KEY" not in html and "MONGODB_URI" not in html
    assert client.get("/").headers["x-content-type-options"] == "nosniff"


def test_app_starts_without_ai_credentials(monkeypatch):
    for name in ("GEMMA_API_URL", "GEMMA_API_KEY"):
        monkeypatch.setenv(name, "")  # overrides any value in a local .env
    app = create_app()
    app.state.db = FakeDB()
    with TestClient(app) as client:
        body = client.get("/api/health").json()
        assert body["ai"] == "unconfigured"
        assert "AI provider unavailable" in body["ai_message"]
        # Free conversation can be opened; sending a message explains how to enable AI.
        created = client.post("/api/conversations", json={}).json()
        reply = client.post(
            f"/api/conversations/{created['conversation']['id']}/messages", json={"content": "Hi"}
        )
        assert reply.status_code == 503
        assert "GEMMA_API_URL" in reply.json()["detail"]
        assert "Traceback" not in reply.text


def test_invalid_config_message(monkeypatch):
    monkeypatch.setenv("GEMMA_API_URL", "https://example.test/v1/chat/completions")
    monkeypatch.setenv("GEMMA_API_KEY", "")
    app = create_app()
    app.state.db = FakeDB()
    with TestClient(app) as client:
        body = client.get("/api/health").json()
        assert body["ai"] == "invalid"
        assert "not configured correctly" in body["ai_message"]
