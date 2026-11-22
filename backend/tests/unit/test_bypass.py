"""Attempts to get around the gateway. Every one must fail without running a tool."""

import json

import pytest

from app.auth.api_keys import hash_api_key
from app.core.config import get_settings
from tests.unit.conftest import AGENT_KEY

URL = "/api/v1/proxy/execute"
READ = {"tool_name": "database", "action": "read", "arguments": {"customer_id": 101}}


# --- identity ---


@pytest.mark.parametrize("field", ["agent_id", "agent", "agent_name"])
def test_identity_cannot_come_from_the_body(api, field):
    assert api.post(URL, json=READ | {field: "admin"}).status_code == 422


def test_identity_headers_are_ignored(api, policy):
    calls = policy("allow")
    api.post(URL, json=READ, headers={"X-Agent-Id": "admin", "X-Forwarded-User": "admin"})
    assert calls[0]["agent"] == "support-agent"


def test_api_key_in_query_string_is_not_accepted(api):
    del api.headers["X-API-Key"]
    assert api.post(URL, params={"api_key": AGENT_KEY}, json=READ).status_code == 401


def test_agent_key_does_not_open_admin_endpoints(api, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_ADMIN_API_KEY_HASH", hash_api_key("real-admin"))
    get_settings.cache_clear()
    for path in ("/api/v1/agents", "/api/v1/audit", "/api/v1/approvals"):
        assert api.get(path, headers={"X-Admin-Key": AGENT_KEY}).status_code == 401


# --- tool lookup ---


@pytest.mark.parametrize(
    "name",
    ["Database", "DATABASE", " database", "database ", "databаse", "database\x00", "../database"],
)
def test_lookalike_tool_names_are_unknown(api, policy, tool_calls, name):
    calls = policy("allow")
    assert api.post(URL, json=READ | {"tool_name": name}).status_code == 404
    assert calls == [] and tool_calls == []


@pytest.mark.parametrize("action", ["Read", "read ", "read;delete", "__init__", "handler"])
def test_lookalike_actions_are_unknown(api, policy, action):
    policy("allow")
    assert api.post(URL, json=READ | {"action": action}).status_code == 404


# --- argument validation ---


@pytest.mark.parametrize(
    "arguments",
    [
        {"customer_id": 101, "nested": {"customer_id": 102}},
        {"customer_id": [101, 102]},
        {"customer_id": "101; DROP TABLE agents"},
        {"customer_id": 1e30},
        {"customer_id": True},
    ],
)
def test_smuggled_arguments_are_rejected(api, policy, tool_calls, arguments):
    calls = policy("allow")
    assert api.post(URL, json=READ | {"arguments": arguments}).status_code == 422
    assert calls == [] and tool_calls == []


def test_arguments_must_be_an_object(api):
    assert api.post(URL, json=READ | {"arguments": [101]}).status_code == 422


def test_form_encoded_body_is_rejected(api):
    assert api.post(URL, data={"tool_name": "database", "action": "read"}).status_code == 422


def test_refund_customer_id_is_checked_against_the_transaction(api, policy):
    calls = policy("allow")
    body = {
        "tool_name": "payment",
        "action": "refund",
        "arguments": {"transaction_id": "txn_1009", "customer_id": 102, "amount": 10},
    }
    api.post(URL, json=body)
    assert calls[0]["verification"]["customer_matches"] is False


# --- request size ---


def test_oversized_body_is_rejected_before_processing(api, policy, tool_calls):
    calls = policy("allow")
    big = READ | {"arguments": {"customer_id": 101, "pad": "x" * 70_000}}
    resp = api.post(URL, json=big)
    assert resp.status_code == 413
    assert calls == [] and tool_calls == []


def test_oversized_chunked_body_is_rejected(api):
    body = json.dumps(READ | {"arguments": {"pad": "x" * 70_000}}).encode()

    def chunks():
        for i in range(0, len(body), 8192):
            yield body[i : i + 8192]

    resp = api.post(URL, content=chunks(), headers={"content-type": "application/json"})
    assert resp.status_code == 413


def test_invalid_content_length_is_rejected(api):
    resp = api.post(URL, content=b"{}", headers={"content-length": "abc"})
    assert resp.status_code == 400


def test_body_under_the_limit_is_accepted(api, policy):
    policy("allow")
    assert api.post(URL, json=READ).status_code == 200
