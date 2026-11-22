import { describe, expect, it } from "vitest";
import type { AuditEvent } from "./api";
import { countFindings, isSecurityEvent, relative, shortHash } from "./lib";

function event(overrides: Partial<AuditEvent>): AuditEvent {
  return {
    seq: 1,
    created_at: "2026-11-22T08:00:00Z",
    request_id: "req_1",
    agent_id: "a1",
    agent_name: "support-agent",
    tool_name: "database",
    action: "read",
    event_type: "decision",
    decision: "allow",
    status: "executing",
    reason: null,
    policy_version: "v1",
    approval_id: null,
    firewall: [],
    request_fingerprint: "f",
    response_fingerprint: null,
    prev_hash: "0",
    event_hash: "h",
    ...overrides,
  };
}

describe("isSecurityEvent", () => {
  it("flags denials, blocks and firewall findings only", () => {
    expect(isSecurityEvent(event({}))).toBe(false);
    expect(isSecurityEvent(event({ decision: "deny", status: "blocked" }))).toBe(true);
    expect(isSecurityEvent(event({ decision: null, status: "blocked" }))).toBe(true);
    expect(
      isSecurityEvent(event({ firewall: [{ entity_type: "EMAIL", path: "x", action: "redact" }] })),
    ).toBe(true);
  });
});

describe("countFindings", () => {
  it("groups by entity type and action, most frequent first", () => {
    const f = (entity_type: string, action: "block" | "redact") => ({ entity_type, path: "p", action });
    const rows = countFindings([
      event({ firewall: [f("EMAIL", "redact"), f("PHONE", "redact")] }),
      event({ firewall: [f("EMAIL", "redact"), f("AWS_ACCESS_KEY", "block")] }),
    ]);
    expect(rows).toEqual([
      { type: "EMAIL", action: "redact", n: 2 },
      { type: "AWS_ACCESS_KEY", action: "block", n: 1 },
      { type: "PHONE", action: "redact", n: 1 },
    ]);
  });
});

describe("formatting", () => {
  it("writes relative times and short hashes", () => {
    const now = Date.parse("2026-11-22T08:00:00Z");
    expect(relative("2026-11-22T08:45:00Z", now)).toBe("in 45 minutes");
    expect(relative("2026-11-22T06:00:00Z", now)).toBe("2 hours ago");
    expect(shortHash("abcdef0123456789")).toBe("abcdef0123…");
    expect(shortHash(null)).toBe("none");
  });
});
