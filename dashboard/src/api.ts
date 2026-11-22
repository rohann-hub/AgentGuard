// Typed client for the AgentGuard admin APIs. The admin key lives only in the
// closure returned by createApi: never in storage, cookies or the URL.

export type Decision = "allow" | "deny" | "approval_required";

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  status: "active" | "revoked";
  created_at: string;
}

export interface AgentCreated extends Agent {
  api_key: string;
}

export interface Finding {
  entity_type: string;
  path: string;
  action: "block" | "redact" | "allow";
}

export interface AuditEvent {
  seq: number;
  created_at: string;
  request_id: string;
  agent_id: string;
  agent_name: string;
  tool_name: string;
  action: string;
  event_type: "decision" | "execution" | "error";
  decision: Decision | null;
  status: string;
  reason: string | null;
  policy_version: string | null;
  approval_id: string | null;
  firewall: Finding[];
  request_fingerprint: string;
  response_fingerprint: string | null;
  prev_hash: string;
  event_hash: string;
}

export interface Verification {
  valid: boolean;
  events: number;
  first_invalid_seq: number | null;
}

export type ApprovalState = "pending" | "approved" | "rejected" | "used" | "expired";

export interface Approval {
  id: string;
  agent_id: string;
  request_id: string;
  tool_name: string;
  action: string;
  arguments: Record<string, unknown>;
  reason: string;
  status: ApprovalState;
  expires_at: string;
  decided_at: string | null;
  created_at: string;
}

export interface Overview {
  policy_version: string | null;
  tools: { name: string; action: string; verified: boolean }[];
  agents: Record<string, number>;
  approvals: Record<string, number>;
  decisions: Record<string, number>;
}

export interface AuditFilters {
  agent_name?: string;
  decision?: string;
  event_type?: string;
  request_id?: string;
  limit?: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

// Empty: same origin (the backend serves the dashboard). Set VITE_API_BASE_URL when the
// dashboard is hosted elsewhere, e.g. on Vercel: https://agentguard.example.com
const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

export function createApi(adminKey: string, fetcher: typeof fetch = fetch, origin = API_ORIGIN) {
  const BASE = `${origin}/api/v1`;

  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    let resp: Response;
    try {
      resp = await fetcher(BASE + path, {
        ...init,
        headers: {
          "X-Admin-Key": adminKey,
          Accept: "application/json",
          ...(init.body ? { "Content-Type": "application/json" } : {}),
        },
        credentials: "omit",
        cache: "no-store",
      });
    } catch {
      throw new ApiError(0, "AgentGuard is not answering. Check that the backend is up and allows this site in AGENTGUARD_CORS_ORIGINS.");
    }
    if (!resp.headers.get("content-type")?.includes("application/json")) {
      // e.g. a static host answering /api/... with its own page: no backend behind it.
      throw new ApiError(0, "No AgentGuard API answered here. Check the dashboard's API address.");
    }
    const body = await resp.json().catch(() => null);
    if (!resp.ok) {
      const detail = body && typeof body.detail === "string" ? body.detail : resp.statusText;
      throw new ApiError(resp.status, detail || `Request failed (${resp.status})`);
    }
    return body as T;
  }

  const post = <T>(path: string) => call<T>(path, { method: "POST" });

  return {
    overview: () => call<Overview>("/overview"),
    agents: () => call<Agent[]>("/agents"),
    registerAgent: (name: string, description: string) =>
      call<AgentCreated>("/agents", {
        method: "POST",
        body: JSON.stringify({ name, description: description || null }),
      }),
    revokeAgent: (id: string) => post<Agent>(`/agents/${encodeURIComponent(id)}/revoke`),
    approvals: (state?: ApprovalState) =>
      call<Approval[]>(state ? `/approvals?state=${state}` : "/approvals"),
    approve: (id: string) => post<Approval>(`/approvals/${encodeURIComponent(id)}/approve`),
    reject: (id: string) => post<Approval>(`/approvals/${encodeURIComponent(id)}/reject`),
    audit: (filters: AuditFilters = {}) => call<AuditEvent[]>(`/audit${query(filters)}`),
    verify: () => call<Verification>("/audit/verify"),
  };
}

export type Api = ReturnType<typeof createApi>;

export function query(params: object): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
