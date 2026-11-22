"""Liveness and readiness endpoints.

/health        - the process is up. Never touches dependencies.
/health/ready  - PostgreSQL and OPA both answer. Returns 503 if either does not,
                 so orchestrators stop routing traffic to an instance that cannot
                 make policy decisions (fail closed).
"""

import asyncio
import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.api.dependencies import SettingsDep
from app.core.config import Settings
from app.database.connection import check_database

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    env: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckStatus]


async def check_opa(settings: Settings) -> None:
    async with httpx.AsyncClient(timeout=settings.dependency_timeout_seconds) as client:
        resp = await client.get(f"{settings.opa_url.rstrip('/')}/health")
        resp.raise_for_status()


async def _run_check(name: str, check, timeout: float) -> CheckStatus:
    try:
        await asyncio.wait_for(check(), timeout=timeout)
        return "ok"
    except Exception as exc:  # noqa: BLE001 - any failure means not ready
        logger.warning("Readiness check %s failed: %s", name, exc)
        return "error"


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok", service=settings.app_name, version=settings.version, env=settings.env
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(response: Response, settings: SettingsDep) -> ReadinessResponse:
    timeout = settings.dependency_timeout_seconds + 1
    db, opa = await asyncio.gather(
        _run_check("database", check_database, timeout),
        _run_check("opa", lambda: check_opa(settings), timeout),
    )
    checks: dict[str, CheckStatus] = {"database": db, "opa": opa}
    ready = all(v == "ok" for v in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "not_ready", checks=checks)
