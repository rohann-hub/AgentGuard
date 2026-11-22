"""Agent registry: register, list, inspect and revoke agents. Admin key required."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import SessionDep
from app.auth.api_keys import hash_api_key, new_api_key, require_admin
from app.database.models import Agent
from app.schemas.agents import AgentCreate, AgentCreated, AgentOut

router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(require_admin)])


async def _get(session: SessionDep, agent_id: uuid.UUID) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentCreated)
async def register_agent(body: AgentCreate, session: SessionDep) -> AgentCreated:
    api_key = new_api_key()
    agent = Agent(
        name=body.name,
        description=body.description,
        status="active",
        api_key_hash=hash_api_key(api_key),
    )
    session.add(agent)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Agent name already exists") from exc
    await session.refresh(agent)
    return AgentCreated(**AgentOut.model_validate(agent).model_dump(), api_key=api_key)


@router.get("", response_model=list[AgentOut])
async def list_agents(session: SessionDep) -> list[Agent]:
    return list(await session.scalars(select(Agent).order_by(Agent.created_at, Agent.name)))


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: uuid.UUID, session: SessionDep) -> Agent:
    return await _get(session, agent_id)


@router.post("/{agent_id}/revoke", response_model=AgentOut)
async def revoke_agent(agent_id: uuid.UUID, session: SessionDep) -> Agent:
    agent = await _get(session, agent_id)
    agent.status = "revoked"
    await session.commit()
    return agent
