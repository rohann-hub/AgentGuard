"""Scans tool arguments and responses, then redacts or blocks per configured actions.

Findings record the entity type and where it was found, never the value.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from app.firewall.detectors import SECRET_FIELD_NAME, SECRET_TYPES, find

Action = Literal["block", "redact", "allow"]


@dataclass(frozen=True)
class Finding:
    entity_type: str
    path: str
    action: Action


@dataclass
class ScanResult:
    data: Any  # with redactions applied
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.action == "block" for f in self.findings)


def default_action(entity_type: str) -> Action:
    return "block" if entity_type in SECRET_TYPES else "redact"


def scan(data: Any, overrides: dict[str, Action], root: str) -> ScanResult:
    findings: list[Finding] = []

    def action_for(entity: str) -> Action:
        return overrides.get(entity, default_action(entity))

    def walk(value: Any, path: str, key: str | None) -> Any:
        if isinstance(value, dict):
            return {k: walk(v, f"{path}.{k}", str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, f"{path}[{i}]", key) for i, v in enumerate(value)]
        if not isinstance(value, str) or not value:
            return value  # shortcut: only strings are scanned; numbers pass through.
        if key and SECRET_FIELD_NAME.search(key):
            act = action_for("SECRET_FIELD")
            findings.append(Finding("SECRET_FIELD", path, act))
            return "[REDACTED:SECRET_FIELD]" if act != "allow" else value
        out, last = [], 0
        for entity, start, end in find(value):
            act = action_for(entity)
            findings.append(Finding(entity, path, act))
            if act != "allow":
                out += [value[last:start], f"[REDACTED:{entity}]"]
                last = end
        return "".join(out) + value[last:] if out else value

    return ScanResult(walk(data, root, None), findings)
