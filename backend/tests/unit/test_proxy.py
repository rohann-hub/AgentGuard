import asyncio
import dataclasses
import json

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.policy import opa_client
from app.policy.opa_client import PolicyDecision, PolicyUnavailableError
from app.tools.registry import REGISTRY
from tests.unit.conftest import AGENT_KEY as KEY

URL = "/api/v1/proxy/execute"
READ = {"tool_name": "database", "action": "read", "arguments": {"customer_id": 101}}
DELETE = {"tool_name": "database", "action": "delete", "arguments": {"customer_id": 101}}
REFUND = {
    "tool_name": "payment",
    "action": "refund",
    "arguments": {"transaction_id": "txn_1001", "customer_id": 101, "amount": 8000},
}


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
        "tool_result": {
            "customer": {
                "customer_id": 101,
                "name": "Asha Rao",
                "email": "[REDACTED:EMAIL]",
                "phone": "[REDACTED:PHONE]",
                "plan": "pro",
            }
        },
        "firewall": [
            {"entity_type": "EMAIL", "path": "tool_result.customer.email", "action": "redact"},
            {"entity_type": "PHONE", "path": "tool_result.customer.phone", "action": "redact"},
        ],
    }
    assert tool_calls == [("database", "read")]
    assert calls == [
        {
            "agent": "support-agent",
            "tool_name": "database",
            "action": "read",
            "arguments": {"customer_id": 101},
            "firewall": [],
            "verification": {},
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
    assert calls[0]["arguments"] == {
        "transaction_id": "txn_1001",
        "customer_id": 101,
        "amount": 8000.0,
        "note": None,
    }


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


# --- firewall ---


def _refund_with(note):
    return REFUND | {
        "arguments": {"transaction_id": "txn_1009", "customer_id": 101, "amount": 100, "note": note}
    }


def test_secret_in_arguments_is_blocked_before_policy(api, policy, tool_calls):
    calls = policy("allow")
    resp = api.post(URL, json=_refund_with("use key AKIAIOSFODNN7EXAMPLE"))
    assert resp.status_code == 403
    body = resp.json()
    assert body["reason"] == "Sensitive data in arguments"
    assert body["firewall"] == [
        {"entity_type": "AWS_ACCESS_KEY", "path": "arguments.note", "action": "block"}
    ]
    assert "AKIA" not in resp.text
    assert calls == [] and tool_calls == []


def test_pii_in_arguments_is_redacted_before_policy_and_tool(api, policy, tool_calls):
    calls = policy("allow")
    resp = api.post(URL, json=_refund_with("customer asha.rao@example.com asked"))
    assert resp.status_code == 200
    assert calls[0]["arguments"]["note"] == "customer [REDACTED:EMAIL] asked"
    assert calls[0]["firewall"] == ["EMAIL"]
    assert resp.json()["tool_result"]["note"] == "customer [REDACTED:EMAIL] asked"
    assert "asha.rao" not in resp.text


def test_firewall_actions_are_configurable(api, policy, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_FIREWALL_ACTIONS", json.dumps({"EMAIL": "allow"}))
    get_settings.cache_clear()
    policy("allow")
    resp = api.post(URL, json=READ)
    assert resp.json()["tool_result"]["customer"]["email"] == "asha.rao@example.com"


def test_secret_in_tool_response_is_blocked(api, policy, monkeypatch):
    async def leaky(_args):
        return {"config": {"db_password": "hunter2"}}

    _replace_handler(monkeypatch, leaky)
    policy("allow")
    resp = api.post(URL, json=READ)
    assert resp.status_code == 403
    assert resp.json()["reason"] == "Sensitive data in tool response"
    assert "hunter2" not in resp.text
