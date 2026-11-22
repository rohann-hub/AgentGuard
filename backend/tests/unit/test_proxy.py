import asyncio
import dataclasses
import json

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.auth.api_keys import hash_api_key
from app.core.config import get_settings
from app.database.models import Agent
from app.policy import opa_client
from app.policy.opa_client import PolicyDecision, PolicyUnavailableError
from app.tools.registry import REGISTRY

KEY = "test-key-support"
URL = "/api/v1/proxy/execute"
READ = {"tool_name": "database", "action": "read", "arguments": {"customer_id": 101}}
DELETE = {"tool_name": "database", "action": "delete", "arguments": {"customer_id": 101}}
REFUND = {
    "tool_name": "payment",
    "action": "refund",
    "arguments": {"customer_id": 101, "amount": 8000},
}


@pytest.fixture
def api(db, make_client):
    db.add(Agent(name="support-agent", status="active", api_key_hash=hash_api_key(KEY)))
    db.add(Agent(name="old-agent", status="revoked", api_key_hash=hash_api_key("revoked-key")))
    db.commit()
    return make_client(headers={"X-API-Key": KEY})


@pytest.fixture
def policy(monkeypatch):
    """Replace OPA with a fixed decision and record what it was asked."""
    calls = []

    def set_decision(status, reason="test"):
        async def fake(_settings, policy_input):
            calls.append(policy_input)
            return PolicyDecision(status=status, reason=reason, policy_version="test-1")

        monkeypatch.setattr(opa_client, "evaluate", fake)
        return calls

    return set_decision


@pytest.fixture
def tool_calls(monkeypatch):
    """Wrap every registered tool so tests can see whether it ran."""
    calls = []
    for key, tool in list(REGISTRY.items()):

        async def spy(args, _orig=tool.handler, _key=key):
            calls.append(_key)
            return await _orig(args)

        monkeypatch.setitem(REGISTRY, key, dataclasses.replace(tool, handler=spy))
    return calls


# --- authentication ---


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_rejects_missing_or_wrong_key(api, policy, tool_calls, headers):
    policy("allow")
    del api.headers["X-API-Key"]
    resp = api.post(URL, json=READ, headers=headers)
    assert resp.status_code == 401
    assert tool_calls == []


def test_revoked_agent_is_rejected(api, policy, tool_calls):
    policy("allow")
    assert api.post(URL, json=READ, headers={"X-API-Key": "revoked-key"}).status_code == 401
    assert tool_calls == []


def test_auth_fails_closed_when_database_is_down(make_client, policy, monkeypatch, tool_calls):
    from sqlalchemy.ext.asyncio import AsyncSession

    async def broken(*_a, **_k):
        raise OperationalError("SELECT", {}, ConnectionError("down"))

    monkeypatch.setattr(AsyncSession, "scalar", broken)
    policy("allow")
    resp = make_client().post(URL, json=READ, headers={"X-API-Key": KEY})
    assert resp.status_code == 503
    assert tool_calls == []


def test_agent_identity_comes_from_key_not_body(api, policy):
    assert api.post(URL, json=READ | {"agent_id": "admin"}).status_code == 422
    calls = policy("allow")
    api.post(URL, json=READ)
    assert calls[0]["agent"] == "support-agent"


# --- request validation ---


def test_unknown_tool_is_rejected_before_policy(api, policy):
    calls = policy("allow")
    resp = api.post(URL, json={"tool_name": "shell", "action": "exec", "arguments": {}})
    assert resp.status_code == 404
    assert calls == []


@pytest.mark.parametrize(
    "arguments",
    [{}, {"customer_id": "abc"}, {"customer_id": -1}, {"customer_id": 101, "extra": "x"}],
)
def test_invalid_arguments_are_rejected_before_policy(api, policy, arguments):
    calls = policy("allow")
    resp = api.post(URL, json=READ | {"arguments": arguments})
    assert resp.status_code == 422
    assert calls == []


def test_invalid_refund_amount_rejected(api, policy):
    policy("allow")
    bad = REFUND | {"arguments": {"customer_id": 101, "amount": 0}}
    assert api.post(URL, json=bad).status_code == 422


def test_request_id_is_echoed_or_generated(api, policy):
    policy("allow")
    assert api.post(URL, json=READ | {"request_id": "req_001"}).json()["request_id"] == "req_001"
    assert api.post(URL, json=READ).json()["request_id"].startswith("req_")
    assert api.post(URL, json=READ | {"request_id": "bad id!"}).status_code == 422


# --- policy decisions ---


def test_allow_executes_tool(api, policy, tool_calls):
    calls = policy("allow", "reads ok")
    resp = api.post(URL, json=READ | {"request_id": "req_001"})
    assert resp.status_code == 200
    assert resp.json() == {
        "request_id": "req_001",
        "status": "success",
        "decision": "allow",
        "policy_version": "test-1",
        "tool_result": {"customer": {"customer_id": 101, "name": "Asha Rao", "plan": "pro"}},
    }
    assert tool_calls == [("database", "read")]
    assert calls == [
        {
            "agent": "support-agent",
            "tool_name": "database",
            "action": "read",
            "arguments": {"customer_id": 101},
        }
    ]


def test_deny_does_not_execute(api, policy, tool_calls):
    policy("deny", "Deleting customer data is prohibited")
    resp = api.post(URL, json=DELETE)
    assert resp.status_code == 403
    body = resp.json()
    assert (body["status"], body["decision"]) == ("blocked", "deny")
    assert body["reason"] == "Deleting customer data is prohibited"
    assert tool_calls == []


def test_approval_required_does_not_execute(api, policy, tool_calls):
    calls = policy("approval_required", "Refunds require human approval")
    resp = api.post(URL, json=REFUND)
    assert resp.status_code == 202
    body = resp.json()
    assert (body["status"], body["decision"]) == ("pending_approval", "approval_required")
    assert tool_calls == []
    assert calls[0]["arguments"] == {"customer_id": 101, "amount": 8000.0}


def test_fails_closed_when_opa_unavailable(api, monkeypatch, tool_calls):
    async def down(*_):
        raise PolicyUnavailableError

    monkeypatch.setattr(opa_client, "evaluate", down)
    resp = api.post(URL, json=READ)
    assert resp.status_code == 503
    assert resp.json()["decision"] == "deny"
    assert tool_calls == []


# --- tool execution ---


def test_tool_error_is_reported(api, policy):
    policy("allow")
    resp = api.post(URL, json=READ | {"arguments": {"customer_id": 999}})
    assert resp.status_code == 422
    assert resp.json()["status"] == "failed"
    assert resp.json()["reason"] == "Customer 999 not found"


def _replace_handler(monkeypatch, handler):
    key = ("database", "read")
    monkeypatch.setitem(REGISTRY, key, dataclasses.replace(REGISTRY[key], handler=handler))


def test_tool_timeout(api, policy, monkeypatch):
    async def slow(_args):
        await asyncio.sleep(1)

    monkeypatch.setenv("AGENTGUARD_TOOL_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()
    _replace_handler(monkeypatch, slow)
    policy("allow")
    resp = api.post(URL, json=READ)
    assert resp.status_code == 504
    assert resp.json()["reason"] == "Tool timed out"


def test_tool_crash_does_not_leak_details(api, policy, monkeypatch):
    async def boom(_args):
        raise RuntimeError("db password=hunter2")

    _replace_handler(monkeypatch, boom)
    policy("allow")
    resp = api.post(URL, json=READ)
    assert resp.status_code == 500
    assert "hunter2" not in resp.text


# --- OPA client ---


def _opa_returning(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        opa_client.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


async def test_opa_client_parses_decision(monkeypatch):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"result": {"status": "allow", "reason": "ok", "policy_version": "v1"}}
        )

    _opa_returning(monkeypatch, handler)
    decision = await opa_client.evaluate(get_settings(), {"action": "read"})
    assert decision == PolicyDecision(status="allow", reason="ok", policy_version="v1")
    assert seen == {"path": "/v1/data/agentguard/decision", "body": {"input": {"action": "read"}}}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json={}),  # policy not loaded
        httpx.Response(200, json={"result": {"status": "maybe", "reason": "x"}}),
        httpx.Response(200, text="not json"),
    ],
)
async def test_opa_client_fails_closed_on_bad_response(monkeypatch, response):
    _opa_returning(monkeypatch, lambda _req: response)
    with pytest.raises(PolicyUnavailableError):
        await opa_client.evaluate(get_settings(), {})


async def test_opa_client_fails_closed_when_unreachable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    _opa_returning(monkeypatch, handler)
    with pytest.raises(PolicyUnavailableError):
        await opa_client.evaluate(get_settings(), {})
