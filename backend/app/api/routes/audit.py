"""Admin APIs over the audit ledger: list events and verify the hash chain."""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.dependencies import SessionDep
from app.audit import ledger
from app.auth.api_keys import require_admin
from app.database.models import AuditEvent
from app.schemas.admin import AuditEventOut, AuditVerification

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[AuditEventOut])
async def list_events(
    session: SessionDep,
    request_id: str | None = None,
    agent_name: str | None = None,
    decision: str | None = None,
    event_type: Literal["decision", "execution", "error"] | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AuditEvent]:
    query = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
    filters = {
        AuditEvent.request_id: request_id,
        AuditEvent.agent_name: agent_name,
        AuditEvent.decision: decision,
        AuditEvent.event_type: event_type,
    }
    for column, value in filters.items():
        if value:
            query = query.where(column == value)
    return list(await session.scalars(query))


@router.get("/verify", response_model=AuditVerification)
async def verify(session: SessionDep) -> AuditVerification:
    return AuditVerification(**asdict(await ledger.verify(session)))
