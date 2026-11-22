import { type FormEvent, useMemo, useState } from "react";
import { ApiError, createApi } from "./api";
import { Session } from "./ui";
import { AgentsView } from "./views/Agents";
import { ApprovalsView } from "./views/Approvals";
import { AuditView } from "./views/Audit";
import { OverviewView } from "./views/Overview";
import { SecurityView } from "./views/Security";

const VIEWS = [
  { id: "overview", label: "Overview", View: OverviewView },
  { id: "approvals", label: "Approvals", View: ApprovalsView },
  { id: "agents", label: "Agents", View: AgentsView },
  { id: "security", label: "Security", View: SecurityView },
  { id: "audit", label: "Audit log", View: AuditView },
] as const;

type ViewId = (typeof VIEWS)[number]["id"];

export function App() {
  // The key is held in React state only: a reload or a closed tab forgets it.
  const [key, setKey] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [view, setView] = useState<ViewId>("overview");
  const api = useMemo(() => (key ? createApi(key) : null), [key]);

  const session = useMemo(
    () =>
      api && {
        api,
        signOut: (reason?: string) => {
          setKey(null);
          setNotice(reason ?? null);
        },
      },
    [api],
  );

  if (!session) {
    return (
      <SignIn
        notice={notice}
        onSignIn={(k) => {
          setNotice(null);
          setView("overview");
          setKey(k);
        }}
      />
    );
  }

  const Current = VIEWS.find((v) => v.id === view)!.View;
  return (
    <Session.Provider value={session}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-4 focus:z-20 focus:rounded-md focus:bg-accent focus:px-4 focus:py-2 focus:text-on-accent"
      >
        Skip to content
      </a>
      <header className="surface sticky top-0 z-10 border-b border-line">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-x-8 px-4 sm:h-16 sm:flex-nowrap sm:px-8">
          <span className="flex h-14 items-center sm:h-auto">
            <Wordmark />
          </span>
          <nav
            aria-label="Dashboard"
            className="order-last -mx-3 flex w-[calc(100%+24px)] gap-1 overflow-x-auto sm:order-none sm:mx-0 sm:w-auto sm:flex-1"
          >
            {VIEWS.map((v) => (
              <button
                key={v.id}
                type="button"
                onClick={() => setView(v.id)}
                aria-current={v.id === view ? "page" : undefined}
                className="relative h-11 shrink-0 px-3 text-[15px] font-medium text-muted transition-colors duration-150 hover:text-ink aria-[current=page]:text-ink"
              >
                {v.label}
                <span
                  aria-hidden
                  className={`absolute inset-x-3 bottom-0 sm:-bottom-[10px] h-0.5 bg-moonstone transition-transform duration-200 ${
                    v.id === view ? "scale-x-100" : "scale-x-0"
                  }`}
                />
              </button>
            ))}
          </nav>
          <button type="button" className="btn btn--secondary btn--sm shrink-0" onClick={() => session.signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-[1280px] px-4 pt-10 pb-24 sm:px-8">
        <Current />
      </main>
    </Session.Provider>
  );
}

function Wordmark() {
  return (
    <span className="flex shrink-0 items-center gap-2 text-[17px] font-semibold tracking-[-0.01em] text-ink">
      <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden>
        <rect width="24" height="24" rx="5" className="fill-accent" />
        <path
          d="M12 5l6 2.4v4.3c0 3.6-2.5 6.3-6 7.3-3.5-1-6-3.7-6-7.3V7.4z"
          fill="none"
          strokeWidth="1.8"
          strokeLinejoin="round"
          className="stroke-on-accent"
        />
      </svg>
      AgentGuard
    </span>
  );
}

function SignIn({ notice, onSignIn }: { notice: string | null; onSignIn: (key: string) => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(notice);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const k = value.trim();
    if (!k) return setError("Paste the admin key to continue.");
    setBusy(true);
    setError(null);
    try {
      await createApi(k).overview();
      onSignIn(k);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That key was refused. Check it against AGENTGUARD_ADMIN_API_KEY_HASH."
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-16">
      <div className="surface w-full max-w-[460px] rounded-lg border border-line px-8 py-10 sm:px-10">
        <Wordmark />
        <h1 className="mt-12 font-display text-[52px] leading-[0.98] font-normal tracking-[-0.015em] text-ink">
          Review what
          <span className="block text-display-soft">your agents do.</span>
        </h1>
        <p className="mt-5 text-base leading-relaxed text-text">
          Approve held refunds, revoke agents and check the audit chain. Sign in with the admin key.
        </p>
        <form onSubmit={submit} noValidate className="mt-8">
          <label htmlFor="admin-key" className="block text-[14px] font-medium text-ink">
            Admin key
          </label>
          <input
            id="admin-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            className="field mt-2 font-mono"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby="admin-key-help"
            autoFocus
          />
          <p id="admin-key-help" className="mt-2 text-[14px] text-muted">
            {error ? (
              <span className="text-deny" role="alert">
                {error}
              </span>
            ) : (
              "Kept in this tab's memory only. Reloading or closing the tab forgets it."
            )}
          </p>
          <button type="submit" className="btn btn--primary mt-6 w-full" disabled={busy}>
            {busy ? "Checking key…" : "Open the dashboard"}
          </button>
        </form>
      </div>
    </main>
  );
}
