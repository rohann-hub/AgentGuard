import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>AgentGuard</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-1.js").write_text("console.log(1)")
    monkeypatch.setenv("AGENTGUARD_DASHBOARD_DIR", str(tmp_path))
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c


def test_dashboard_is_served_with_security_headers(dashboard):
    resp = dashboard.get("/dashboard/")
    assert resp.status_code == 200
    assert "AgentGuard" in resp.text
    assert resp.headers["cache-control"] == "no-cache"
    csp = resp.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"

    asset = dashboard.get("/dashboard/assets/app-1.js")
    assert asset.status_code == 200
    assert asset.headers["x-content-type-options"] == "nosniff"


def test_dashboard_redirects_bare_path_and_hides_other_files(dashboard):
    assert dashboard.get("/dashboard", follow_redirects=False).status_code in (307, 308)
    assert dashboard.get("/dashboard/../app/main.py").status_code == 404
    assert dashboard.get("/dashboard/missing.js").status_code == 404


def test_dashboard_not_served_by_default(client):
    assert client.get("/dashboard/").status_code == 404


def test_dashboard_dir_without_index_fails_fast(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_DASHBOARD_DIR", str(tmp_path))
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="no index.html"):
        create_app()
