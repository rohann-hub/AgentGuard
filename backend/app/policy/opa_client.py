"""Asks OPA for a decision. Any failure becomes a deny (fail closed)."""

import logging
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.schemas.proxy import Decision

logger = logging.getLogger(__name__)

DECISION_PATH = "/v1/data/agentguard/decision"


class PolicyDecision(BaseModel):
    status: Decision
    reason: str
    policy_version: str


class PolicyUnavailableError(Exception):
    """OPA could not be reached or returned something that is not a valid decision."""


async def evaluate(settings: Settings, policy_input: dict[str, Any]) -> PolicyDecision:
    try:
        async with httpx.AsyncClient(timeout=settings.dependency_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.opa_url.rstrip('/')}{DECISION_PATH}", json={"input": policy_input}
            )
            resp.raise_for_status()
            # A missing "result" means the policy is not loaded.
            return PolicyDecision.model_validate(resp.json()["result"])
    except Exception as exc:
        logger.error("Policy evaluation failed, denying: %s", exc)
        raise PolicyUnavailableError from exc
