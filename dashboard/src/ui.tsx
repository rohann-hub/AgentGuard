import { type ReactNode, createContext, useCallback, useContext, useEffect, useState } from "react";
import { type Api, ApiError } from "./api";
import { DECISION_LABEL } from "./lib";

// --- session: the api bound to the admin key, and a way to drop it ---

export const Session = createContext<{ api: Api; signOut: (reason?: string) => void } | null>(null);

export function useSession() {
  const s = useContext(Session);
  if (!s) throw new Error("useSession outside <Session>");
  return s;
}

/** Load data from the API. A refused key ends the session instead of showing an error. */
export function useLoad<T>(load: (api: Api) => Promise<T>, deps: unknown[] = []) {
  const { api, signOut } = useSession();
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({
    loading: true,
  });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    load(api).then(
      (data) => live && setState({ data, loading: false }),
      (e: unknown) => {
        if (!live) return;
        if (e instanceof ApiError && e.status === 401) return signOut("The admin key was refused.");
        setState({ error: e instanceof Error ? e.message : String(e), loading: false });
      },
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, tick, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

/** Run a write (approve, revoke, register) with the same 401 handling. */
export function useAction() {
  const { api, signOut } = useSession();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run<T>(id: string, action: (api: Api) => Promise<T>): Promise<T | undefined> {
    setBusy(id);
    setError(null);
    try {
      return await action(api);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) signOut("The admin key was refused.");
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }
  return { run, busy, error, clearError: () => setError(null) };
}

// --- building blocks ---

export function PageHeader({ title, lead, actions }: { title: string; lead: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em] text-ink">{title}</h1>
        <p className="mt-2 max-w-[62ch] text-base leading-relaxed text-text">{lead}</p>
      </div>
      {actions && <div className="flex shrink-0 gap-3">{actions}</div>}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>{children}</section>
  );
}

export function CardHead({ title, meta }: { title: string; meta?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line px-5 py-4">
      <h2 className="text-base font-medium text-ink">{title}</h2>
      {meta && <div className="text-[13px] text-muted">{meta}</div>}
    </div>
  );
}

type Tone = "allow" | "deny" | "wait" | "neutral";

const TONES: Record<Tone, string> = {
  allow: "bg-allow-bg text-allow",
  deny: "bg-deny-bg text-deny",
  wait: "bg-wait-bg text-wait",
  neutral: "bg-sunken text-text",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex h-6 items-center rounded-sm px-2 text-[13px] font-medium whitespace-nowrap ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function toneFor(value: string | null): Tone {
  switch (value) {
    case "allow":
    case "success":
    case "approved":
    case "active":
    case "used":
      return "allow";
    case "deny":
    case "blocked":
    case "rejected":
    case "revoked":
    case "failed":
    case "error":
      return "deny";
    case "approval_required":
    case "pending":
    case "pending_approval":
    case "executing":
      return "wait";
    default:
      return "neutral";
  }
}

const STATUS_LABEL: Record<string, string> = {
  ...DECISION_LABEL,
  pending_approval: "Waiting",
  executing: "Executing",
  success: "Succeeded",
  blocked: "Blocked",
  failed: "Failed",
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  used: "Used",
  expired: "Expired",
  active: "Active",
  revoked: "Revoked",
  error: "Error",
};

export function StatusBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted">none</span>;
  return <Badge tone={toneFor(value)}>{STATUS_LABEL[value] ?? value}</Badge>;
}

export function Notice({ children, onDismiss }: { children: ReactNode; onDismiss?: () => void }) {
  return (
    <div
      role="alert"
      className="mb-6 flex items-start justify-between gap-4 rounded-md border border-deny/30 bg-deny-bg px-4 py-3 text-[15px] text-deny"
    >
      <span>{children}</span>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="link shrink-0 text-deny">
          Dismiss
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="px-5 py-12 text-center">
      <p className="text-base font-medium text-ink">{title}</p>
      <p className="mx-auto mt-1 max-w-[52ch] text-[15px] text-muted">{children}</p>
    </div>
  );
}

export function Loading() {
  return (
    <div className="px-5 py-12 text-center text-[15px] text-muted" role="status">
      Loading…
    </div>
  );
}

export function Mono({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span className="font-mono text-[13px] whitespace-nowrap text-text" title={title}>
      {children}
    </span>
  );
}

export const th = "px-5 py-3 text-left text-[13px] font-medium text-muted whitespace-nowrap";
export const td = "px-5 py-3 align-top text-[14px] text-text";
