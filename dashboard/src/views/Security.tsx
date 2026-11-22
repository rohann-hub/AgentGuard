import { countFindings, isSecurityEvent } from "../lib";
import { Badge, Card, CardHead, Empty, Loading, Notice, PageHeader, td, th, useLoad } from "../ui";
import { EventTable } from "./EventTable";

const SCAN = 1000;

export function SecurityView() {
  const events = useLoad((api) => api.audit({ limit: SCAN }));
  const flagged = events.data?.filter(isSecurityEvent) ?? [];
  const findings = countFindings(flagged);
  const blocked = flagged.filter((e) => e.status === "blocked" && e.event_type === "decision").length;

  return (
    <>
      <PageHeader
        title="Security events"
        lead={`Denied calls and everything the firewall caught in the latest ${SCAN.toLocaleString()} audit events. Secrets block the call; personal data is redacted before policy and the tool see it.`}
        actions={
          <button type="button" className="btn btn--secondary" onClick={events.reload}>
            Refresh
          </button>
        }
      />
      {events.error && <Notice>{events.error}</Notice>}

      {events.loading && !events.data ? (
        <Card>
          <Loading />
        </Card>
      ) : (
        <div className="grid gap-6">
          <Card className="min-w-0 lg:max-w-[560px]">
            <CardHead title="Firewall findings" meta={`${blocked} calls blocked`} />
            {findings.length === 0 ? (
              <Empty title="Nothing caught">No secrets or personal data in recent calls.</Empty>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-line">
                    <th className={th}>Type</th>
                    <th className={th}>Action</th>
                    <th className={`${th} text-right`}>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((f) => (
                    <tr key={`${f.type}:${f.action}`} className="border-b border-line last:border-0">
                      <td className={`${td} font-mono text-[13px]`}>{f.type}</td>
                      <td className={td}>
                        <Badge tone={f.action === "block" ? "deny" : "neutral"}>
                          {f.action === "block" ? "Blocked" : f.action === "redact" ? "Redacted" : "Allowed"}
                        </Badge>
                      </td>
                      <td className={`${td} text-right font-mono tabular-nums`}>{f.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card className="min-w-0">
            <CardHead title="Flagged events" meta={`${flagged.length} of ${events.data?.length ?? 0}`} />
            {flagged.length === 0 ? (
              <Empty title="No security events">Denied calls and firewall findings show up here.</Empty>
            ) : (
              <EventTable events={flagged} />
            )}
          </Card>
        </div>
      )}
    </>
  );
}
