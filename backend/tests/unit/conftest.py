"""Fixtures for proxy-level tests: a seeded agent, a fake OPA, and a spy on every tool."""

import dataclasses

import pytest

from app.auth.api_keys import hash_api_key
from app.database.models import Agent
from app.policy import opa_client
from app.policy.opa_client import PolicyDecision
from app.tools.registry import REGISTRY

AGENT_KEY = "test-key-support"


@pytest.fixture
def api(db, make_client):
    db.add(Agent(name="support-agent", status="active", api_key_hash=hash_api_key(AGENT_KEY)))
    db.add(Agent(name="old-agent", status="revoked", api_key_hash=hash_api_key("revoked-key")))
    db.commit()
    return make_client(headers={"X-API-Key": AGENT_KEY})


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
