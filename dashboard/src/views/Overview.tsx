import { Badge, Card, CardHead, Empty, Loading, Mono, Notice, PageHeader, th, td, useLoad } from "../ui";

function sum(counts: Record<string, number> | undefined, ...keys: string[]) {
  return keys.reduce((n, k) => n + (counts?.[k] ?? 0), 0);
}

export function OverviewView() {
  const overview = useLoad((api) => api.overview());
  const chain = useLoad((api) => api.verify());
  const o = overview.data;

  const stats = [
    { label: "Allowed", value: sum(o?.decisions, "allow"), note: "tool calls that ran" },
    { label: "Denied", value: sum(o?.decisions, "deny"), note: "stopped by policy or firewall" },
    {
      label: "Sent for approval",
      value: sum(o?.decisions, "approval_required"),
      note: `${sum(o?.approvals, "pending")} waiting now`,
    },
    {
      label: "Active agents",
      value: sum(o?.agents, "active"),
      note: `${sum(o?.agents, "revoked")} revoked`,
    },
  ];

  return (
    <>
      <PageHeader
        title="Overview"
        tagline="What policy decided."
        lead="Every tool call an agent makes passes the firewall and policy before it runs. Here is what they decided."
        actions={
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => {
              overview.reload();
              chain.reload();
            }}
          >
            Refresh
          </button>
        }
      />
      {overview.error && <Notice>{overview.error}</Notice>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="surface rounded-lg border border-line px-5 py-5">
            <p className="text-[13px] font-medium text-muted">{s.label}</p>
            <p className="mt-3 font-display text-[52px] leading-[0.9] text-ink tabular-nums">
              {o ? s.value.toLocaleString() : "–"}
            </p>
            <p className="mt-2 text-[14px] text-text">{s.note}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-12">
        <Card className="min-w-0 lg:col-span-5">
          <CardHead title="Audit chain" meta="hash-chained, append-only" />
          <div className="px-5 py-5">
            {chain.loading && !chain.data ? (
              <p className="text-[15px] text-muted">Checking every event hash…</p>
            ) : chain.error ? (
              <p className="text-[15px] text-deny">{chain.error}</p>
            ) : chain.data?.valid ? (
              <>
                <div className="flex items-center gap-3">
                  <Badge tone="allow">Intact</Badge>
                  <span className="text-[15px] text-ink">
                    {chain.data.events.toLocaleString()} events verified
                  </span>
                </div>
                <p className="mt-3 text-[15px] leading-relaxed text-text">
                  Each event's hash covers the one before it, so an edited or deleted row breaks the chain
                  from that point on.
                </p>
              </>
            ) : (
              <>
                <div className="flex items-center gap-3">
                  <Badge tone="deny">Broken</Badge>
                  <span className="text-[15px] text-ink">
                    First bad event: #{chain.data?.first_invalid_seq}
                  </span>
                </div>
                <p className="mt-3 text-[15px] leading-relaxed text-text">
                  An event no longer matches its hash. Treat the log from that event on as tampered and
                  investigate the database before trusting it.
                </p>
              </>
            )}
            <button type="button" className="btn btn--secondary btn--sm mt-5" onClick={chain.reload}>
              Verify again
            </button>
          </div>
        </Card>

        <Card className="min-w-0 lg:col-span-7">
          <CardHead
            title="Registered tools"
            meta={
              o && (
                <>
                  Policy <Mono>{o.policy_version ?? "unreachable"}</Mono>
                </>
              )
            }
          />
          {overview.loading && !o ? (
            <Loading />
          ) : !o || o.tools.length === 0 ? (
            <Empty title="No tools registered">Agents can only call tools listed in the registry.</Empty>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-line">
                    <th className={th}>Tool</th>
                    <th className={th}>Before policy runs</th>
                  </tr>
                </thead>
                <tbody>
                  {o.tools.map((t) => (
                    <tr key={`${t.name}.${t.action}`} className="border-b border-line last:border-0">
                      <td className={td}>
                        <Mono>
                          {t.name}.{t.action}
                        </Mono>
                      </td>
                      <td className={td}>
                        {t.verified
                          ? "Firewall scan, then facts checked against the payments source"
                          : "Firewall scan"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {o && o.policy_version === null && (
            <p className="border-t border-line px-5 py-3 text-[14px] text-deny">
              OPA is not answering. Every tool call is denied until it is back.
            </p>
          )}
        </Card>
      </div>
    </>
  );
}
