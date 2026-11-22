"""Explicit registry of the tools AgentGuard may execute, keyed by (tool_name, action).

Only tools listed here can run. Names from requests are looked up, never imported
or called dynamically.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.tools import mock_tools


@dataclass(frozen=True)
class Tool:
    name: str
    action: str
    args_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[dict[str, Any]]]


_TOOLS = [
    Tool("database", "read", mock_tools.CustomerArgs, mock_tools.read_customer),
    Tool("database", "delete", mock_tools.CustomerArgs, mock_tools.delete_customer),
    Tool("payment", "refund", mock_tools.RefundArgs, mock_tools.refund),
]

REGISTRY: dict[tuple[str, str], Tool] = {(t.name, t.action): t for t in _TOOLS}


def get_tool(name: str, action: str) -> Tool | None:
    return REGISTRY.get((name, action))
