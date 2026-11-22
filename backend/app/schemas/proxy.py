"""Request and response bodies for POST /api/v1/proxy/execute."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Decision = Literal["allow", "deny", "approval_required"]


class ProxyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Agent identity comes from the API key, never from the body.
    request_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    tool_name: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ProxyResponse(BaseModel):
    request_id: str
    status: Literal["success", "blocked", "pending_approval", "failed"]
    decision: Decision | None = None
    reason: str | None = None
    policy_version: str | None = None
    tool_result: dict[str, Any] | None = None
