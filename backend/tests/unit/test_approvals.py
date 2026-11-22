import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.api_keys import hash_api_key
from app.core.config import get_settings
from app.database.models import Agent, Approval, AuditEvent

URL = "/api/v1/proxy/execute"
ADMIN = "test-admin-key"
REFUND = {
    "tool_name": "payment",
    "action": "refund",
    "arguments": {"transaction_id": "txn_1001", "customer_id": 101, "amount": 8000},
}


@pytest.fixture
def admin(monkeypatch, make_client):
    monkeypatch.setenv("AGENTGUARD_ADMIN_API_KEY_HASH", hash_api_key(ADMIN))
    get_settings.cache_clear()
    return make_client(headers={"X-Admin-Key": ADMIN})


@pytest.fixture
def pending(api, policy, admin):
    """A refund that policy sends for approval; returns its approval_id."""
    policy("approval_required", "Refunds over 5000 require human approval")
    resp = api.post(URL, json=REFUND | {"request_id": "ask-1"})
    assert resp.status_code == 202
    return resp.json()["approval_id"]


def _resubmit(api, approval_id, request_id="run-1", **changes):
    body = REFUND | {"request_id": request_id, "approval_id": approval_id}
    body["arguments"] = REFUND["arguments"] | changes
    return api.post(URL, json=body)


def test_approval_required_creates_pending_approval_without_running(admin, pending, tool_calls):
    listed = admin.get("/api/v1/approvals", params={"state": "pending"}).json()
    assert [a["id"] for a in listed] == [pending]
    assert listed[0]["arguments"]["amount"] == 8000
    assert listed[0]["reason"] == "Refunds over 5000 require human approval"
    assert tool_calls == []


def test_approved_request_runs_once(api, admin, pending, tool_calls, db):
    assert admin.post(f"/api/v1/approvals/{pending}/approve").json()["status"] == "approved"
    resp = _resubmit(api, pending)
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval_id"] == pending
    assert resp.json()["tool_result"]["refunded"] is True
    assert tool_calls == [("payment", "refund")]

    again = _resubmit(api, pending, request_id="run-2")
    assert again.status_code == 403
    assert again.json()["reason"] == "Approval is used"
    assert tool_calls == [("payment", "refund")]

    events = db.query(AuditEvent).filter(AuditEvent.approval_id.isnot(None)).all()
    assert {e.status for e in events} >= {"pending_approval", "executing", "success"}
    assert admin.get("/api/v1/audit/verify").json()["valid"] is True


def test_unapproved_request_does_not_run(api, pending, tool_calls):
    resp = _resubmit(api, pending)
    assert resp.status_code == 403
    assert resp.json()["reason"] == "Approval is pending"
    assert tool_calls == []


def test_rejected_request_does_not_run(api, admin, pending, tool_calls):
    assert admin.post(f"/api/v1/approvals/{pending}/reject").json()["status"] == "rejected"
    assert _resubmit(api, pending).json()["reason"] == "Approval is rejected"
    assert admin.post(f"/api/v1/approvals/{pending}/approve").status_code == 409
    assert tool_calls == []


def test_approval_cannot_authorize_a_modified_request(api, admin, pending, tool_calls):
    admin.post(f"/api/v1/approvals/{pending}/approve")
    resp = _resubmit(api, pending, amount=9000)
    assert resp.status_code == 403
    assert resp.json()["reason"] == "Approval does not match this request"
    assert tool_calls == []


def test_approval_is_bound_to_the_agent(admin, pending, db, make_client, tool_calls):
    admin.post(f"/api/v1/approvals/{pending}/approve")
    db.add(Agent(name="other", status="active", api_key_hash=hash_api_key("other-key")))
    db.commit()
    other = make_client(headers={"X-API-Key": "other-key"})
    assert _resubmit(other, pending).json()["reason"] == "Approval not found"
    assert tool_calls == []


def test_expired_approval_does_not_run(api, admin, pending, db, tool_calls):
    admin.post(f"/api/v1/approvals/{pending}/approve")
    approval = db.get(Approval, uuid.UUID(pending))
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert _resubmit(api, pending).json()["reason"] == "Approval is expired"
    assert admin.get(f"/api/v1/approvals/{pending}").json()["status"] == "expired"
    assert tool_calls == []


def test_policy_is_rechecked_on_resubmit(api, admin, pending, policy, tool_calls):
    admin.post(f"/api/v1/approvals/{pending}/approve")
    policy("deny", "Transaction is already fully refunded")
    resp = _resubmit(api, pending)
    assert resp.status_code == 403
    assert resp.json()["reason"] == "Transaction is already fully refunded"
    assert tool_calls == []


def test_unknown_approval_404_and_admin_key_required(admin, make_client):
    missing = "00000000-0000-0000-0000-000000000000"
    assert admin.get(f"/api/v1/approvals/{missing}").status_code == 404
    assert admin.post(f"/api/v1/approvals/{missing}/approve").status_code == 404
    assert make_client().get("/api/v1/approvals").status_code == 401
