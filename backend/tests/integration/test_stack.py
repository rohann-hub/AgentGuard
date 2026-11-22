"""Runs against the real Compose stack: `docker compose up -d` then `pytest -m integration`."""

import os

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
        json={"input": {"tool": "unknown_tool", "action": "anything"}},
        timeout=10,
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["allow"] is False
