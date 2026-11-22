"""Agent authentication with one API key per agent.

Keys are configured as SHA-256 hashes (AGENTGUARD_AGENT_API_KEYS), so raw keys
are never stored. With no keys configured, every request is rejected.
"""

import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from app.api.dependencies import SettingsDep

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def authenticate_agent(
    settings: SettingsDep, api_key: Annotated[str | None, Depends(_api_key_header)]
) -> str:
    """Return the name of the agent that owns the presented key, or reject with 401."""
    if api_key:
        presented = hash_api_key(api_key)
        for agent, key_hash in settings.agent_api_keys.items():
            if hmac.compare_digest(presented, key_hash):
                return agent
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "APIKey"},
    )


AgentDep = Annotated[str, Depends(authenticate_agent)]
