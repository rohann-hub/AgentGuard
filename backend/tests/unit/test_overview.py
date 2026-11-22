import httpx
import pytest

from app.api.routes import overview
from tests.unit.conftest import ADMIN

URL = "/api/v1/proxy/execute"
READ = {"tool_name": "database", "action": "read", "arguments": {"customer_id": 101}}
DELETE = {"tool_name": "database", "action": "delete", "arguments": {"customer_id": 101}}


@pytest.fixture
def opa_version(monkeypatch):
    def set_response(handler):
        real = httpx.AsyncClient
        monkeypatch.setattr(
            overview.httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
        )

    return set_response


def test_overview_requires_admin(api, admin):
    assert api.get("/api/v1/overview").status_code == 401
    assert admin.get("/api/v1/overview", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert admin.get("/api/v1/overview", headers={"X-Admin-Key": ADMIN}).status_code == 200


def test_overview_counts_and_tools(api, policy, admin, opa_version):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"result": "2026-11-22.2"})

    opa_version(handler)
    policy("allow")
    api.post(URL, json=READ)
    policy("deny")
    api.post(URL, json=DELETE)

    body = admin.get("/api/v1/overview").json()
    assert seen == ["/v1/data/agentguard/policy_version"]
    assert body["policy_version"] == "2026-11-22.2"
    assert body["agents"] == {"active": 1, "revoked": 1}
    assert body["decisions"] == {"allow": 1, "deny": 1}
    assert body["approvals"] == {}
    assert {"name": "payment", "action": "refund", "verified": True} in body["tools"]
    assert {"name": "database", "action": "read", "verified": False} in body["tools"]


@pytest.mark.parametrize(
    "response", [httpx.Response(500), httpx.Response(200, json={}), httpx.Response(200, text="x")]
)
def test_overview_renders_without_opa(api, admin, opa_version, response):
    opa_version(lambda _req: response)
    resp = admin.get("/api/v1/overview")
    assert resp.status_code == 200
    assert resp.json()["policy_version"] is None


def test_audit_filters(api, policy, admin):
    policy("allow")
    api.post(URL, json=READ | {"request_id": "r1"})
    policy("deny")
    api.post(URL, json=DELETE | {"request_id": "r2"})

    def ids(**params):
        rows = admin.get("/api/v1/audit", params=params).json()
        return [(r["request_id"], r["event_type"]) for r in rows]

    assert ids(decision="deny") == [("r2", "decision")]
    assert ids(decision="allow") == [("r1", "execution"), ("r1", "decision")]
    assert ids(event_type="execution") == [("r1", "execution")]
    assert ids(agent_name="support-agent", decision="allow", event_type="decision") == [
        ("r1", "decision")
    ]
    assert ids(agent_name="nobody") == []
    assert admin.get("/api/v1/audit", params={"event_type": "other"}).status_code == 422
