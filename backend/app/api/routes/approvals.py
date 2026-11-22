"""Admin APIs for human approvals: list, inspect, approve, reject."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import SessionDep
from app.approvals.service import effective_status
from app.auth.api_keys import require_admin
from app.database.models import Approval
from app.schemas.admin import ApprovalOut

router = APIRouter(prefix="/approvals", tags=["approvals"], dependencies=[Depends(require_admin)])


def _out(a: Approval) -> ApprovalOut:
    return ApprovalOut(
        **{f: getattr(a, f) for f in ApprovalOut.model_fields if f != "status"},
        status=effective_status(a),
    )


async def _get(session: SessionDep, approval_id: uuid.UUID, lock: bool = False) -> Approval:
    approval = await session.get(Approval, approval_id, with_for_update=lock)
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
    return approval


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    session: SessionDep,
    state: Literal["pending", "approved", "rejected", "used", "expired"] | None = None,
) -> list[ApprovalOut]:
    rows = await session.scalars(select(Approval).order_by(Approval.created_at.desc()))
    out = [_out(a) for a in rows]
    return [a for a in out if state is None or a.status == state]


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(approval_id: uuid.UUID, session: SessionDep) -> ApprovalOut:
    return _out(await _get(session, approval_id))


async def _decide(session: SessionDep, approval_id: uuid.UUID, new_status: str) -> ApprovalOut:
    approval = await _get(session, approval_id, lock=True)
    current = effective_status(approval)
    if current != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Approval is {current}")
    approval.status = new_status
    approval.decided_at = datetime.now(UTC)
    await session.commit()
    return _out(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(approval_id: uuid.UUID, session: SessionDep) -> ApprovalOut:
    return await _decide(session, approval_id, "approved")


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(approval_id: uuid.UUID, session: SessionDep) -> ApprovalOut:
    return await _decide(session, approval_id, "rejected")
