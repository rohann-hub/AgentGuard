"""API key authentication for agents and for the admin.

Only SHA-256 hashes of keys are stored. Keys are random 256-bit tokens, so an
unsalted hash is enough and lets us look agents up by hash.
"""

import hashlib
import hmac
import logging
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import SessionDep, SettingsDep
from app.database.models import Agent

logger = logging.getLogger(__name__)

_agent_key = APIKeyHeader(name="X-API-Key", auto_error=False)
_admin_key = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_api_key() -> str:
    return "ag_" + secrets.token_urlsafe(32)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "APIKey"}
    )


async def authenticate_agent(
    session: SessionDep, api_key: Annotated[str | None, Depends(_agent_key)]
) -> Agent:
    """Return the active agent that owns the presented key, or reject."""
    if not api_key:
        raise _unauthorized("Invalid or missing API key")
    try:
        agent = await session.scalar(
            select(Agent).where(Agent.api_key_hash == hash_api_key(api_key))
        )
    except SQLAlchemyError as exc:
        logger.error("Agent lookup failed, rejecting: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication unavailable"
        ) from exc
    if agent is None or agent.status != "active":
        raise _unauthorized("Invalid or missing API key")
    return agent


def require_admin(
    settings: SettingsDep, api_key: Annotated[str | None, Depends(_admin_key)]
) -> None:
    expected = settings.admin_api_key_hash
    if not (expected and api_key and hmac.compare_digest(hash_api_key(api_key), expected)):
        raise _unauthorized("Invalid or missing admin key")


AgentDep = Annotated[Agent, Depends(authenticate_agent)]
