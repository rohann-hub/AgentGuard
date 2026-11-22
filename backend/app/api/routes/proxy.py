"""POST /api/v1/proxy/execute: the single path from agents to tools.

Order: authenticate -> look up tool -> validate arguments -> OPA decision -> execute.
A tool runs only when OPA explicitly allows it.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.dependencies import SettingsDep
from app.auth.api_keys import AgentDep
from app.policy import opa_client
from app.schemas.proxy import ProxyRequest, ProxyResponse
from app.tools.errors import ToolError
from app.tools.registry import get_tool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/proxy", tags=["proxy"])

_STATUS_CODES = {
    "success": status.HTTP_200_OK,
    "pending_approval": status.HTTP_202_ACCEPTED,
    "blocked": status.HTTP_403_FORBIDDEN,
}


def _respond(body: ProxyResponse, code: int | None = None) -> JSONResponse:
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=code or _STATUS_CODES[body.status]
    )


@router.post(
    "/execute",
    response_model=ProxyResponse,
    response_model_exclude_none=True,
    responses={
        202: {"model": ProxyResponse, "description": "Pending approval; the tool did not run"},
        403: {"model": ProxyResponse, "description": "Denied by policy"},
        503: {"model": ProxyResponse, "description": "Policy engine unavailable (fail closed)"},
    },
)
async def execute(req: ProxyRequest, agent: AgentDep, settings: SettingsDep) -> JSONResponse:
    request_id = req.request_id or f"req_{uuid.uuid4().hex}"

    tool = get_tool(req.tool_name, req.action)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown tool or action")
    try:
        args = tool.args_model.model_validate(req.arguments)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            exc.errors(include_url=False, include_input=False, include_context=False),
        ) from exc

    policy_input = {
        "agent": agent,
        "tool_name": tool.name,
        "action": tool.action,
        "arguments": args.model_dump(),
    }
    try:
        decision = await opa_client.evaluate(settings, policy_input)
    except opa_client.PolicyUnavailableError:
        body = ProxyResponse(
            request_id=request_id,
            status="blocked",
            decision="deny",
            reason="Policy engine unavailable",
        )
        return _respond(body, status.HTTP_503_SERVICE_UNAVAILABLE)

    # Never log arguments: they may hold PII or secrets.
    logger.info(
        "request_id=%s agent=%s tool=%s.%s decision=%s",
        request_id,
        agent,
        tool.name,
        tool.action,
        decision.status,
    )

    if decision.status == "deny":
        body = ProxyResponse(
            request_id=request_id, status="blocked", decision="deny", reason=decision.reason
        )
        return _respond(body)
    if decision.status == "approval_required":
        # shortcut: nothing is stored yet; the Phase 6 approval workflow will persist it.
        body = ProxyResponse(
            request_id=request_id,
            status="pending_approval",
            decision="approval_required",
            reason=decision.reason,
        )
        return _respond(body)

    try:
        result = await asyncio.wait_for(tool.handler(args), timeout=settings.tool_timeout_seconds)
    except ToolError as exc:
        body = ProxyResponse(
            request_id=request_id, status="failed", decision="allow", reason=str(exc)
        )
        return _respond(body, status.HTTP_422_UNPROCESSABLE_ENTITY)
    except TimeoutError:
        body = ProxyResponse(
            request_id=request_id, status="failed", decision="allow", reason="Tool timed out"
        )
        return _respond(body, status.HTTP_504_GATEWAY_TIMEOUT)
    except Exception:
        logger.exception("request_id=%s tool %s.%s crashed", request_id, tool.name, tool.action)
        body = ProxyResponse(
            request_id=request_id, status="failed", decision="allow", reason="Tool execution failed"
        )
        return _respond(body, status.HTTP_500_INTERNAL_SERVER_ERROR)

    body = ProxyResponse(
        request_id=request_id, status="success", decision="allow", tool_result=result
    )
    return _respond(body)
