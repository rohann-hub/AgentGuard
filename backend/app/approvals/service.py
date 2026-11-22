"""Human approvals for requests that policy marks approval_required.

An approval is bound to the agent, tool, action and exact (redacted) arguments through
request_hash, expires, and can be used once.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ledger import fingerprint
from app.database.models import Agent, Approval


class ApprovalError(Exception):
    """The approval cannot authorize this request. The message is safe to return."""


def utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def request_hash(agent: Agent, tool_name: str, action: str, arguments: dict[str, Any]) -> str:
    return fingerprint(
        {"agent_id": str(agent.id), "tool": tool_name, "action": action, "arguments": arguments}
    )


def effective_status(approval: Approval) -> str:
    if approval.status in ("pending", "approved") and utc(approval.expires_at) <= datetime.now(UTC):
        return "expired"
    return approval.status


async def create(
    session: AsyncSession,
    *,
    agent: Agent,
    request_id: str,
    tool_name: str,
    action: str,
    arguments: dict[str, Any],
    reason: str,
    ttl_seconds: int,
) -> Approval:
    approval = Approval(
        agent_id=agent.id,
        request_id=request_id,
        tool_name=tool_name,
        action=action,
        arguments=arguments,
        request_hash=request_hash(agent, tool_name, action, arguments),
        reason=reason,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )
    session.add(approval)
    await session.flush()
    return approval


async def redeem(
    session: AsyncSession, approval_id: uuid.UUID, agent: Agent, rhash: str
) -> Approval:
    """Mark an approved, matching, unexpired approval as used. Caller commits."""
    approval = await session.get(Approval, approval_id, with_for_update=True)
    if approval is None or approval.agent_id != agent.id:
        raise ApprovalError("Approval not found")
    if approval.request_hash != rhash:
        raise ApprovalError("Approval does not match this request")
    state = effective_status(approval)
    if state != "approved":
        raise ApprovalError(f"Approval is {state}")
    approval.status = "used"
    await session.flush()
    return approval


async def has_open(
    session: AsyncSession,
    tool_name: str,
    action: str,
    field: str,
    value: Any,
    exclude: uuid.UUID | None = None,
) -> bool:
    """Whether a pending or approved, unexpired approval exists with arguments[field] == value."""
    # shortcut: filters in Python; add an indexed column once approvals grow large.
    rows = await session.scalars(
        select(Approval).where(
            Approval.tool_name == tool_name,
            Approval.action == action,
            Approval.status.in_(("pending", "approved")),
        )
    )
    return any(
        a.id != exclude and a.arguments.get(field) == value and effective_status(a) != "expired"
        for a in rows
    )
