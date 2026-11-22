"""The design doc's end-to-end story, run against the real stack (Postgres + OPA).

Agent -> Read customer   -> ALLOW              -> tool executed
Agent -> Delete customer -> DENY               -> tool not executed
Agent -> Refund 8,000    -> APPROVAL REQUIRED  -> not executed until a human approves
"""

import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("AGENTGUARD_BASE_URL", "http://localhost:8000")
ADMIN = {"X-Admin-Key": os.environ.get("AGENTGUARD_TEST_ADMIN_KEY", "ci-admin-key")}


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def agent(client):
    resp = client.post(
        "/api/v1/agents", json={"name": f"e2e-{uuid.uuid4().hex[:8]}"}, headers=ADMIN
    )
    assert resp.status_code == 201, resp.text
    return {"X-API-Key": resp.json()["api_key"]}


def _call(client, agent, tool, action, arguments, **extra):
    body = {"request_id": f"e2e-{uuid.uuid4().hex}", "tool_name": tool, "action": action}
    return client.post(
        "/api/v1/proxy/execute", json=body | {"arguments": arguments} | extra, headers=agent
    )


def _events(client, request_id):
    resp = client.get("/api/v1/audit", params={"request_id": request_id}, headers=ADMIN)
    return [(e["event_type"], e["status"]) for e in reversed(resp.json())]


def test_scenario_1_read_is_allowed_and_executed(client, agent):
    resp = _call(client, agent, "database", "read", {"customer_id": 101})
    body = resp.json()
    assert (resp.status_code, body["decision"], body["status"]) == (200, "allow", "success")
    assert body["tool_result"]["customer"]["email"] == "[REDACTED:EMAIL]"
    assert _events(client, body["request_id"]) == [
        ("decision", "executing"),
        ("execution", "success"),
    ]


def test_scenario_2_delete_is_denied_and_not_executed(client, agent):
    resp = _call(client, agent, "database", "delete", {"customer_id": 101})
    body = resp.json()
    assert (resp.status_code, body["decision"]) == (403, "deny")
    assert _events(client, body["request_id"]) == [("decision", "blocked")]


def test_scenario_3_refund_waits_for_approval_then_runs_once(client, agent):
    refund = {"transaction_id": "txn_1011", "customer_id": 101, "amount": 8000}

    ask = _call(client, agent, "payment", "refund", refund)
    assert ask.status_code == 202, ask.text
    approval_id = ask.json()["approval_id"]
    assert _events(client, ask.json()["request_id"]) == [("decision", "pending_approval")]

    early = _call(client, agent, "payment", "refund", refund, approval_id=approval_id)
    assert (early.status_code, early.json()["reason"]) == (403, "Approval is pending")

    approved = client.post(f"/api/v1/approvals/{approval_id}/approve", headers=ADMIN)
    assert approved.json()["status"] == "approved"

    run = _call(client, agent, "payment", "refund", refund, approval_id=approval_id)
    assert run.status_code == 200, run.text
    assert run.json()["tool_result"]["total_refunded"] == 8000

    again = _call(client, agent, "payment", "refund", refund, approval_id=approval_id)
    assert (again.status_code, again.json()["reason"]) == (403, "Approval is used")


def test_scenario_4_secret_is_blocked_and_never_stored(client, agent):
    secret = "AKIAIOSFODNN7EXAMPLE"
    refund = {"transaction_id": "txn_1009", "customer_id": 101, "amount": 5, "note": secret}
    resp = _call(client, agent, "payment", "refund", refund)
    assert resp.status_code == 403 and secret not in resp.text
    audit = client.get(
        "/api/v1/audit", params={"request_id": resp.json()["request_id"]}, headers=ADMIN
    )
    assert secret not in audit.text


def test_scenario_5_audit_chain_is_intact(client):
    assert client.get("/api/v1/audit/verify", headers=ADMIN).json()["valid"] is True
