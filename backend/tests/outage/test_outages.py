"""Stops and restarts OPA and PostgreSQL under the running stack.

Run with: docker compose up -d --wait && pytest -m outage
Nothing may execute while a dependency is down, and the service must recover after.
"""

import os
import subprocess
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.outage

BASE_URL = os.environ.get("AGENTGUARD_BASE_URL", "http://localhost:8000")
ADMIN = {"X-Admin-Key": os.environ.get("AGENTGUARD_TEST_ADMIN_KEY", "ci-admin-key")}
READ = {"tool_name": "database", "action": "read", "arguments": {"customer_id": 101}}


def _compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True)


def _wait_ready(timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{BASE_URL}/health/ready", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError("service did not become ready")


@pytest.fixture(scope="module")
def agent():
    _wait_ready()
    resp = httpx.post(
        f"{BASE_URL}/api/v1/agents",
        json={"name": f"outage-{uuid.uuid4().hex[:8]}"},
        headers=ADMIN,
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return {"X-API-Key": resp.json()["api_key"]}


def _execute(agent, body):
    return httpx.post(f"{BASE_URL}/api/v1/proxy/execute", json=body, headers=agent, timeout=15)


def test_opa_outage_blocks_everything_then_recovers(agent):
    read = READ | {"request_id": f"o-{uuid.uuid4().hex}"}
    refund = {
        "tool_name": "payment",
        "action": "refund",
        "arguments": {"transaction_id": "txn_1009", "customer_id": 101, "amount": 1},
    }
    _compose("stop", "opa")
    try:
        assert httpx.get(f"{BASE_URL}/health/ready", timeout=10).status_code == 503
        for body in (read, refund):
            resp = _execute(agent, body)
            assert resp.status_code == 503, resp.text
            assert resp.json()["reason"] == "Policy engine unavailable"
            assert "tool_result" not in resp.json()
    finally:
        _compose("start", "opa")
    _wait_ready()
    # The same request_id is retryable after an outage, and now runs.
    assert _execute(agent, read).status_code == 200
    events = httpx.get(
        f"{BASE_URL}/api/v1/audit", params={"request_id": read["request_id"]}, headers=ADMIN
    ).json()
    assert [e["event_type"] for e in reversed(events)] == ["error", "decision", "execution"]


def test_database_outage_rejects_requests_then_recovers(agent):
    _compose("stop", "postgres")
    try:
        assert httpx.get(f"{BASE_URL}/health/ready", timeout=10).status_code == 503
        resp = _execute(agent, READ)
        assert resp.status_code == 503, resp.text
        assert "tool_result" not in resp.json()
    finally:
        _compose("start", "postgres")
    _wait_ready()
    assert _execute(agent, READ).status_code == 200


def test_audit_chain_survives_outages():
    resp = httpx.get(f"{BASE_URL}/api/v1/audit/verify", headers=ADMIN, timeout=10)
    assert resp.json()["valid"] is True
