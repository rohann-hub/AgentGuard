"""Runs against the real Compose stack: `docker compose up -d` then `pytest -m integration`."""

import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("AGENTGUARD_BASE_URL", "http://localhost:8000")


def test_backend_is_ready_against_real_postgres_and_opa():
    resp = httpx.get(f"{BASE_URL}/health/ready", timeout=10)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ready", "checks": {"database": "ok", "opa": "ok"}}


def test_opa_loaded_the_base_policy():
    opa_url = os.environ.get("AGENTGUARD_OPA_URL", "http://localhost:8181")
    resp = httpx.post(
        f"{opa_url}/v1/data/agentguard/decision",
        json={"input": {"tool_name": "unknown_tool", "action": "anything"}},
        timeout=10,
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "deny"


# The CI workflow configures this admin key.
ADMIN_KEY = os.environ.get("AGENTGUARD_TEST_ADMIN_KEY", "ci-admin-key")


@pytest.fixture(scope="module")
def agent() -> dict:
    resp = httpx.post(
        f"{BASE_URL}/api/v1/agents",
        json={"name": f"it-{uuid.uuid4().hex[:12]}"},
        headers={"X-Admin-Key": ADMIN_KEY},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _execute(body: dict, key: str) -> httpx.Response:
    return httpx.post(
        f"{BASE_URL}/api/v1/proxy/execute", json=body, headers={"X-API-Key": key}, timeout=10
    )


READ = {"tool_name": "database", "action": "read", "arguments": {"customer_id": 101}}


def test_read_customer_is_allowed_and_executed(agent):
    resp = _execute(READ, agent["api_key"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["decision"]) == ("success", "allow")
    assert body["tool_result"]["customer"]["customer_id"] == 101
    assert body["policy_version"]
    # Phase 4: PII in the response is redacted by the firewall.
    assert body["tool_result"]["customer"]["email"] == "[REDACTED:EMAIL]"


def test_secret_in_arguments_is_blocked(agent):
    resp = _execute(
        {
            "tool_name": "payment",
            "action": "refund",
            "arguments": {"customer_id": 101, "amount": 10, "note": "key AKIAIOSFODNN7EXAMPLE"},
        },
        agent["api_key"],
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["firewall"][0]["entity_type"] == "AWS_ACCESS_KEY"
    assert "AKIA" not in resp.text


def test_delete_customer_is_denied_by_policy(agent):
    resp = _execute(
        {"tool_name": "database", "action": "delete", "arguments": {"customer_id": 101}},
        agent["api_key"],
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["reason"] == "Deleting customer data is prohibited"


def test_refund_needs_approval(agent):
    resp = _execute(
        {
            "tool_name": "payment",
            "action": "refund",
            "arguments": {"customer_id": 101, "amount": 8000},
        },
        agent["api_key"],
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["decision"] == "approval_required"


def test_wrong_key_is_rejected():
    assert _execute(READ, "nope").status_code == 401


def test_revoked_agent_is_rejected(agent):
    resp = httpx.post(
        f"{BASE_URL}/api/v1/agents/{agent['id']}/revoke",
        headers={"X-Admin-Key": ADMIN_KEY},
        timeout=10,
    )
    assert resp.json()["status"] == "revoked"
    assert _execute(READ, agent["api_key"]).status_code == 401
