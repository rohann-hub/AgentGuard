import { type FormEvent, useState } from "react";
import type { Agent, AgentCreated } from "../api";
import { formatTime } from "../lib";
import {
  Card,
  CardHead,
  Empty,
  Loading,
  Mono,
  Notice,
  PageHeader,
  StatusBadge,
  td,
  th,
  useAction,
  useLoad,
} from "../ui";

const NAME = /^[a-z0-9][a-z0-9_-]*$/;

export function AgentsView() {
  const agents = useLoad((api) => api.agents());
  const action = useAction();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [created, setCreated] = useState<AgentCreated | null>(null);

  async function revoke(a: Agent) {
    const done = await action.run(a.id, (api) => api.revokeAgent(a.id));
    setConfirming(null);
    if (done) agents.reload();
  }

  return (
    <>
      <PageHeader
        title="Agents"
        tagline="Who holds a key."
        lead="Each agent calls AgentGuard with its own key. Revoking an agent stops its key at once; past audit events stay."
      />
      {(agents.error || action.error) && (
        <Notice onDismiss={action.error ? action.clearError : undefined}>
          {action.error ?? agents.error}
        </Notice>
      )}

      <div className="grid gap-6 lg:grid-cols-12">
        <Card className="min-w-0 lg:col-span-8">
          <CardHead title="Registered agents" meta={agents.data && `${agents.data.length} total`} />
          {agents.loading && !agents.data ? (
            <Loading />
          ) : !agents.data?.length ? (
            <Empty title="No agents yet">Register one to give it a key for the proxy.</Empty>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-line">
                    <th className={th}>Agent</th>
                    <th className={th}>Status</th>
                    <th className={th}>Registered</th>
                    <th className={th}>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {agents.data.map((a) => (
                    <tr key={a.id} className="border-b border-line last:border-0">
                      <td className={td}>
                        <Mono>{a.name}</Mono>
                        {a.description && <p className="mt-1 max-w-[48ch] text-[14px] text-muted">{a.description}</p>}
                      </td>
                      <td className={td}>
                        <StatusBadge value={a.status} />
                      </td>
                      <td className={`${td} whitespace-nowrap`}>{formatTime(a.created_at)}</td>
                      <td className={`${td} text-right whitespace-nowrap`}>
                        {a.status === "active" &&
                          (confirming === a.id ? (
                            <span className="inline-flex items-center gap-2">
                              <button
                                type="button"
                                className="btn btn--danger btn--sm"
                                disabled={action.busy !== null}
                                onClick={() => revoke(a)}
                              >
                                {action.busy === a.id ? "Revoking…" : `Revoke ${a.name}`}
                              </button>
                              <button
                                type="button"
                                className="btn btn--secondary btn--sm"
                                onClick={() => setConfirming(null)}
                              >
                                Keep
                              </button>
                            </span>
                          ) : (
                            <button
                              type="button"
                              className="btn btn--secondary btn--sm"
                              onClick={() => setConfirming(a.id)}
                            >
                              Revoke…
                            </button>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="min-w-0 lg:col-span-4">
          {created ? (
            <NewKey agent={created} onDone={() => setCreated(null)} />
          ) : (
            <RegisterForm
              onCreated={(a) => {
                setCreated(a);
                agents.reload();
              }}
            />
          )}
        </div>
      </div>
    </>
  );
}

function RegisterForm({ onCreated }: { onCreated: (a: AgentCreated) => void }) {
  const action = useAction();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const n = name.trim();
    if (!NAME.test(n) || n.length > 64) {
      setNameError("Use lowercase letters, digits, - or _, starting with a letter or digit.");
      document.getElementById("agent-name")?.focus();
      return;
    }
    setNameError(null);
    const agent = await action.run("register", (api) => api.registerAgent(n, description.trim()));
    if (agent) {
      setName("");
      setDescription("");
      onCreated(agent);
    }
  }

  return (
    <Card>
      <CardHead title="Register an agent" />
      <form onSubmit={submit} noValidate className="px-5 py-5">
        <label htmlFor="agent-name" className="block text-[14px] font-medium text-ink">
          Name
        </label>
        <input
          id="agent-name"
          className="field mt-2 font-mono"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="billing-agent"
          autoComplete="off"
          spellCheck={false}
          maxLength={64}
          aria-invalid={nameError ? true : undefined}
          aria-describedby="agent-name-error"
        />
        <p id="agent-name-error" className="mt-2 min-h-5 text-[14px] text-deny">
          {nameError}
        </p>
        <label htmlFor="agent-description" className="mt-2 block text-[14px] font-medium text-ink">
          What it does <span className="font-normal text-muted">(optional)</span>
        </label>
        <input
          id="agent-description"
          className="field mt-2"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={1000}
        />
        {action.error && (
          <p role="alert" className="mt-3 text-[14px] text-deny">
            {action.error}
          </p>
        )}
        <button type="submit" className="btn btn--primary mt-5 w-full" disabled={action.busy !== null}>
          {action.busy ? "Registering…" : "Register agent"}
        </button>
      </form>
    </Card>
  );
}

function NewKey({ agent, onDone }: { agent: AgentCreated; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Card className="border-ink">
      <CardHead title={`Key for ${agent.name}`} />
      <div className="px-5 py-5">
        <p className="text-[15px] leading-relaxed text-text">
          This is the only time the key is shown. AgentGuard keeps just its hash. Store it in the agent's
          secret manager now.
        </p>
        <code className="mt-4 block rounded-md border border-line bg-sunken px-3 py-3 font-mono text-[13px] break-all text-ink select-all">
          {agent.api_key}
        </code>
        <div className="mt-5 flex gap-3">
          <button
            type="button"
            className="btn btn--primary flex-1"
            onClick={() =>
              navigator.clipboard.writeText(agent.api_key).then(
                () => setCopied(true),
                () => setCopied(false),
              )
            }
          >
            {copied ? "Copied" : "Copy key"}
          </button>
          <button type="button" className="btn btn--secondary" onClick={onDone}>
            Done
          </button>
        </div>
        <p className="mt-3 text-[13px] text-muted" role="status">
          {copied ? "The key is on your clipboard." : <>Send it as <Mono>X-API-Key</Mono>.</>}
        </p>
      </div>
    </Card>
  );
}
