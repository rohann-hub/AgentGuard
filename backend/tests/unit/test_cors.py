import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.main import create_app

DASHBOARD = "https://agentguard-dashboard.vercel.app"
PREFLIGHT = {
    "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "x-admin-key",
}


def _client(monkeypatch, origins: str | None) -> TestClient:
    if origins is not None:
        monkeypatch.setenv("AGENTGUARD_CORS_ORIGINS", origins)
    get_settings.cache_clear()
    return TestClient(create_app())


def test_no_cross_origin_access_by_default(monkeypatch):
    client = _client(monkeypatch, None)
    resp = client.options("/api/v1/overview", headers={"Origin": DASHBOARD, **PREFLIGHT})
    assert "access-control-allow-origin" not in resp.headers


def test_allowed_origin_gets_preflight_for_admin_header(monkeypatch):
    client = _client(monkeypatch, f'["{DASHBOARD}"]')
    resp = client.options("/api/v1/overview", headers={"Origin": DASHBOARD, **PREFLIGHT})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == DASHBOARD
    assert "x-admin-key" in resp.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in resp.headers


def test_other_origins_are_refused(monkeypatch):
    client = _client(monkeypatch, f'["{DASHBOARD}"]')
    resp = client.options(
        "/api/v1/overview", headers={"Origin": "https://evil.example", **PREFLIGHT}
    )
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers
    plain = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in plain.headers


@pytest.mark.parametrize(
    "bad", ["*", "https://*.vercel.app", "vercel.app", "https://x.app/path", "ftp://x"]
)
def test_cors_origins_must_be_exact(bad):
    with pytest.raises(ValidationError):
        Settings(cors_origins=[bad])
