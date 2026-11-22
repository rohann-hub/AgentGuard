import { Fragment, useState } from "react";
import type { AuditEvent } from "../api";
import { formatTime, shortHash } from "../lib";
import { Badge, Mono, StatusBadge, td, th } from "../ui";

export function EventTable({ events }: { events: AuditEvent[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-line">
            <th className={th}>#</th>
            <th className={th}>Time</th>
            <th className={th}>Agent</th>
            <th className={th}>Tool</th>
            <th className={th}>Event</th>
            <th className={th}>Decision</th>
            <th className={th}>Outcome</th>
            <th className={th}>Reason</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => {
            const expanded = open === e.seq;
            return (
              <Fragment key={e.seq}>
                <tr
                  className={`border-b border-line transition-colors duration-150 hover:bg-sunken ${expanded ? "bg-sunken" : ""}`}
                >
                  <td className={td}>
                    <button
                      type="button"
                      aria-expanded={expanded}
                      aria-controls={`event-${e.seq}`}
                      onClick={() => setOpen(expanded ? null : e.seq)}
                      className="link font-mono text-[13px] whitespace-nowrap"
                    >
                      {e.seq}
                      <span className="sr-only">{expanded ? ", hide details" : ", show details"}</span>
                    </button>
                  </td>
                  <td className={`${td} whitespace-nowrap`}>{formatTime(e.created_at)}</td>
                  <td className={td}>
                    <Mono>{e.agent_name}</Mono>
                  </td>
                  <td className={td}>
                    <Mono>
                      {e.tool_name}.{e.action}
                    </Mono>
                  </td>
                  <td className={`${td} capitalize`}>{e.event_type}</td>
                  <td className={td}>
                    {e.decision ? (
                      <StatusBadge value={e.decision} />
                    ) : (
                      <span className="text-[14px] whitespace-nowrap text-muted" title="Stopped before policy ran">
                        Not reached
                      </span>
                    )}
                  </td>
                  <td className={td}>
                    <StatusBadge value={e.status} />
                  </td>
                  <td className={`${td} min-w-[220px]`}>
                    {e.reason ?? <span className="text-muted">none</span>}
                    {e.firewall.length > 0 && (
                      <span className="mt-1 flex flex-wrap gap-1">
                        {e.firewall.map((f, i) => (
                          <Badge key={i} tone={f.action === "block" ? "deny" : "neutral"}>
                            {f.entity_type} {f.action === "block" ? "blocked" : f.action === "redact" ? "redacted" : "allowed"}
                          </Badge>
                        ))}
                      </span>
                    )}
                  </td>
                </tr>
                {expanded && (
                  <tr id={`event-${e.seq}`} className="border-b border-line bg-sunken">
                    <td colSpan={8} className="px-5 pt-1 pb-5">
                      <dl className="grid gap-x-8 gap-y-3 text-[14px] sm:grid-cols-2 lg:grid-cols-3">
                        <Detail label="Request ID" value={e.request_id} />
                        <Detail label="Policy version" value={e.policy_version ?? "none"} />
                        <Detail label="Approval" value={e.approval_id ?? "none"} />
                        <Detail label="Request fingerprint" value={shortHash(e.request_fingerprint)} full={e.request_fingerprint} />
                        <Detail label="Response fingerprint" value={shortHash(e.response_fingerprint)} full={e.response_fingerprint} />
                        <Detail label="Event hash" value={shortHash(e.event_hash)} full={e.event_hash} />
                        <Detail label="Previous hash" value={shortHash(e.prev_hash)} full={e.prev_hash} />
                        {e.firewall.length > 0 && (
                          <div className="sm:col-span-2">
                            <dt className="text-[13px] text-muted">Firewall findings (types and paths only, never values)</dt>
                            <dd className="mt-1 font-mono text-[13px] text-ink">
                              {e.firewall.map((f) => `${f.path}: ${f.entity_type} (${f.action})`).join(", ")}
                            </dd>
                          </div>
                        )}
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Detail({ label, value, full }: { label: string; value: string; full?: string | null }) {
  return (
    <div className="min-w-0">
      <dt className="text-[13px] text-muted">{label}</dt>
      <dd className="mt-1 font-mono text-[13px] break-all text-ink" title={full ?? undefined}>
        {value}
      </dd>
    </div>
  );
}
