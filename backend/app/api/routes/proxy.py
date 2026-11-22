"""POST /api/v1/proxy/execute: the single path from agents to tools.

Order: authenticate -> look up tool -> validate arguments -> firewall scan of arguments
-> OPA decision -> execute -> firewall scan of the response.
A tool runs only when OPA explicitly allows it and the firewall did not block.
"""

import asyncio
import logging
import uuid
from functools import partial

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.api.dependencies import SettingsDep
from app.auth.api_keys import AgentDep
from app.firewall.scanner import Finding, scan
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


def _invalid(exc: ValidationError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        exc.errors(include_url=False, include_input=False, include_context=False),
    )


def _findings(findings: list[Finding]) -> list[dict] | None:
    return [vars(f) for f in findings] or None


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
        args: BaseModel = tool.args_model.model_validate(req.arguments)
    except ValidationError as exc:
        raise _invalid(exc) from exc

    arg_scan = scan(args.model_dump(), settings.firewall_actions, "arguments")
    findings = arg_scan.findings
    if arg_scan.blocked:
        body = ProxyResponse(
            request_id=request_id,
            status="blocked",
            reason="Sensitive data in arguments",
            firewall=_findings(findings),
        )
        return _respond(body)
    if findings:
        try:
            args = tool.args_model.model_validate(arg_scan.data)
        except ValidationError as exc:
            raise _invalid(exc) from exc

    policy_input = {
        "agent": agent.name,
        "tool_name": tool.name,
        "action": tool.action,
        "arguments": args.model_dump(),
        "firewall": sorted({f.entity_type for f in findings}),
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
        "request_id=%s agent=%s tool=%s.%s decision=%s policy_version=%s",
        request_id,
        agent.name,
        tool.name,
        tool.action,
        decision.status,
        decision.policy_version,
    )
    reply = partial(
        ProxyResponse,
        request_id=request_id,
        decision=decision.status,
        policy_version=decision.policy_version,
    )

    if decision.status == "deny":
        return _respond(reply(status="blocked", reason=decision.reason))
    if decision.status == "approval_required":
        # shortcut: nothing is stored yet; the Phase 6 approval workflow will persist it.
        return _respond(reply(status="pending_approval", reason=decision.reason))

    try:
        result = await asyncio.wait_for(tool.handler(args), timeout=settings.tool_timeout_seconds)
    except ToolError as exc:
        return _respond(
            reply(status="failed", reason=str(exc)), status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    except TimeoutError:
        return _respond(
            reply(status="failed", reason="Tool timed out"), status.HTTP_504_GATEWAY_TIMEOUT
        )
    except Exception:
        logger.exception("request_id=%s tool %s.%s crashed", request_id, tool.name, tool.action)
        body = reply(status="failed", reason="Tool execution failed")
        return _respond(body, status.HTTP_500_INTERNAL_SERVER_ERROR)

    result_scan = scan(result, settings.firewall_actions, "tool_result")
    findings = findings + result_scan.findings
    if result_scan.blocked:
        body = reply(
            status="blocked", reason="Sensitive data in tool response", firewall=_findings(findings)
        )
        return _respond(body)
    return _respond(
        reply(status="success", tool_result=result_scan.data, firewall=_findings(findings))
    )
