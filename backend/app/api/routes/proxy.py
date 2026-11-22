"""POST /api/v1/proxy/execute: the single path from agents to tools.

authenticate -> look up tool -> validate arguments -> firewall (arguments)
-> verification (trusted data) -> OPA -> [approval] -> audit decision -> execute
-> firewall (response) -> audit result.

A tool runs only when OPA allows it (or a human approved this exact request), the
firewall did not block, and the decision was written to the audit ledger first.
"""

import asyncio
import logging
import uuid
from functools import partial
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import SessionDep, SettingsDep
from app.approvals import service as approvals
from app.audit import ledger
from app.auth.api_keys import AgentDep
from app.firewall.scanner import scan
from app.policy import opa_client
from app.schemas.proxy import FirewallFinding, ProxyRequest, ProxyResponse
from app.tools.errors import ToolError
from app.tools.registry import get_tool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/proxy", tags=["proxy"])

_STATUS_CODES = {
    "success": status.HTTP_200_OK,
    "pending_approval": status.HTTP_202_ACCEPTED,
    "blocked": status.HTTP_403_FORBIDDEN,
}


class _AuditUnavailableError(Exception):
    pass


def _invalid(exc: ValidationError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        exc.errors(include_url=False, include_input=False, include_context=False),
    )


@router.post(
    "/execute",
    response_model=ProxyResponse,
    response_model_exclude_none=True,
    responses={
        202: {"model": ProxyResponse, "description": "Pending approval; the tool did not run"},
        403: {
            "model": ProxyResponse,
            "description": "Blocked by policy, firewall or approval check",
        },
        409: {"description": "request_id already used by this agent"},
        503: {"model": ProxyResponse, "description": "Policy engine or audit unavailable"},
    },
)
async def execute(
    req: ProxyRequest, agent: AgentDep, settings: SettingsDep, session: SessionDep
) -> JSONResponse:
    request_id = req.request_id or f"req_{uuid.uuid4().hex}"

    tool = get_tool(req.tool_name, req.action)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown tool or action")
    try:
        args: BaseModel = tool.args_model.model_validate(req.arguments)
    except ValidationError as exc:
        raise _invalid(exc) from exc

    arg_scan = scan(args.model_dump(), settings.firewall_actions, "arguments")
    findings = list(arg_scan.findings)
    record = partial(
        ledger.append,
        session,
        agent=agent,
        request_id=request_id,
        tool_name=tool.name,
        action=tool.action,
        request_fingerprint=ledger.fingerprint(arg_scan.data),
    )

    async def audit(event_type: str, reason: str | None, **fields: Any) -> None:
        # Reasons can echo tool errors, so they pass through the firewall before storage.
        safe_reason = scan(reason, settings.firewall_actions, "reason").data
        try:
            await record(
                event_type=event_type,
                reason=safe_reason,
                firewall=[vars(f) for f in findings],
                **fields,
            )
            await session.commit()
        except ledger.DuplicateRequestError:
            raise HTTPException(status.HTTP_409_CONFLICT, "request_id already used") from None
        except SQLAlchemyError as exc:
            logger.error("request_id=%s audit write failed: %s", request_id, exc)
            raise _AuditUnavailableError from exc

    async def finish(
        body: ProxyResponse, code: int | None = None, event_type: str = "decision"
    ) -> JSONResponse:
        body.firewall = [FirewallFinding(**vars(f)) for f in findings] or None
        try:
            await audit(
                event_type,
                **body.model_dump(
                    include={"decision", "status", "reason", "policy_version", "approval_id"}
                ),
                response_fingerprint=(
                    ledger.fingerprint(body.tool_result) if body.tool_result is not None else None
                ),
            )
        except _AuditUnavailableError:
            # Nothing leaves the gateway unaudited, including a result the tool already produced.
            reason = "Audit unavailable"
            if event_type == "execution":
                reason += "; the tool ran but its result was withheld"
            body = ProxyResponse(request_id=request_id, status="blocked", reason=reason)
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            body.model_dump(mode="json", exclude_none=True),
            status_code=code or _STATUS_CODES[body.status],
        )

    if arg_scan.blocked:
        return await finish(
            ProxyResponse(
                request_id=request_id, status="blocked", reason="Sensitive data in arguments"
            )
        )
    if findings:
        try:
            args = tool.args_model.model_validate(arg_scan.data)
        except ValidationError as exc:
            raise _invalid(exc) from exc
    arguments = args.model_dump()

    verification: dict[str, Any] = {}
    if tool.verify:
        try:
            verification = await tool.verify(
                args, session=session, exclude_approval_id=req.approval_id
            )
        except Exception:
            logger.exception("request_id=%s verification failed", request_id)
            body = ProxyResponse(
                request_id=request_id,
                status="blocked",
                decision="deny",
                reason="Verification unavailable",
            )
            return await finish(body, status.HTTP_503_SERVICE_UNAVAILABLE, event_type="error")

    policy_input = {
        "agent": agent.name,
        "tool_name": tool.name,
        "action": tool.action,
        "arguments": arguments,
        "firewall": sorted({f.entity_type for f in findings}),
        "verification": verification,
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
        # "error" events do not consume the request_id, so the agent can retry.
        return await finish(body, status.HTTP_503_SERVICE_UNAVAILABLE, event_type="error")

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
        return await finish(reply(status="blocked", reason=decision.reason))

    approval_id = None
    if decision.status == "approval_required":
        if req.approval_id is None:
            approval = await approvals.create(
                session,
                agent=agent,
                request_id=request_id,
                tool_name=tool.name,
                action=tool.action,
                arguments=arguments,
                reason=decision.reason,
                ttl_seconds=settings.approval_ttl_seconds,
            )
            body = reply(status="pending_approval", reason=decision.reason, approval_id=approval.id)
            return await finish(body)
        rhash = approvals.request_hash(agent, tool.name, tool.action, arguments)
        try:
            approval_id = (await approvals.redeem(session, req.approval_id, agent, rhash)).id
        except approvals.ApprovalError as exc:
            return await finish(
                reply(status="blocked", reason=str(exc), approval_id=req.approval_id)
            )

    # The decision (and any approval use) must be on the ledger before the tool runs.
    try:
        await audit(
            "decision",
            decision=decision.status,
            status="executing",
            reason=decision.reason,
            policy_version=decision.policy_version,
            approval_id=approval_id,
        )
    except _AuditUnavailableError:
        body = ProxyResponse(request_id=request_id, status="blocked", reason="Audit unavailable")
        return JSONResponse(
            body.model_dump(exclude_none=True), status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    reply = partial(reply, approval_id=approval_id)
    done = partial(finish, event_type="execution")

    try:
        result = await asyncio.wait_for(tool.handler(args), timeout=settings.tool_timeout_seconds)
    except ToolError as exc:
        return await done(
            reply(status="failed", reason=str(exc)), status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    except TimeoutError:
        return await done(
            reply(status="failed", reason="Tool timed out"), status.HTTP_504_GATEWAY_TIMEOUT
        )
    except Exception:
        logger.exception("request_id=%s tool %s.%s crashed", request_id, tool.name, tool.action)
        body = reply(status="failed", reason="Tool execution failed")
        return await done(body, status.HTTP_500_INTERNAL_SERVER_ERROR)

    result_scan = scan(result, settings.firewall_actions, "tool_result")
    findings += result_scan.findings
    if result_scan.blocked:
        return await done(reply(status="blocked", reason="Sensitive data in tool response"))
    return await done(reply(status="success", tool_result=result_scan.data))
