import { type FormEvent, type ReactNode, useState } from "react";
import type { AuditFilters } from "../api";
import { Card, CardHead, Empty, Loading, Notice, PageHeader, useLoad } from "../ui";
import { EventTable } from "./EventTable";

const LIMIT = 200;

export function AuditView() {
  const [filters, setFilters] = useState<AuditFilters>({});
  const [draft, setDraft] = useState<AuditFilters>({});
  const events = useLoad((api) => api.audit({ ...filters, limit: LIMIT }), [JSON.stringify(filters)]);
  const agents = useLoad((api) => api.agents());

  function apply(e: FormEvent) {
    e.preventDefault();
    setFilters({ ...draft, request_id: draft.request_id?.trim() });
  }

  const set = (k: keyof AuditFilters) => (e: { target: { value: string } }) =>
    setDraft((d) => ({ ...d, [k]: e.target.value }));

  return (
    <>
      <PageHeader
        title="Audit log"
        tagline="Every decision, chained."
        lead="Every decision and every execution, newest first. Arguments and responses are stored only as fingerprints, so nothing sensitive is shown here."
      />
      {events.error && <Notice>{events.error}</Notice>}

      <form onSubmit={apply} className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_1.4fr_auto] lg:items-end">
        <Filter label="Agent" id="f-agent">
          <select id="f-agent" className="field" value={draft.agent_name ?? ""} onChange={set("agent_name")}>
            <option value="">All agents</option>
            {agents.data?.map((a) => (
              <option key={a.id} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>
        </Filter>
        <Filter label="Decision" id="f-decision">
          <select id="f-decision" className="field" value={draft.decision ?? ""} onChange={set("decision")}>
            <option value="">Any decision</option>
            <option value="allow">Allowed</option>
            <option value="deny">Denied</option>
            <option value="approval_required">Needs approval</option>
          </select>
        </Filter>
        <Filter label="Event" id="f-event">
          <select id="f-event" className="field" value={draft.event_type ?? ""} onChange={set("event_type")}>
            <option value="">Any event</option>
            <option value="decision">Decision</option>
            <option value="execution">Execution</option>
            <option value="error">Error</option>
          </select>
        </Filter>
        <Filter label="Request ID" id="f-request">
          <input
            id="f-request"
            className="field font-mono"
            value={draft.request_id ?? ""}
            onChange={set("request_id")}
            placeholder="req_…"
            spellCheck={false}
          />
        </Filter>
        <button type="submit" className="btn btn--primary">
          Show events
        </button>
      </form>

      <Card>
        <CardHead
          title="Events"
          meta={events.data && (events.data.length === LIMIT ? `latest ${LIMIT}` : `${events.data.length} shown`)}
        />
        {events.loading && !events.data ? (
          <Loading />
        ) : !events.data?.length ? (
          <Empty title="No events match">Agents' calls through the proxy appear here as they happen.</Empty>
        ) : (
          <EventTable events={events.data} />
        )}
      </Card>
    </>
  );
}

function Filter({ label, id, children }: { label: string; id: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="block text-[14px] font-medium text-ink">
        {label}
      </label>
      <div className="mt-2">{children}</div>
    </div>
  );
}
