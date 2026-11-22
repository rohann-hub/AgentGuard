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
            "arguments": {
                "transaction_id": "txn_1009",
                "customer_id": 101,
                "amount": 10,
                "note": "key AKIAIOSFODNN7EXAMPLE",
            },
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
            "arguments": {"transaction_id": "txn_1001", "customer_id": 101, "amount": 8000},
        },
        agent["api_key"],
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["decision"] == "approval_required"


def test_wrong_key_is_rejected():
    assert _execute(READ, "nope").status_code == 401


# --- Phase 5: audit ledger on real PostgreSQL ---

DB_URL = os.environ.get(
    "AGENTGUARD_TEST_DATABASE_URL", "postgresql://agentguard:change-me@localhost:5432/agentguard"
)


def _admin_get(path: str) -> httpx.Response:
    return httpx.get(f"{BASE_URL}{path}", headers={"X-Admin-Key": ADMIN_KEY}, timeout=10)


def test_duplicate_request_id_is_rejected(agent):
    body = READ | {"request_id": f"dup-{uuid.uuid4().hex}"}
    assert _execute(body, agent["api_key"]).status_code == 200
    assert _execute(body, agent["api_key"]).status_code == 409


def test_audit_chain_verifies():
    resp = _admin_get("/api/v1/audit/verify")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True and body["events"] > 0


@pytest.mark.parametrize(
    "sql",
    ["UPDATE audit_events SET status = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events"],
)
def test_postgres_trigger_blocks_audit_tampering(sql):
    import psycopg

    with psycopg.connect(DB_URL) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql)


# --- Phase 6: refund verification and approvals on the real stack ---


def _refund(txn: str, customer: int, amount: float, **extra) -> dict:
    return {
        "tool_name": "payment",
        "action": "refund",
        "arguments": {"transaction_id": txn, "customer_id": customer, "amount": amount},
    } | extra


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (_refund("txn_9999", 101, 10), "Transaction not found"),
        (_refund("txn_1003", 101, 10), "Original payment was not completed"),
        (_refund("txn_1002", 101, 10), "Transaction is already fully refunded"),
        (_refund("txn_1009", 101, 2600), "Refund exceeds the refundable balance"),
        (_refund("txn_1009", 102, 10), "Transaction belongs to a different customer"),
        (_refund("txn_1006", 103, 10), "Customer is not eligible: customer account is not active"),
        (_refund("txn_1001", 101, 11000), "Refund exceeds the maximum of 10000"),
    ],
)
def test_invalid_refunds_are_denied(agent, body, reason):
    resp = _execute(body, agent["api_key"])
    assert resp.status_code == 403, resp.text
    assert reason in resp.json()["reason"]


def test_risky_small_refund_needs_review(agent):
    resp = _execute(_refund("txn_1004", 102, 100), agent["api_key"])
    assert resp.status_code == 202, resp.text
    assert resp.json()["reason"] == "Risk signals: new_account"


def test_small_clean_refund_runs(agent):
    resp = _execute(_refund("txn_1009", 101, 100), agent["api_key"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["tool_result"]["total_refunded"] >= 100


def test_approval_flow_end_to_end(agent):
    key = agent["api_key"]
    ask = _execute(_refund("txn_1010", 101, 8000), key)
    assert ask.status_code == 202, ask.text
    approval_id = ask.json()["approval_id"]

    # A second refund for the same transaction is refused while one is pending.
    dup = _execute(_refund("txn_1010", 101, 500), key)
    assert dup.json()["reason"] == "A refund for this transaction is already pending"

    approve = httpx.post(
        f"{BASE_URL}/api/v1/approvals/{approval_id}/approve",
        headers={"X-Admin-Key": ADMIN_KEY},
        timeout=10,
    )
    assert approve.json()["status"] == "approved"

    tampered = _execute(_refund("txn_1010", 101, 9000, approval_id=approval_id), key)
    assert tampered.json()["reason"] == "Approval does not match this request"

    run = _execute(_refund("txn_1010", 101, 8000, approval_id=approval_id), key)
    assert run.status_code == 200, run.text
    assert run.json()["tool_result"]["refunded"] is True

    replay = _execute(_refund("txn_1010", 101, 8000, approval_id=approval_id), key)
    assert replay.status_code == 403
    assert _admin_get("/api/v1/audit/verify").json()["valid"] is True


# Runs last: it revokes the shared agent.
def test_revoked_agent_is_rejected(agent):
    resp = httpx.post(
        f"{BASE_URL}/api/v1/agents/{agent['id']}/revoke",
        headers={"X-Admin-Key": ADMIN_KEY},
        timeout=10,
    )
    assert resp.json()["status"] == "revoked"
    assert _execute(READ, agent["api_key"]).status_code == 401


def test_dashboard_is_served_with_strict_headers():
    resp = httpx.get(f"{BASE_URL}/dashboard/", timeout=10)
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    script = resp.text.split('src="/dashboard/assets/')[1].split('"')[0]
    asset = httpx.get(f"{BASE_URL}/dashboard/assets/{script}", timeout=10)
    assert asset.status_code == 200 and "javascript" in asset.headers["content-type"]


def test_overview_reads_policy_version_from_opa(agent):
    resp = httpx.get(f"{BASE_URL}/api/v1/overview", headers={"X-Admin-Key": ADMIN_KEY}, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy_version"] and body["agents"]["active"] >= 1
    assert {"name": "payment", "action": "refund", "verified": True} in body["tools"]
