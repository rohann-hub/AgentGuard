import dataclasses
import json

import pytest
from sqlalchemy.exc import OperationalError

from app.audit import ledger
from app.auth.api_keys import hash_api_key
from app.database.models import Agent, AuditEvent
from app.policy import opa_client
from app.policy.opa_client import PolicyUnavailableError
from app.tools.errors import ToolError
from app.tools.registry import REGISTRY

URL = "/api/v1/proxy/execute"
READ = {"tool_name": "database", "action": "read", "arguments": {"customer_id": 101}}
SECRET = "AKIAIOSFODNN7EXAMPLE"


def _events(db) -> list[AuditEvent]:
    db.expire_all()
    return db.query(AuditEvent).order_by(AuditEvent.seq).all()


def _db_down(*_a, **_k):
    raise OperationalError("INSERT", {}, ConnectionError("down"))


# --- what gets recorded ---


def test_allowed_call_records_decision_before_and_result_after(api, policy, admin):
    policy("allow", "reads ok")
    assert api.post(URL, json=READ | {"request_id": "r1"}).status_code == 200

    decision, execution = admin.get("/api/v1/audit", params={"request_id": "r1"}).json()[::-1]
    assert (decision["event_type"], decision["status"]) == ("decision", "executing")
    assert (execution["event_type"], execution["status"]) == ("execution", "success")
    assert decision["policy_version"] == execution["policy_version"] == "test-1"
    assert execution["response_fingerprint"] and execution["prev_hash"] == decision["event_hash"]
    assert [f["entity_type"] for f in execution["firewall"]] == ["EMAIL", "PHONE"]


@pytest.mark.parametrize(
    ("decision", "status"), [("deny", "blocked"), ("approval_required", "pending_approval")]
)
def test_non_executed_decisions_record_one_event(api, policy, db, decision, status):
    policy(decision)
    api.post(URL, json=READ)
    assert [(e.event_type, e.status) for e in _events(db)] == [("decision", status)]


def test_firewall_block_is_recorded(api, policy, db):
    policy("allow")
    note = {"transaction_id": "txn_1009", "customer_id": 101, "amount": 5, "note": SECRET}
    api.post(URL, json={"tool_name": "payment", "action": "refund", "arguments": note})
    (event,) = _events(db)
    assert event.status == "blocked" and event.decision is None
    assert event.firewall == [
        {"entity_type": "AWS_ACCESS_KEY", "path": "arguments.note", "action": "block"}
    ]


def test_tool_failure_is_recorded(api, policy, db):
    policy("allow")
    api.post(URL, json=READ | {"arguments": {"customer_id": 999}})
    assert [e.status for e in _events(db)] == ["executing", "failed"]
    assert _events(db)[1].reason == "Customer 999 not found"


# --- fail closed ---


def test_tool_does_not_run_when_pre_execution_audit_fails(api, policy, tool_calls, monkeypatch):
    policy("allow")
    monkeypatch.setattr(ledger, "append", _db_down)
    resp = api.post(URL, json=READ)
    assert resp.status_code == 503
    assert resp.json()["reason"] == "Audit unavailable"
    assert tool_calls == []


def test_result_is_withheld_when_post_execution_audit_fails(api, policy, tool_calls, monkeypatch):
    policy("allow")
    real, calls = ledger.append, []

    async def fail_second(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            _db_down()
        return await real(*a, **k)

    monkeypatch.setattr(ledger, "append", fail_second)
    resp = api.post(URL, json=READ)
    assert resp.status_code == 503
    assert "result was withheld" in resp.json()["reason"]
    assert "tool_result" not in resp.json() and "Asha" not in resp.text
    assert tool_calls == [("database", "read")]


def test_blocked_decision_still_fails_closed_without_audit(api, policy, monkeypatch):
    policy("deny")
    monkeypatch.setattr(ledger, "append", _db_down)
    assert api.post(URL, json=READ).status_code == 503


# --- duplicate protection ---


def test_duplicate_request_id_runs_the_tool_once(api, policy, tool_calls):
    policy("allow")
    first = api.post(URL, json=READ | {"request_id": "dup-1"})
    retry = api.post(URL, json=READ | {"request_id": "dup-1"})
    assert first.status_code == 200
    assert retry.status_code == 409
    assert tool_calls == [("database", "read")]


def test_duplicate_of_a_denied_request_is_rejected(api, policy):
    policy("deny")
    api.post(URL, json=READ | {"request_id": "dup-2"})
    policy("allow")  # even if policy changes, the request_id was already decided
    assert api.post(URL, json=READ | {"request_id": "dup-2"}).status_code == 409


def test_retry_allowed_after_policy_engine_outage(api, policy, monkeypatch, db):
    async def down(*_):
        raise PolicyUnavailableError

    monkeypatch.setattr(opa_client, "evaluate", down)
    assert api.post(URL, json=READ | {"request_id": "r-opa"}).status_code == 503
    policy("allow")
    assert api.post(URL, json=READ | {"request_id": "r-opa"}).status_code == 200
    assert [e.event_type for e in _events(db)] == ["error", "decision", "execution"]


def test_request_ids_are_per_agent(api, policy, db, make_client):
    db.add(Agent(name="other", status="active", api_key_hash=hash_api_key("other-key")))
    db.commit()
    policy("allow")
    assert api.post(URL, json=READ | {"request_id": "shared"}).status_code == 200
    other = make_client(headers={"X-API-Key": "other-key"})
    assert other.post(URL, json=READ | {"request_id": "shared"}).status_code == 200


# --- privacy ---


def test_audit_never_stores_raw_secrets_or_pii(api, policy, monkeypatch, db, admin):
    policy("allow")

    async def leaky(_args):
        raise ToolError(f"failed for asha.rao@example.com using {SECRET}")

    key = ("payment", "refund")
    monkeypatch.setitem(REGISTRY, key, dataclasses.replace(REGISTRY[key], handler=leaky))
    note = {
        "transaction_id": "txn_1009",
        "customer_id": 101,
        "amount": 5,
        "note": "email asha.rao@example.com",
    }
    api.post(URL, json={"tool_name": "payment", "action": "refund", "arguments": note})
    api.post(URL, json=READ)  # response holds email and phone

    stored = json.dumps(
        [{c: str(getattr(e, c)) for c in e.__table__.columns.keys()} for e in _events(db)]
    )
    listed = admin.get("/api/v1/audit").text
    for raw in ("asha.rao@example.com", "98765 43210", SECRET, "Asha Rao"):
        assert raw not in stored and raw not in listed
    assert "[REDACTED:EMAIL]" in stored  # the redacted tool error reason


# --- tamper detection ---


def _make_events(api, policy, n=3):
    policy("deny")
    for i in range(n):
        api.post(URL, json=READ | {"request_id": f"t{i}"})


def test_verify_reports_a_valid_chain(api, policy, admin):
    _make_events(api, policy)
    assert admin.get("/api/v1/audit/verify").json() == {
        "valid": True,
        "events": 3,
        "first_invalid_seq": None,
    }


def test_verify_detects_a_modified_event(api, policy, admin, db):
    _make_events(api, policy)
    event = _events(db)[1]
    event.status = "success"
    db.commit()
    assert admin.get("/api/v1/audit/verify").json() == {
        "valid": False,
        "events": 2,
        "first_invalid_seq": 2,
    }


def test_verify_detects_a_deleted_event(api, policy, admin, db):
    _make_events(api, policy)
    db.delete(_events(db)[0])
    db.commit()
    body = admin.get("/api/v1/audit/verify").json()
    assert body["valid"] is False and body["first_invalid_seq"] == 2


def test_audit_endpoints_need_admin_key(make_client):
    c = make_client()
    assert c.get("/api/v1/audit").status_code == 401
    assert c.get("/api/v1/audit/verify").status_code == 401
