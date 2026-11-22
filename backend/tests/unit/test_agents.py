import pytest

from app.auth.api_keys import hash_api_key
from app.core.config import get_settings
from app.database.models import Agent

ADMIN = "test-admin-key"
URL = "/api/v1/agents"


@pytest.fixture
def admin(monkeypatch, make_client):
    monkeypatch.setenv("AGENTGUARD_ADMIN_API_KEY_HASH", hash_api_key(ADMIN))
    get_settings.cache_clear()
    return make_client(headers={"X-Admin-Key": ADMIN})


def test_register_returns_key_once_and_stores_only_hash(admin, db):
    resp = admin.post(URL, json={"name": "support-agent", "description": "helps"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "active" and body["api_key"].startswith("ag_")

    stored = db.query(Agent).one()
    assert stored.api_key_hash == hash_api_key(body["api_key"])
    assert body["api_key"] not in str(vars(stored))

    listed = admin.get(URL).json()
    assert [a["name"] for a in listed] == ["support-agent"]
    assert "api_key" not in listed[0] and "api_key_hash" not in listed[0]
    assert admin.get(f"{URL}/{body['id']}").json()["description"] == "helps"


def test_duplicate_name_conflicts(admin):
    assert admin.post(URL, json={"name": "a1"}).status_code == 201
    assert admin.post(URL, json={"name": "a1"}).status_code == 409


@pytest.mark.parametrize("body", [{}, {"name": "Has Spaces"}, {"name": "a", "status": "x"}])
def test_invalid_registration_rejected(admin, body):
    assert admin.post(URL, json=body).status_code == 422


def test_revoked_agent_can_no_longer_call_proxy(admin, monkeypatch):
    from app.policy import opa_client
    from app.policy.opa_client import PolicyDecision

    async def allow(*_):
        return PolicyDecision(status="allow", reason="ok", policy_version="t")

    monkeypatch.setattr(opa_client, "evaluate", allow)
    created = admin.post(URL, json={"name": "temp"}).json()
    call = {"tool_name": "database", "action": "read", "arguments": {"customer_id": 101}}
    key = {"X-API-Key": created["api_key"]}
    assert admin.post("/api/v1/proxy/execute", json=call, headers=key).status_code == 200

    revoked = admin.post(f"{URL}/{created['id']}/revoke")
    assert revoked.json()["status"] == "revoked"
    assert admin.post("/api/v1/proxy/execute", json=call, headers=key).status_code == 401


def test_unknown_agent_404(admin):
    missing = "00000000-0000-0000-0000-000000000000"
    assert admin.get(f"{URL}/{missing}").status_code == 404
    assert admin.post(f"{URL}/{missing}/revoke").status_code == 404


@pytest.mark.parametrize("key", [None, "wrong"])
def test_admin_key_required(admin, key):
    del admin.headers["X-Admin-Key"]
    headers = {"X-Admin-Key": key} if key else {}
    assert admin.get(URL, headers=headers).status_code == 401


def test_admin_apis_disabled_without_configured_hash(make_client):
    c = make_client(headers={"X-Admin-Key": ADMIN})
    assert c.get(URL).status_code == 401


def test_agent_key_is_not_an_admin_key(admin):
    created = admin.post(URL, json={"name": "sneaky"}).json()
    del admin.headers["X-Admin-Key"]
    assert admin.get(URL, headers={"X-Admin-Key": created["api_key"]}).status_code == 401


def test_settings_reject_raw_admin_key(monkeypatch):
    monkeypatch.setenv("AGENTGUARD_ADMIN_API_KEY_HASH", "plain-text-key")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="SHA-256"):
        get_settings()
