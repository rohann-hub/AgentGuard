"""Hash-chained audit ledger.

event_hash = SHA-256(prev_hash + canonical JSON of the event). Changing, removing or
reordering any stored event breaks verification from that event on.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Agent, AuditEvent

GENESIS = "0" * 64
_LOCK_ID = 0x41_47_41_55_44  # any constant; serializes appends across app instances


class DuplicateRequestError(Exception):
    """This agent already used this request_id."""


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint(data: Any) -> str:
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def _ts(dt: datetime) -> str:
    # SQLite returns naive datetimes; Postgres returns aware ones in the session time zone.
    return (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)).isoformat()


def _hashed_fields(e: AuditEvent) -> dict[str, Any]:
    fields = {
        "seq": e.seq,
        "created_at": _ts(e.created_at),
        "request_id": e.request_id,
        "agent_id": str(e.agent_id),
        "agent_name": e.agent_name,
        "tool_name": e.tool_name,
        "action": e.action,
        "event_type": e.event_type,
        "decision": e.decision,
        "status": e.status,
        "reason": e.reason,
        "policy_version": e.policy_version,
        "firewall": e.firewall,
        "request_fingerprint": e.request_fingerprint,
        "response_fingerprint": e.response_fingerprint,
    }
    # Added in Phase 6. Hashed only when set, so events written before it still verify.
    if e.approval_id is not None:
        fields["approval_id"] = str(e.approval_id)
    return fields


def compute_hash(prev_hash: str, event: AuditEvent) -> str:
    return hashlib.sha256((prev_hash + canonical(_hashed_fields(event))).encode()).hexdigest()


async def append(
    session: AsyncSession,
    *,
    agent: Agent,
    approval_id: uuid.UUID | None = None,
    response_fingerprint: str | None = None,
    **fields: Any,
) -> AuditEvent:
    """Add the next event to the chain. Flushes but does not commit: the caller commits,
    so the event lands atomically with whatever else the caller changed."""
    if session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _LOCK_ID})
    last = await session.scalar(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1))
    event = AuditEvent(
        seq=(last.seq + 1) if last else 1,
        created_at=datetime.now(UTC),
        agent_id=agent.id,
        agent_name=agent.name,
        approval_id=approval_id,
        response_fingerprint=response_fingerprint,
        prev_hash=last.event_hash if last else GENESIS,
        **fields,
    )
    event.event_hash = compute_hash(event.prev_hash, event)
    session.add(event)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "request_id" in str(exc.orig):  # the (agent_id, request_id) unique index
            raise DuplicateRequestError from exc
        raise
    return event


@dataclass
class Verification:
    valid: bool
    events: int
    first_invalid_seq: int | None = None


async def verify(session: AsyncSession) -> Verification:
    prev, count = GENESIS, 0
    async for event in await session.stream_scalars(select(AuditEvent).order_by(AuditEvent.seq)):
        count += 1
        if (
            event.seq != count
            or event.prev_hash != prev
            or event.event_hash != compute_hash(prev, event)
        ):
            return Verification(False, count, event.seq)
        prev = event.event_hash
    return Verification(True, count)
