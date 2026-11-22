"""Admin overview for the dashboard: registered tools, live policy version and counts."""

import logging

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.dependencies import SessionDep, SettingsDep
from app.approvals.service import effective_status
from app.auth.api_keys import require_admin
from app.core.config import Settings
from app.database.models import Agent, Approval, AuditEvent
from app.schemas.admin import Overview, ToolOut
from app.tools.registry import REGISTRY

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/overview", tags=["overview"], dependencies=[Depends(require_admin)])

POLICY_VERSION_PATH = "/v1/data/agentguard/policy_version"


async def _policy_version(settings: Settings) -> str | None:
    """The version OPA has loaded now, or None if OPA cannot say."""
    try:
        async with httpx.AsyncClient(timeout=settings.dependency_timeout_seconds) as client:
            resp = await client.get(f"{settings.opa_url.rstrip('/')}{POLICY_VERSION_PATH}")
            resp.raise_for_status()
            version = resp.json().get("result")
            return version if isinstance(version, str) else None
    except Exception as exc:  # noqa: BLE001 - the overview still renders without it
        logger.warning("Could not read policy version: %s", exc)
        return None


async def _count(session: SessionDep, column) -> dict[str, int]:
    rows = await session.execute(select(column, func.count()).group_by(column))
    return {str(key): n for key, n in rows if key is not None}


@router.get("", response_model=Overview)
async def overview(session: SessionDep, settings: SettingsDep) -> Overview:
    approvals: dict[str, int] = {}
    for approval in await session.scalars(select(Approval)):
        state = effective_status(approval)
        approvals[state] = approvals.get(state, 0) + 1
    decisions = select(AuditEvent.decision).where(AuditEvent.event_type == "decision")
    return Overview(
        policy_version=await _policy_version(settings),
        tools=[
            ToolOut(name=t.name, action=t.action, verified=t.verify is not None)
            for t in REGISTRY.values()
        ],
        agents=await _count(session, Agent.status),
        approvals=approvals,
        decisions=await _count(session, decisions.subquery().c.decision),
    )
