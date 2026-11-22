from app.api.routes import health


def test_health_is_ok_without_dependencies(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "AgentGuard"


async def _ok():
    return None


async def _fail(*_):
    raise ConnectionError("down")


def test_ready_when_all_dependencies_answer(client, monkeypatch):
    monkeypatch.setattr(health, "check_database", _ok)
    monkeypatch.setattr(health, "check_opa", lambda _settings: _ok())
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"database": "ok", "opa": "ok"}}


def test_not_ready_fails_closed_when_opa_is_down(client, monkeypatch):
    monkeypatch.setattr(health, "check_database", _ok)
    monkeypatch.setattr(health, "check_opa", _fail)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json() == {"status": "not_ready", "checks": {"database": "ok", "opa": "error"}}


def test_not_ready_when_database_is_down(client, monkeypatch):
    monkeypatch.setattr(health, "check_database", _fail)
    monkeypatch.setattr(health, "check_opa", lambda _settings: _ok())
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["database"] == "error"


def test_docs_hidden_in_production(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("AGENTGUARD_ENV", "production")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/health").json()["env"] == "production"
