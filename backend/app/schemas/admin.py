"""Response bodies for the admin audit and approval APIs."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seq: int
    created_at: datetime
    request_id: str
    agent_id: uuid.UUID
    agent_name: str
    tool_name: str
    action: str
    event_type: str
    decision: str | None
    status: str
    reason: str | None
    policy_version: str | None
    approval_id: uuid.UUID | None
    firewall: list[dict[str, Any]]
    request_fingerprint: str
    response_fingerprint: str | None
    prev_hash: str
    event_hash: str


class AuditVerification(BaseModel):
    valid: bool
    events: int
    first_invalid_seq: int | None = None


class ApprovalOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    request_id: str
    tool_name: str
    action: str
    arguments: dict[str, Any]
    reason: str
    status: str
    expires_at: datetime
    decided_at: datetime | None
    created_at: datetime
